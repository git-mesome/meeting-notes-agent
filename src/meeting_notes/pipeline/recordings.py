"""회의를 올린 뒤에 더 올린 녹음. 새 녹음만 전사해 앞 녹음 뒤에 잇는다.

더 올린 녹음은 added에 받아 두고, 처리를 시작할 때 앞 녹음 뒤에 넣는다(take_added). 처리하는 동안에도 받을 수 있다.
앞 녹음을 아직 전사하지 않았으면 parts에 넣어 이어서 한 번에 전사한다(pipeline/audio.py).

전사한 녹음이 있으면 녹음과 녹음마다의 전사를 recordings/1.m4a, recordings/1.json처럼 번호를 붙여 두고, 재생과
회의록에 쓰는 audio.m4a와 audio.json은 거기서 다시 만든다. 처음 더 올릴 때 원래 녹음과 전사를 1번으로 옮긴다.

녹음마다 화자 구분을 따로 해서 같은 사람도 라벨이 다르게 나온다. 목소리 특징으로 앞 녹음의 화자와 짝짓고,
짝이 없으면 앞 녹음에 없는 라벨을 붙인다. 앞 녹음의 라벨은 그대로라 정해 둔 화자 이름도 그대로 맞는다.
"""

import json
import os
import shutil

from meeting_notes.errors import AppError
from meeting_notes.pipeline.audio import (
    JOINED_AUDIO,
    MAX_RECORDINGS,
    PARTS_DIR,
    concat_audio,
    find_audio,
    find_parts,
    numbered,
    probe_duration,
)
from meeting_notes.speakers.names import SPEAKER_LABEL
from meeting_notes.speakers.voices import MATCH_THRESHOLD, cosine

ADDED_DIR = "added"
RECORDINGS_DIR = "recordings"
# 녹음 전체의 전사. WhisperX가 audio.m4a를 전사하면 이 이름으로 쓴다.
TRANSCRIPT = "audio.json"


def find_recordings(job_dir):
    return numbered(job_dir / RECORDINGS_DIR)


def find_added(job_dir):
    return numbered(job_dir / ADDED_DIR)


def stage_recording(job_dir, suffix, incoming):
    """회의 끝에 녹음을 하나 더 받아 둔다. 앞 녹음 뒤에 넣는 일은 처리하는 쪽이 한다(take_added)."""
    count = (len(find_recordings(job_dir)) or len(find_parts(job_dir)) or 1) + len(find_added(job_dir))
    if count >= MAX_RECORDINGS:
        raise AppError(f"녹음은 한 회의에 {MAX_RECORDINGS}개까지 올릴 수 있어요.")
    folder = job_dir / ADDED_DIR
    folder.mkdir(exist_ok=True)
    os.replace(incoming, folder / f"{len(find_added(job_dir)) + 1}{suffix}")


def take_added(job_dir):
    """받아 둔 녹음을 앞 녹음 뒤에 넣는다. 처리하는 쪽만 부른다.

    전사한 녹음이 없으면 parts에 넣어 앞 녹음과 이어 한 번에 전사하고, 있으면 recordings에 넣어 새 녹음만 전사한다.
    """
    if not (job_dir / TRANSCRIPT).exists() and not find_recordings(job_dir):
        folder = job_dir / PARTS_DIR
        if not find_parts(job_dir):
            audio = find_audio(job_dir)
            folder.mkdir()
            os.replace(audio, folder / f"1{audio.suffix}")
    else:
        folder = job_dir / RECORDINGS_DIR
        if folder.is_dir():
            # 이어 만든 전사를 지워 다시 만들게 한다.
            (job_dir / TRANSCRIPT).unlink(missing_ok=True)
        else:
            audio = find_audio(job_dir)
            folder.mkdir()
            os.replace(audio, folder / f"1{audio.suffix}")
            if (job_dir / TRANSCRIPT).exists():
                os.replace(job_dir / TRANSCRIPT, folder / "1.json")
    for number, path in enumerate(find_added(job_dir), len(numbered(folder)) + 1):
        os.replace(path, folder / f"{number}{path.suffix}")
    shutil.rmtree(job_dir / ADDED_DIR)


def untranscribed_seconds(job_dir):
    """recordings에서 아직 전사하지 않은 녹음의 길이. 남은 시간을 어림할 때 쓴다."""
    return sum(probe_duration(audio) for audio in find_recordings(job_dir) if not audio.with_suffix(".json").exists())


def needs_merge(job_dir):
    return bool(find_recordings(job_dir)) and not (job_dir / TRANSCRIPT).exists()


def merge_recordings(job_dir, transcribe, on_process=lambda process: None):
    """전사하지 않은 녹음만 전사하고, 녹음과 전사를 순서대로 이어 audio.m4a와 audio.json을 만든다.

    transcribe(audio, out_dir, on_process)는 out_dir에 <녹음 이름>.json을 쓴다(pipeline/transcribe.py).
    audio.json을 마지막에 써서, 중간에 멈추면 다음에 처음부터 다시 잇는다.
    """
    recordings = find_recordings(job_dir)
    for audio in recordings:
        if not audio.with_suffix(".json").exists():
            transcribe(audio, audio.parent, on_process)
    transcripts = [json.loads(audio.with_suffix(".json").read_text(encoding="utf-8")) for audio in recordings]
    durations = [probe_duration(audio) for audio in recordings]
    concat_audio(recordings, job_dir / JOINED_AUDIO, on_process)
    temp = job_dir / f"{TRANSCRIPT}.tmp"
    temp.write_text(json.dumps(merge_transcripts(transcripts, durations), ensure_ascii=False), encoding="utf-8")
    os.replace(temp, job_dir / TRANSCRIPT)


def merge_transcripts(transcripts, durations):
    """녹음마다의 전사를 하나로 잇는다. 뒤 녹음의 시각은 앞 녹음 길이만큼 미루고 화자 라벨은 앞 녹음에 맞춘다."""
    segments, voices, used = [], {}, set()
    offset = 0.0
    for transcript, duration in zip(transcripts, durations):
        labels = relabel(transcript, voices, used)
        segments += [moved(segment, offset, labels) for segment in transcript["segments"]]
        offset += duration
    return {"segments": segments, "speaker_embeddings": voices}


def relabel(transcript, voices, used):
    """이 녹음의 화자 라벨을 앞 녹음까지의 라벨로 바꾸는 표를 만들고, voices와 used에 새 화자를 더한다.

    목소리가 가장 비슷한 쌍부터 짝짓고 한 화자는 한 번만 짝짓는다(speakers/voices.py의 match와 같다).
    """
    embeddings = transcript.get("speaker_embeddings") or {}
    speakers = {
        item["speaker"]
        for segment in transcript["segments"]
        for item in (segment, *segment.get("words", []))
        if "speaker" in item
    } | set(embeddings)
    pairs = sorted(
        ((cosine(embedding, voices[known]), label, known) for label, embedding in embeddings.items() for known in voices),
        reverse=True,
    )
    labels = {}
    for score, label, known in pairs:
        if score < MATCH_THRESHOLD:
            break
        if label not in labels and known not in labels.values():
            labels[label] = known
    for label in sorted(speakers - set(labels)):
        new = label if label not in used else next_label(used)
        labels[label] = new
        used.add(new)
        if label in embeddings:
            voices[new] = embeddings[label]
    return labels


def next_label(used):
    numbers = [int(label.rsplit("_", 1)[1]) for label in used if SPEAKER_LABEL.fullmatch(label)]
    return f"SPEAKER_{max(numbers, default=-1) + 1:02d}"


def moved(item, offset, labels):
    """구간이나 단어의 시각을 offset만큼 미루고 화자 라벨을 바꾼다."""
    item = dict(item)
    for key in ("start", "end"):
        if key in item:
            item[key] = round(item[key] + offset, 3)
    if "speaker" in item:
        item["speaker"] = labels[item["speaker"]]
    if "words" in item:
        item["words"] = [moved(word, offset, labels) for word in item["words"]]
    return item
