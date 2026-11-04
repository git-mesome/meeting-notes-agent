import json
from types import SimpleNamespace

import pytest

import meeting_notes

SEGMENTS = {
    "segments": [
        {
            "start": 0.0,
            "end": 2.0,
            "text": "예시 발언",
            "speaker": "SPEAKER_00",
            "words": [
                {"word": "예시", "start": 0.0, "end": 1.0, "speaker": "SPEAKER_00"},
                {"word": "발언", "start": 1.0, "end": 2.0, "speaker": "SPEAKER_00"},
            ],
        }
    ]
}


@pytest.fixture
def pipeline(monkeypatch):
    calls = SimpleNamespace(transcribe=0, transcript=None, glossary=None)

    def fake_transcribe(audio, out_dir, glossary):
        calls.transcribe += 1
        calls.glossary = glossary
        (out_dir / f"{audio.stem}.json").write_text(json.dumps(SEGMENTS, ensure_ascii=False), encoding="utf-8")

    def fake_write_notes(transcript, _glossary):
        calls.transcript = transcript
        return "# 회의록: 예시", SimpleNamespace(input_tokens=11, output_tokens=22)

    monkeypatch.setattr(meeting_notes, "transcribe", fake_transcribe)
    monkeypatch.setattr(meeting_notes, "write_notes", fake_write_notes)
    return calls


def test_saves_results_and_reports_stages(tmp_path, pipeline):
    stages = []
    usage = meeting_notes.process_audio(tmp_path / "audio.m4a", tmp_path, ["용어"], stages.append)

    assert stages == ["transcribing", "writing"]
    assert pipeline.glossary == ["용어"]
    assert pipeline.transcript == "[00:00] SPEAKER_00: 예시 발언"
    assert (tmp_path / "notes.md").read_text(encoding="utf-8") == "# 회의록: 예시\n"
    assert json.loads((tmp_path / "turns.json").read_text(encoding="utf-8")) == [
        {"start": 0.0, "end": 2.0, "speaker": "SPEAKER_00", "text": "예시 발언"}
    ]
    assert json.loads(json.dumps(usage)) == {"input_tokens": 11, "output_tokens": 22}


def test_skips_transcription_when_result_exists(tmp_path, pipeline):
    (tmp_path / "audio.json").write_text(json.dumps(SEGMENTS, ensure_ascii=False), encoding="utf-8")
    stages = []
    meeting_notes.process_audio(tmp_path / "audio.m4a", tmp_path, [], stages.append)
    assert pipeline.transcribe == 0
    assert stages == ["writing"]


def test_load_glossary_ignores_blank_lines(tmp_path):
    path = tmp_path / "glossary.txt"
    path.write_text("방화벽\n\n  지점망  \n", encoding="utf-8")
    assert meeting_notes.load_glossary(path) == ["방화벽", "지점망"]
