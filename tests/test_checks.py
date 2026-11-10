import json
import subprocess
import time

import pytest
from fastapi.testclient import TestClient

from meeting_notes.main import create_app

NOTES = """# 회의록: 점검

## 요약
- 요약

## 확인 필요
- 모델명 불분명 [00:48]
- [x] 기한 확인 필요
* 담당자 확인
"""


def fake_process(audio, out_dir, on_stage, on_process):
    on_stage("transcribing")
    (out_dir / "turns.json").write_text(json.dumps([{"start": 0.0, "end": 1.0, "speaker": "SPEAKER_00", "text": "네"}]), encoding="utf-8")
    on_stage("writing")
    (out_dir / "notes.md").write_text(NOTES, encoding="utf-8")
    return {"input_tokens": 1, "output_tokens": 1}


@pytest.fixture
def done_job(tmp_path):
    tone = tmp_path / "tone.m4a"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=1", str(tone)], check=True)
    with TestClient(create_app(data_dir=tmp_path / "jobs", process=fake_process, tracker=None, auth=None), base_url="http://127.0.0.1") as client:
        job_id = client.post("/api/jobs", files={"file": ("a.m4a", tone.read_bytes(), "audio/mp4")}).json()["id"]
        deadline = time.time() + 20
        while client.get(f"/api/jobs/{job_id}").json()["status"] != "done":
            assert time.time() < deadline
            time.sleep(0.02)
        yield client, job_id


def test_check_marks_are_saved_without_unconfirming(done_job):
    client, job_id = done_job
    client.post(f"/api/jobs/{job_id}/confirm")
    notes = client.put(f"/api/jobs/{job_id}/checks/0", json={"done": True}).json()["notes"]
    assert "- [x] 모델명 불분명 [00:48]" in notes
    notes = client.put(f"/api/jobs/{job_id}/checks/1", json={"done": False}).json()["notes"]
    assert "- 기한 확인 필요" in notes and "[x] 기한" not in notes
    detail = client.put(f"/api/jobs/{job_id}/checks/2", json={"done": True}).json()
    assert "- [x] 담당자 확인" in detail["notes"]
    # 내용을 고친 것이 아니므로 확정과 원본 보관 상태는 그대로다
    assert detail["confirmed_at"] and detail["edited"] is False
    assert client.put(f"/api/jobs/{job_id}/checks/3", json={"done": True}).status_code == 404


def test_confirmed_note_is_kept_and_remembered(done_job):
    client, job_id = done_job
    body = {"done": True, "note": "홍길동 부장님이 맞음", "remember": True}
    notes = client.put(f"/api/jobs/{job_id}/checks/0", json=body).json()["notes"]
    assert "- [x] 모델명 불분명 [00:48] — 확인: 홍길동 부장님이 맞음" in notes
    memory = client.get("/api/memory").json()
    assert [(item["question"], item["answer"]) for item in memory] == [("모델명 불분명", "홍길동 부장님이 맞음")]
    # 다시 확인하면 답을 바꾸고, 체크를 풀면 회의록의 확인 내용은 지운다(기억은 남는다)
    client.put(f"/api/jobs/{job_id}/checks/0", json={**body, "note": "홍길동 부장님"})
    assert [item["answer"] for item in client.get("/api/memory").json()] == ["홍길동 부장님"]
    notes = client.put(f"/api/jobs/{job_id}/checks/0", json={"done": False}).json()["notes"]
    assert "- 모델명 불분명 [00:48]\n" in notes and "확인:" not in notes
    item_id = client.get("/api/memory").json()[0]["id"]
    assert client.delete(f"/api/memory/{item_id}").status_code == 200
    assert client.get("/api/memory").json() == []
    assert client.delete(f"/api/memory/{item_id}").status_code == 404


def test_note_without_remember_is_not_stored(done_job):
    client, job_id = done_job
    client.put(f"/api/jobs/{job_id}/checks/0", json={"done": True, "note": "확인함", "remember": False})
    assert client.get("/api/memory").json() == []


def test_answers_and_next_notes_get_remembered_facts(tmp_path, monkeypatch):
    from meeting_notes import main
    from meeting_notes.memory import MemoryBook
    from meeting_notes.pipeline import knowledge, process

    MemoryBook(tmp_path).add('"홍길똥 부장님"의 실제 이름', "홍길동 부장님이 맞음", "job")
    job_dir = tmp_path / "abc"
    job_dir.mkdir()
    (job_dir / "meta.json").write_text('{"template": "general"}', encoding="utf-8")
    seen = {}
    monkeypatch.setattr(process, "process_audio", lambda *args, **kwargs: seen.update(facts=args[-1]) or {})
    main.default_process(job_dir / "audio.m4a", job_dir, lambda stage: None, lambda proc: None)
    assert seen["facts"] == ['"홍길똥 부장님"의 실제 이름 → 홍길동 부장님이 맞음']
    text = knowledge.load_knowledge("전사문", tmp_path / "없음", facts=seen["facts"])
    assert "## 사용자가 지난 회의에서 확인한 사실" in text and "→ 홍길동 부장님이 맞음" in text


def test_questions_get_remembered_facts(tmp_path):
    seen = {}

    def answer(transcript, notes, question, facts=()):
        seen["facts"] = facts
        return "답"

    tone = tmp_path / "tone.m4a"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=1", str(tone)], check=True)
    app = create_app(data_dir=tmp_path / "jobs", process=fake_process, answer=answer, tracker=None, auth=None)
    with TestClient(app, base_url="http://127.0.0.1") as client:
        job_id = client.post("/api/jobs", files={"file": ("a.m4a", tone.read_bytes(), "audio/mp4")}).json()["id"]
        deadline = time.time() + 20
        while client.get(f"/api/jobs/{job_id}").json()["status"] != "done":
            assert time.time() < deadline
            time.sleep(0.02)
        client.put(f"/api/jobs/{job_id}/checks/1", json={"done": True, "note": "9월 12일", "remember": True})
        client.post(f"/api/jobs/{job_id}/ask", json={"question": "기한은?"})
    assert seen["facts"] == ["기한 확인 필요 → 9월 12일"]
