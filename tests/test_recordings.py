"""한 회의에 녹음 여럿 올리기. 한 번에 올리면 이어서 한 번에 전사하고, 나중에 더 올리면 새 녹음만 전사해 잇는다."""

import json
import re
import subprocess
import threading

import pytest
from fastapi.testclient import TestClient

from meeting_notes.main import create_app
from meeting_notes.pipeline.audio import probe_duration
from meeting_notes.pipeline.recordings import merge_transcripts
from meeting_notes.pipeline.turns import to_turns
from meeting_notes.speakers.voices import VoiceBook
from meeting_notes.web.routers import jobs as jobs_router
from tests.test_app import client, tone, upload, wait_for  # noqa: F401


def segment(start, speaker, text):
    return {
        "start": start,
        "end": start + 0.4,
        "text": text,
        "speaker": speaker,
        "words": [{"word": text, "start": start, "end": start + 0.4, "speaker": speaker}],
    }


# 앞 녹음: 두 사람. 뒤 녹음: SPEAKER_00은 앞 녹음의 SPEAKER_01과 목소리가 같고, SPEAKER_01은 처음 나온 사람이다.
FIRST = {
    "segments": [segment(0.0, "SPEAKER_00", "앞 녹음 첫 발언"), segment(0.5, "SPEAKER_01", "앞 녹음 둘째 발언")],
    "speaker_embeddings": {"SPEAKER_00": [1.0, 0.0, 0.0], "SPEAKER_01": [0.0, 1.0, 0.0]},
}
SECOND = {
    "segments": [segment(0.0, "SPEAKER_01", "뒤 녹음 새 사람"), segment(0.5, "SPEAKER_00", "뒤 녹음 아는 사람")],
    "speaker_embeddings": {"SPEAKER_00": [0.1, 0.99, 0.0], "SPEAKER_01": [0.0, 0.0, 1.0]},
}


def transcript_for(audio):
    return FIRST if audio.stem == "audio" else SECOND


def make_site(tmp_path, gate=None):
    """process는 process_audio처럼 전사가 없을 때만 전사하고, transcribe는 더 올린 녹음을 전사한다. 전사한 녹음 이름을 남긴다.

    gate를 넘기면 회의록을 쓰기 전에 gate가 열릴 때까지 기다린다.
    """
    transcribed = []

    def transcribe(audio, out_dir, _on_process=None):
        transcribed.append(audio.name)
        (out_dir / f"{audio.stem}.json").write_text(json.dumps(transcript_for(audio), ensure_ascii=False), encoding="utf-8")

    def process(audio, out_dir, on_stage, on_process):
        if not (out_dir / "audio.json").exists():
            on_stage("transcribing")
            transcribe(audio, out_dir, on_process)
        segments = json.loads((out_dir / "audio.json").read_text(encoding="utf-8"))["segments"]
        (out_dir / "turns.json").write_text(json.dumps(to_turns(segments), ensure_ascii=False), encoding="utf-8")
        on_stage("writing")
        if gate:
            gate.wait(5)
        (out_dir / "notes.md").write_text("# 회의록: 녹음 여럿\n", encoding="utf-8")
        return {"input_tokens": 1, "output_tokens": 1}

    app = create_app(data_dir=tmp_path, process=process, transcribe=transcribe, tracker=None, auth=None)
    return TestClient(app, base_url="http://127.0.0.1"), transcribed


def add(client, job_id, data, name="뒤 녹음.m4a"):
    return client.post(f"/api/jobs/{job_id}/recordings", files={"file": (name, data, "audio/mp4")})


def mean_volume(path, start, length):
    result = subprocess.run(
        ["ffmpeg", "-ss", str(start), "-t", str(length), "-i", str(path), "-af", "volumedetect", "-f", "null", "-"],
        capture_output=True,
        text=True,
    )
    return float(re.search(r"mean_volume: (-?[\d.]+) dB", result.stderr).group(1))


@pytest.fixture(scope="session")
def silence(tmp_path_factory):
    path = tmp_path_factory.mktemp("audio") / "silence.m4a"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono", "-t", "1", str(path)], check=True)
    return path.read_bytes()


@pytest.fixture(scope="session")
def wav_tone(tmp_path_factory):
    path = tmp_path_factory.mktemp("audio") / "tone.wav"
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "sine=frequency=660:duration=1:sample_rate=16000", str(path)],
        check=True,
    )
    return path.read_bytes()


# 한 번에 올리기


def test_recordings_sent_together_become_one_meeting_in_order(client, silence, wav_tone, tmp_path):
    response = client.post(
        "/api/jobs",
        files=[("file", ("회의 1.m4a", silence, "audio/mp4")), ("file", ("회의 2.wav", wav_tone, "audio/wav"))],
    )
    assert response.status_code == 201
    job = response.json()
    assert job["name"] == "회의 1.m4a 외 1개"
    assert job["duration_seconds"] == pytest.approx(2.0, abs=0.2)
    assert wait_for(client, job["id"], "done")["status"] == "done"
    assert len(client.get("/api/jobs").json()) == 1

    job_dir = tmp_path / job["id"]
    assert not (job_dir / "parts").exists()
    joined = job_dir / "audio.m4a"
    assert probe_duration(joined) == pytest.approx(2.0, abs=0.2)
    # 고요한 녹음을 먼저 담았으니 앞 절반은 조용하고 뒤 절반에 소리가 있다.
    assert mean_volume(joined, 0.1, 0.7) < mean_volume(joined, 1.2, 0.7) - 30


def test_too_many_recordings_at_once_are_refused(client, tone, tmp_path):
    files = [("file", (f"{number}.m4a", tone, "audio/mp4")) for number in range(6)]
    response = client.post("/api/jobs", files=files)
    assert response.status_code == 400
    assert "5개까지" in response.json()["detail"]
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(("second", "name"), [(b"not audio", "b.m4a"), (b"text", "b.txt")])
def test_one_bad_recording_refuses_all(client, tone, tmp_path, second, name):
    files = [("file", ("a.m4a", tone, "audio/mp4")), ("file", (name, second, "audio/mp4"))]
    assert client.post("/api/jobs", files=files).status_code == 400
    assert list(tmp_path.iterdir()) == []


def test_size_limit_counts_all_recordings_together(client, tone, tmp_path, monkeypatch):
    monkeypatch.setattr(jobs_router, "MAX_UPLOAD_BYTES", len(tone) + len(tone) // 2)
    files = [("file", ("a.m4a", tone, "audio/mp4")), ("file", ("b.m4a", tone, "audio/mp4"))]
    assert client.post("/api/jobs", files=files).status_code == 413
    assert list(tmp_path.iterdir()) == []


# 나중에 더 올리기


def test_merge_keeps_first_labels_and_matches_later_speakers_by_voice():
    merged = merge_transcripts([FIRST, SECOND], [10.0, 5.0])
    turns = [(item["start"], item["speaker"], item["text"]) for item in merged["segments"]]
    assert turns == [
        (0.0, "SPEAKER_00", "앞 녹음 첫 발언"),
        (0.5, "SPEAKER_01", "앞 녹음 둘째 발언"),
        (10.0, "SPEAKER_02", "뒤 녹음 새 사람"),
        (10.5, "SPEAKER_01", "뒤 녹음 아는 사람"),
    ]
    assert merged["segments"][2]["words"][0] == {"word": "뒤 녹음 새 사람", "start": 10.0, "end": 10.4, "speaker": "SPEAKER_02"}
    assert merged["speaker_embeddings"] == {
        "SPEAKER_00": [1.0, 0.0, 0.0],
        "SPEAKER_01": [0.0, 1.0, 0.0],
        "SPEAKER_02": [0.0, 0.0, 1.0],
    }
    # 녹음을 또 더해도 앞에서 정한 라벨은 바뀌지 않는다.
    again = merge_transcripts([FIRST, SECOND, SECOND], [10.0, 5.0, 5.0])
    assert again["segments"][:4] == merged["segments"]
    assert [item["speaker"] for item in again["segments"][4:]] == ["SPEAKER_02", "SPEAKER_01"]


def test_added_recording_is_transcribed_alone_and_keeps_speaker_names(tmp_path, tone):
    site, transcribed = make_site(tmp_path)
    with site as client:
        job_id = wait_for(client, upload(client, tone), "done")["id"]
        client.put(f"/api/jobs/{job_id}/speakers/SPEAKER_01", json={"name": "김철수"})
        client.put(f"/api/jobs/{job_id}/notes", json={"notes": "# 회의록: 고친 회의록\n"})
        # 앞 녹음의 화자는 이름을 정한 회의라 다시 맞춰 보지 않고, 뒤 녹음에서 처음 나온 사람만 맞춰 본다.
        voices = VoiceBook(tmp_path)
        voices.register("홍길동", [1.0, 0.0, 0.0])
        voices.register("이영희", [0.0, 0.0, 1.0])

        response = add(client, job_id, tone)
        assert response.status_code == 200
        queued = response.json()
        assert queued["status"] in ("queued", "transcribing")
        assert queued["duration_seconds"] == pytest.approx(2.0, abs=0.2)
        # 남은 시간은 새 녹음 길이로 어림한다.
        assert queued["estimated_seconds"] < queued["duration_seconds"] * 2

        job = wait_for(client, job_id, "done")
        assert transcribed == ["audio.m4a", "2.m4a"]
        offset = probe_duration(tmp_path / job_id / "recordings" / "1.m4a")
        assert [(turn["speaker"], turn["start"]) for turn in job["turns"]] == [
            ("SPEAKER_00", 0.0),
            ("SPEAKER_01", 0.5),
            ("SPEAKER_02", pytest.approx(offset, abs=0.01)),
            ("SPEAKER_01", pytest.approx(offset + 0.5, abs=0.01)),
        ]
        names = {speaker["label"]: (speaker["name"], speaker["auto"]) for speaker in job["speakers"]}
        assert names["SPEAKER_01"] == ("김철수", False)
        assert names["SPEAKER_02"] == ("이영희", True)
        assert names["SPEAKER_00"][0] != "홍길동"
        assert not job["edited"]

        job_dir = tmp_path / job_id
        assert (job_dir / "notes.previous.md").read_text(encoding="utf-8") == "# 회의록: 고친 회의록\n"
        assert probe_duration(job_dir / "audio.m4a") == pytest.approx(2.0, abs=0.2)
        assert client.get(f"/api/jobs/{job_id}/audio").status_code == 200

        # 또 더 올리면 그 녹음만 전사한다.
        assert add(client, job_id, tone).status_code == 200
        assert wait_for(client, job_id, "done")["turns"][:4] == job["turns"]
        assert transcribed == ["audio.m4a", "2.m4a", "3.m4a"]


def test_adding_recording_is_refused_while_processing(tmp_path, tone):
    gate = threading.Event()
    site, _ = make_site(tmp_path, gate)
    with site as client:
        job_id = upload(client, tone)
        wait_for(client, job_id, "writing")
        refused = add(client, job_id, tone)
        assert refused.status_code == 409
        gate.set()
        wait_for(client, job_id, "done")
        assert not (tmp_path / job_id / "recordings").exists()
        assert [path for path in (tmp_path / job_id).iterdir() if path.suffix == ".tmp"] == []


def test_recordings_per_meeting_are_limited(tmp_path, tone):
    site, _ = make_site(tmp_path)
    with site as client:
        job_id = wait_for(client, upload(client, tone), "done")["id"]
        for _ in range(4):
            assert add(client, job_id, tone).status_code == 200
            wait_for(client, job_id, "done")
        refused = add(client, job_id, tone)
        assert refused.status_code == 400 and "5개까지" in refused.json()["detail"]


def test_bad_added_recording_leaves_meeting_untouched(tmp_path, tone):
    site, _ = make_site(tmp_path)
    with site as client:
        job_id = wait_for(client, upload(client, tone), "done")["id"]
        before = sorted(path.name for path in (tmp_path / job_id).iterdir())
        assert add(client, job_id, b"not audio").status_code == 400
        assert add(client, job_id, tone, name="뒤 녹음.txt").status_code == 400
        assert sorted(path.name for path in (tmp_path / job_id).iterdir()) == before
        assert client.get(f"/api/jobs/{job_id}").json()["status"] == "done"
