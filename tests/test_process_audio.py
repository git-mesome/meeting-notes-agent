import json
import os
import subprocess
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

    def fake_transcribe(audio, out_dir, glossary, _on_process):
        calls.transcribe += 1
        calls.glossary = glossary
        (out_dir / f"{audio.stem}.json").write_text(json.dumps(SEGMENTS, ensure_ascii=False), encoding="utf-8")

    def fake_write_notes(transcript, _glossary, _template):
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


def test_failed_transcription_reports_process_and_removes_partial_result(tmp_path, monkeypatch):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake = bin_dir / "whisperx"
    fake.write_text("#!/bin/sh\necho '{' > \"$(dirname \"$1\")/audio.json\"\nexit 3\n", encoding="utf-8")
    fake.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ['PATH']}")
    processes = []

    with pytest.raises(subprocess.CalledProcessError):
        meeting_notes.transcribe(tmp_path / "audio.m4a", tmp_path, [], processes.append)

    assert processes[0].returncode == 3
    assert not (tmp_path / "audio.json").exists()


def write_knowledge(root):
    (root / "meeting_context.md").write_text("# 배경\n- 홍길순 부장: 영업\n", encoding="utf-8")
    terms = [
        {"term": "방화벽", "term_en": "firewall", "aliases": ["FW"], "definition": "가" * 500, "tags": []},
        {"term": "토폴로지", "term_en": None, "aliases": [], "definition": "연결 구조다.", "tags": []},
        {"term": "동기화", "term_en": "sync", "aliases": [], "definition": "장비 값을 모은다.", "tags": []},
    ]
    (root / "terms.json").write_text(json.dumps(terms, ensure_ascii=False), encoding="utf-8")


def test_knowledge_lists_all_terms_and_defines_only_spoken_ones(tmp_path):
    write_knowledge(tmp_path)
    text = meeting_notes.load_knowledge("[00:01] SPEAKER_00: 방 화벽 정책과 SYNC 결과를 봅시다.", tmp_path)
    assert "홍길순 부장" in text
    assert "방화벽(firewall, FW)" in text and "토폴로지" in text
    defined = text.split("이 회의에 나온 용어의 뜻")[1]
    assert "- 방화벽: " in defined and "- 동기화: 장비 값을 모은다." in defined
    assert "토폴로지" not in defined
    assert "가" * (meeting_notes.MAX_DEFINITION_CHARS + 1) not in defined


def test_knowledge_is_empty_without_files(tmp_path):
    assert meeting_notes.load_knowledge("전사문", tmp_path) == ""


def test_write_notes_sends_knowledge_before_transcript(tmp_path, monkeypatch):
    write_knowledge(tmp_path)
    monkeypatch.setattr(meeting_notes, "KNOWLEDGE_DIR", tmp_path)
    captured = {}

    class Stream:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def get_final_message(self):
            return SimpleNamespace(
                stop_reason="end_turn", content=[SimpleNamespace(type="text", text="회의록")], usage=None
            )

    class Client:
        beta = SimpleNamespace(messages=SimpleNamespace(stream=lambda **kwargs: captured.update(kwargs) or Stream()))

    monkeypatch.setattr(meeting_notes.anthropic, "Anthropic", Client)
    meeting_notes.write_notes("전사문 내용", ["용어"])
    user = captured["messages"][0]["content"]
    assert user.index("<company_knowledge>") < user.index("<glossary>") < user.index("<transcript>")
    assert "표기를 바로잡고" in captured["system"]


def test_load_glossary_ignores_blank_lines(tmp_path):
    path = tmp_path / "glossary.txt"
    path.write_text("방화벽\n\n  지점망  \n", encoding="utf-8")
    assert meeting_notes.load_glossary(path) == ["방화벽", "지점망"]
