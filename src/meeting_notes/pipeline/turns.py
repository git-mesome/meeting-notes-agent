"""WhisperX 결과를 화자별 발언으로 정리하고 전사문을 만든다."""

import re

from meeting_notes.pipeline.spelling import fix_spelling

# 무음 구간에서 Whisper가 지어내는 문구. 화자가 잡히지 않았을 때만 제거한다.
HALLUCINATIONS = {"감사합니다", "수고하셨습니다", "시청해주셔서감사합니다"}


def format_time(seconds):
    minutes, secs = divmod(int(seconds), 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes:02d}:{secs:02d}"


def is_hallucination(segment):
    text = re.sub(r"[\s.,!?]", "", segment.get("text", ""))
    has_speaker = any("speaker" in word for word in segment.get("words", []))
    return text in HALLUCINATIONS and not has_speaker


def to_turns(segments):
    """세그먼트를 단어별 화자가 바뀌는 지점에서 나눈다. 화자가 없는 단어는 앞 단어의 화자를 따른다."""
    turns = []
    for segment in segments:
        if is_hallucination(segment):
            continue
        speaker = segment.get("speaker", "UNKNOWN")
        words = segment.get("words")
        if not words:
            turns.append(
                {"start": segment["start"], "end": segment["end"], "speaker": speaker, "text": segment["text"].strip()}
            )
            continue
        turn = None
        for word in words:
            speaker = word.get("speaker", speaker)
            if turn is None or turn["speaker"] != speaker:
                start = word.get("start", turn["end"] if turn else segment["start"])
                turn = {"start": start, "end": start, "speaker": speaker, "words": []}
                turns.append(turn)
            turn["words"].append(word["word"])
            turn["end"] = word.get("end", turn["end"])
    return [
        {
            "start": t["start"],
            "end": t["end"],
            "speaker": t["speaker"],
            "text": fix_spelling(" ".join(t["words"]) if "words" in t else t["text"]),
        }
        for t in turns
    ]


def format_transcript(turns):
    return "\n".join(f"[{format_time(t['start'])}] {t['speaker']}: {t['text']}" for t in turns)
