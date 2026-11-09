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
