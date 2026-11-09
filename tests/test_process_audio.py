import json
import os
import subprocess
from types import SimpleNamespace

import pytest

from meeting_notes import llm, settings
from meeting_notes.pipeline import knowledge, notes, process, transcribe

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

    def fake_write_notes(transcript, _glossary, _template, _facts=()):
        calls.transcript = transcript
        return "# 회의록: 예시", SimpleNamespace(input_tokens=11, output_tokens=22)

    monkeypatch.setattr(process, "transcribe", fake_transcribe)
    monkeypatch.setattr(process, "write_notes", fake_write_notes)
    return calls


def test_saves_results_and_reports_stages(tmp_path, pipeline):
    stages = []
    usage = process.process_audio(tmp_path / "audio.m4a", tmp_path, ["용어"], stages.append)

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
    process.process_audio(tmp_path / "audio.m4a", tmp_path, [], stages.append)
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
        transcribe.transcribe(tmp_path / "audio.m4a", tmp_path, [], processes.append)

    assert processes[0].returncode == 3
    assert not (tmp_path / "audio.json").exists()


def fake_whisperx(tmp_path, monkeypatch, exit_code=0):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake = bin_dir / "whisperx"
    fake.write_text(
        '#!/bin/sh\n'
        'echo "$@" > "$(dirname "$1")/args.txt"\n'
        'name=$(basename "$1"); name="${name%.*}"\n'
        'echo "{}" > "$(dirname "$1")/$name.json"\n'
        f"exit {exit_code}\n",
        encoding="utf-8",
    )
    fake.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ['PATH']}")


def test_transcribe_uses_normalized_audio_and_cleans_up(tmp_path, monkeypatch):
    fake_whisperx(tmp_path, monkeypatch)
    audio = tmp_path / "audio.m4a"
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=1", str(audio)],
        check=True,
    )
    transcribe.transcribe(audio, tmp_path, [])
    args = (tmp_path / "args.txt").read_text(encoding="utf-8")
    assert "audio.normalized.wav" in args and "--vad_onset 0.2" in args and "--speaker_embeddings" in args
    assert (tmp_path / "audio.json").exists()
    assert not (tmp_path / "audio.normalized.wav").exists()
    assert not (tmp_path / "audio.normalized.json").exists()
    assert audio.exists()


def test_transcribe_thread_count_follows_environment(tmp_path, monkeypatch):
    fake_whisperx(tmp_path, monkeypatch)
    audio = tmp_path / "audio.m4a"
    audio.write_bytes(b"not audio")
    monkeypatch.delenv("WHISPER_THREADS", raising=False)
    transcribe.transcribe(audio, tmp_path, [])
    assert "--threads 8" in (tmp_path / "args.txt").read_text(encoding="utf-8")
    monkeypatch.setenv("WHISPER_THREADS", "16")
    transcribe.transcribe(audio, tmp_path, [])
    assert "--threads 16" in (tmp_path / "args.txt").read_text(encoding="utf-8")


def test_transcribe_falls_back_to_original_when_normalizing_fails(tmp_path, monkeypatch):
    fake_whisperx(tmp_path, monkeypatch)
    audio = tmp_path / "audio.m4a"
    audio.write_bytes(b"not audio")
    transcribe.transcribe(audio, tmp_path, [])
    assert str(audio) in (tmp_path / "args.txt").read_text(encoding="utf-8")
    assert (tmp_path / "audio.json").exists()


def test_failed_transcription_removes_temporary_files(tmp_path, monkeypatch):
    fake_whisperx(tmp_path, monkeypatch, exit_code=4)
    audio = tmp_path / "audio.m4a"
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=1", str(audio)],
        check=True,
    )
    with pytest.raises(subprocess.CalledProcessError):
        transcribe.transcribe(audio, tmp_path, [])
    leftovers = [p.name for p in tmp_path.iterdir() if p.name.startswith("audio.") and p.name != "audio.m4a"]
    assert leftovers == []


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
    text = knowledge.load_knowledge("[00:01] SPEAKER_00: 방 화벽 정책과 SYNC 결과를 봅시다.", tmp_path)
    assert "홍길순 부장" in text
    assert "방화벽(firewall, FW)" in text and "토폴로지" in text
    defined = text.split("이 회의에 나온 용어의 뜻")[1]
    assert "- 방화벽: " in defined and "- 동기화: 장비 값을 모은다." in defined
    assert "토폴로지" not in defined
    assert "가" * (knowledge.MAX_DEFINITION_CHARS + 1) not in defined


def test_knowledge_is_empty_without_files(tmp_path):
    assert knowledge.load_knowledge("전사문", tmp_path) == ""


def test_write_notes_sends_knowledge_before_transcript(tmp_path, monkeypatch):
    (tmp_path / "knowledge").mkdir()
    write_knowledge(tmp_path / "knowledge")
    monkeypatch.setattr(settings, "current", lambda: settings.Company(tmp_path))
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

    monkeypatch.setattr(llm.anthropic, "Anthropic", Client)
    notes.write_notes("전사문 내용", ["용어"])
    user = captured["messages"][0]["content"]
    assert user.index("<company_knowledge>") < user.index("<glossary>") < user.index("<transcript>")
    assert "표기를 바로잡고" in captured["system"]
    assert f"{notes.MIN_NOTES_CHARS}자 이내" in captured["system"]


def test_load_glossary_ignores_blank_lines(tmp_path):
    path = tmp_path / "glossary.txt"
    path.write_text("방화벽\n\n  지점망  \n", encoding="utf-8")
    assert knowledge.load_glossary(path) == ["방화벽", "지점망"]
