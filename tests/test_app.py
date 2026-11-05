import json
import subprocess
import time

import pytest
from fastapi.testclient import TestClient

from app import create_app, notes_title

NOTES = "# 회의록: 예시 회의\n\n## 요약\n- 내용이다. [00:01]\n"
TURNS = [{"start": 0.0, "end": 1.0, "speaker": "SPEAKER_00", "text": "예시 발언이다."}]


def fake_process(audio, out_dir, on_stage):
    on_stage("transcribing")
    assert audio.suffix == ".m4a"
    (out_dir / "audio.json").write_text("{}", encoding="utf-8")
    (out_dir / "turns.json").write_text(json.dumps(TURNS, ensure_ascii=False), encoding="utf-8")
    on_stage("writing")
    (out_dir / "notes.md").write_text(NOTES, encoding="utf-8")
    return {"input_tokens": 1, "output_tokens": 1}


@pytest.fixture(scope="session")
def tone(tmp_path_factory):
    path = tmp_path_factory.mktemp("audio") / "tone.m4a"
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=1", str(path)],
        check=True,
    )
    return path.read_bytes()


def make_client(tmp_path, process=fake_process):
    return TestClient(create_app(data_dir=tmp_path, process=process), base_url="http://127.0.0.1")


@pytest.fixture
def client(tmp_path):
    with make_client(tmp_path) as test_client:
        yield test_client


def wait_for(client, job_id, *statuses):
    deadline = time.time() + 5
    while time.time() < deadline:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in statuses:
            return job
        time.sleep(0.02)
    raise AssertionError(f"작업이 {statuses} 상태가 되지 않았다: {job}")


def upload(client, tone, name="회의 녹음.m4a"):
    response = client.post("/api/jobs", files={"file": (name, tone, "audio/mp4")})
    assert response.status_code == 201
    return response.json()["id"]


def test_rejects_unknown_host(client):
    assert client.get("/api/jobs", headers={"Host": "evil.example"}).status_code == 400


def test_accepts_tailscale_host(client):
    assert client.get("/api/jobs", headers={"Host": "laptop.example.ts.net"}).status_code == 200


def test_rejects_upload_from_another_site(client, tone, tmp_path):
    response = client.post(
        "/api/jobs",
        files={"file": ("a.m4a", tone, "audio/mp4")},
        headers={"Origin": "https://evil.example"},
    )
    assert response.status_code == 403
    assert list(tmp_path.iterdir()) == []


def test_rejects_edit_from_another_site(client, tone):
    job_id = wait_for(client, upload(client, tone), "done")["id"]
    response = client.put(
        f"/api/jobs/{job_id}/notes", json={"notes": "변조"}, headers={"Origin": "https://evil.example"}
    )
    assert response.status_code == 403
    assert client.get(f"/api/jobs/{job_id}").json()["notes"] == NOTES


def test_accepts_write_from_same_site(client, tone):
    response = client.post(
        "/api/jobs", files={"file": ("a.m4a", tone, "audio/mp4")}, headers={"Origin": "http://127.0.0.1"}
    )
    assert response.status_code == 201


def test_upload_creates_notes(client, tone):
    job_id = upload(client, tone)
    job = wait_for(client, job_id, "done")
    assert job["title"] == "예시 회의"
    assert job["notes"] == NOTES
    assert job["turns"] == TURNS
    assert job["confirmed_at"] is None
    assert job["duration_seconds"] == pytest.approx(1.0, abs=0.2)


def test_rejects_unsupported_suffix(client, tone, tmp_path):
    response = client.post("/api/jobs", files={"file": ("a.exe", tone, "audio/mp4")})
    assert response.status_code == 400
    assert list(tmp_path.iterdir()) == []


def test_rejects_file_that_is_not_audio(client, tmp_path):
    response = client.post("/api/jobs", files={"file": ("a.m4a", b"not audio", "audio/mp4")})
    assert response.status_code == 400
    assert list(tmp_path.iterdir()) == []


def test_upload_name_cannot_escape_job_folder(client, tone, tmp_path):
    job_id = upload(client, tone, name="../../evil.m4a")
    wait_for(client, job_id, "done")
    assert not (tmp_path.parent / "evil.m4a").exists()
    assert (tmp_path / job_id / "audio.m4a").exists()
    assert client.get(f"/api/jobs/{job_id}").json()["name"] == "evil.m4a"


@pytest.mark.parametrize("job_id", ["..", "nope", "0" * 32])
def test_unknown_job_is_not_found(client, job_id):
    assert client.get(f"/api/jobs/{job_id}").status_code == 404


def test_edit_keeps_draft_and_clears_confirmation(client, tone, tmp_path):
    job_id = wait_for(client, upload(client, tone), "done")["id"]
    assert client.post(f"/api/jobs/{job_id}/confirm").json()["confirmed_at"]

    updated = client.put(f"/api/jobs/{job_id}/notes", json={"notes": "# 회의록: 고친 제목\n\n본문이다.\n"}).json()
    assert updated["title"] == "고친 제목"
    assert updated["confirmed_at"] is None
    assert updated["edited"] is True

    client.put(f"/api/jobs/{job_id}/notes", json={"notes": "# 회의록: 또 고침\n"})
    assert (tmp_path / job_id / "notes.draft.md").read_text(encoding="utf-8") == NOTES


def test_download_returns_edited_notes(client, tone):
    job_id = wait_for(client, upload(client, tone), "done")["id"]
    client.put(f"/api/jobs/{job_id}/notes", json={"notes": '# 회의록: 경로/문자"제거\n'})
    response = client.get(f"/api/jobs/{job_id}/download")
    assert response.status_code == 200
    assert response.text == '# 회의록: 경로/문자"제거\n'
    assert "attachment" in response.headers["content-disposition"]
    assert "%EA%B2%BD%EB%A1%9C_%EB%AC%B8%EC%9E%90_" in response.headers["content-disposition"]


def test_audio_supports_range_requests(client, tone):
    job_id = wait_for(client, upload(client, tone), "done")["id"]
    response = client.get(f"/api/jobs/{job_id}/audio", headers={"Range": "bytes=0-9"})
    assert response.status_code == 206
    assert response.content == tone[:10]
    assert response.headers["content-type"] == "audio/mp4"


def test_failure_can_be_retried_without_exposing_details(tmp_path, tone):
    calls = []

    def flaky(audio, out_dir, on_stage):
        calls.append(audio)
        if len(calls) == 1:
            on_stage("writing")
            raise RuntimeError("비밀 내용이 든 예외")
        return fake_process(audio, out_dir, on_stage)

    with make_client(tmp_path, flaky) as test_client:
        job_id = upload(test_client, tone)
        failed = wait_for(test_client, job_id, "failed")
        assert "회의록을 쓰지 못했습니다" in failed["error"]
        assert "비밀" not in json.dumps(failed, ensure_ascii=False)
        assert test_client.post(f"/api/jobs/{job_id}/retry").status_code == 200
        assert wait_for(test_client, job_id, "done")["error"] is None


def test_retry_uses_audio_not_transcript_json(tmp_path, tone):
    seen = []

    def flaky(audio, out_dir, on_stage):
        seen.append(audio.name)
        (out_dir / "audio.json").write_text("{}", encoding="utf-8")
        if len(seen) == 1:
            raise RuntimeError("실패")
        return fake_process(audio, out_dir, on_stage)

    with make_client(tmp_path, flaky) as test_client:
        job_id = upload(test_client, tone)
        wait_for(test_client, job_id, "failed")
        test_client.post(f"/api/jobs/{job_id}/retry")
        wait_for(test_client, job_id, "done")
    assert seen == ["audio.m4a", "audio.m4a"]


def test_retry_is_refused_for_finished_job(client, tone):
    job_id = wait_for(client, upload(client, tone), "done")["id"]
    assert client.post(f"/api/jobs/{job_id}/retry").status_code == 409


def test_interrupted_job_restarts_when_server_starts(tmp_path, tone):
    with make_client(tmp_path) as first:
        job_id = upload(first, tone)
        wait_for(first, job_id, "done")
    meta = tmp_path / job_id / "meta.json"
    job = json.loads(meta.read_text(encoding="utf-8"))
    job.update(status="transcribing", stage_started_at=job["created_at"])
    meta.write_text(json.dumps(job, ensure_ascii=False), encoding="utf-8")

    with make_client(tmp_path) as second:
        assert wait_for(second, job_id, "done")["status"] == "done"


def test_security_headers_and_no_store(client):
    response = client.get("/api/jobs")
    assert response.headers["cache-control"] == "no-store"
    assert "default-src 'self'" in response.headers["content-security-policy"]
    assert response.headers["x-content-type-options"] == "nosniff"


def test_index_is_served(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "회의록" in response.text


@pytest.mark.parametrize(
    ("notes", "expected"),
    [
        ("# 회의록: 예산 회의\n", "예산 회의"),
        ("# 예산 회의\n", "예산 회의"),
        ("요약 없이 시작\n", "파일 이름"),
        ("", "파일 이름"),
    ],
)
def test_notes_title(notes, expected):
    assert notes_title(notes, "파일 이름") == expected
