import json
import re
import subprocess
import threading
import time
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient

from meeting_notes.main import create_app
from meeting_notes.pipeline.notes import notes_title
from meeting_notes.web.routers import jobs as jobs_router

NOTES = "# 회의록: 예시 회의\n\n## 요약\n- 내용이다. [00:01]\n"
TURNS = [{"start": 0.0, "end": 1.0, "speaker": "SPEAKER_00", "text": "예시 발언이다."}]


def fake_process(audio, out_dir, on_stage, _on_process=None):
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
    deadline = time.time() + 20
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


def test_accepts_raw_body_from_shortcut(client, tone, tmp_path):
    response = client.post("/api/jobs", content=tone, headers={"Content-Type": "audio/x-m4a"})
    assert response.status_code == 201
    job_id = response.json()["id"]
    assert response.json()["name"] == "아이폰 녹음.m4a"
    assert wait_for(client, job_id, "done")["title"] == "예시 회의"
    assert (tmp_path / job_id / "audio.m4a").read_bytes() == tone
    assert not (tmp_path / job_id / "upload.tmp").exists()


def test_raw_body_without_content_type_is_accepted(client, tone):
    assert client.post("/api/jobs", content=tone, headers={"Content-Type": ""}).status_code == 201


def test_accepts_form_with_other_field_name(client, tone):
    response = client.post("/api/jobs", files={"단축어 입력": ("메모.m4a", tone, "audio/mp4")})
    assert response.status_code == 201
    assert response.json()["name"] == "메모.m4a"


def test_rejects_form_without_file(client, tmp_path):
    response = client.post("/api/jobs", files={"file": (None, "글자")})
    assert response.status_code == 400
    assert "파일이 들어 있지 않아요" in response.json()["detail"]
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("body", [b"", b"not audio"])
def test_rejects_raw_body_that_is_not_audio(client, tmp_path, body):
    response = client.post("/api/jobs", content=body, headers={"Content-Type": "audio/x-m4a"})
    assert response.status_code == 400
    assert list(tmp_path.iterdir()) == []


def test_rejects_raw_body_over_limit(client, tone, tmp_path, monkeypatch):
    monkeypatch.setattr(jobs_router, "MAX_UPLOAD_BYTES", 5)
    response = client.post("/api/jobs", content=tone, headers={"Content-Type": "audio/x-m4a"})
    assert response.status_code == 413
    assert list(tmp_path.iterdir()) == []


def test_rejects_form_upload_over_limit(client, tone, tmp_path, monkeypatch):
    monkeypatch.setattr(jobs_router, "MAX_UPLOAD_BYTES", 5)
    response = client.post("/api/jobs", files={"file": ("a.m4a", tone, "audio/mp4")})
    assert response.status_code == 413
    assert list(tmp_path.iterdir()) == []


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


def test_edited_notes_keep_ai_spelling(client, tone):
    job_id = wait_for(client, upload(client, tone), "done")["id"]
    updated = client.put(f"/api/jobs/{job_id}/notes", json={"notes": "# 회의록: 에이아이 도입\n"}).json()
    assert updated["title"] == "AI 도입" and "에이아이" not in updated["notes"]


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

    def flaky(audio, out_dir, on_stage, on_process):
        calls.append(audio)
        if len(calls) == 1:
            on_stage("writing")
            raise RuntimeError("비밀 내용이 든 예외")
        return fake_process(audio, out_dir, on_stage, on_process)

    with make_client(tmp_path, flaky) as test_client:
        job_id = upload(test_client, tone)
        failed = wait_for(test_client, job_id, "failed")
        assert "회의록을 쓰지 못했어요" in failed["error"]
        assert "비밀" not in json.dumps(failed, ensure_ascii=False)
        assert test_client.post(f"/api/jobs/{job_id}/retry").status_code == 200
        assert wait_for(test_client, job_id, "done")["error"] is None


def test_retry_uses_audio_not_transcript_json(tmp_path, tone):
    seen = []

    def flaky(audio, out_dir, on_stage, on_process):
        seen.append(audio.name)
        (out_dir / "audio.json").write_text("{}", encoding="utf-8")
        if len(seen) == 1:
            raise RuntimeError("실패")
        return fake_process(audio, out_dir, on_stage, on_process)

    with make_client(tmp_path, flaky) as test_client:
        job_id = upload(test_client, tone)
        wait_for(test_client, job_id, "failed")
        test_client.post(f"/api/jobs/{job_id}/retry")
        wait_for(test_client, job_id, "done")
    assert seen == ["audio.m4a", "audio.m4a"]


def long_running_process(started, processes):
    def process(audio, out_dir, on_stage, on_process):
        on_stage("transcribing")
        running = subprocess.Popen(["sleep", "30"])
        processes.append(running)
        on_process(running)
        started.set()
        if running.wait() != 0:
            raise subprocess.CalledProcessError(running.returncode, "sleep")
        return fake_process(audio, out_dir, on_stage)

    return process


def test_cancel_stops_running_process_and_can_restart(tmp_path, tone):
    started, processes = threading.Event(), []
    with make_client(tmp_path, long_running_process(started, processes)) as test_client:
        job_id = upload(test_client, tone)
        assert started.wait(5)

        response = test_client.post(f"/api/jobs/{job_id}/cancel")
        assert response.status_code == 200
        assert response.json()["status"] == "canceled"
        assert processes[0].wait(5) != 0
        started.clear()
        deadline = time.time() + 5
        while test_client.post(f"/api/jobs/{job_id}/retry").status_code == 409 and time.time() < deadline:
            time.sleep(0.02)

        job = wait_for(test_client, job_id, "transcribing")
        assert job["error"] is None
        assert started.wait(5)
        test_client.post(f"/api/jobs/{job_id}/cancel")
        assert processes[1].wait(5) != 0
        assert not (tmp_path / job_id / "notes.md").exists()


def test_cancel_keeps_status_after_process_fails(tmp_path, tone):
    started, processes = threading.Event(), []
    with make_client(tmp_path, long_running_process(started, processes)) as test_client:
        job_id = upload(test_client, tone)
        assert started.wait(5)
        test_client.post(f"/api/jobs/{job_id}/cancel")
        processes[0].wait(5)
        time.sleep(0.1)
        job = test_client.get(f"/api/jobs/{job_id}").json()
        assert job["status"] == "canceled"
        assert job["error"] is None


def test_cancel_queued_job_is_never_processed(tmp_path, tone):
    started, processes = threading.Event(), []
    with make_client(tmp_path, long_running_process(started, processes)) as test_client:
        first = upload(test_client, tone)
        assert started.wait(5)
        second = upload(test_client, tone)
        assert test_client.get(f"/api/jobs/{second}").json()["ahead"] == 1
        assert test_client.post(f"/api/jobs/{second}/cancel").json()["status"] == "canceled"
        test_client.post(f"/api/jobs/{first}/cancel")
        processes[0].wait(5)
        time.sleep(0.1)
        assert len(processes) == 1
        assert test_client.get(f"/api/jobs/{second}").json()["status"] == "canceled"


def test_cancel_finished_job_is_refused(client, tone):
    job_id = wait_for(client, upload(client, tone), "done")["id"]
    assert client.post(f"/api/jobs/{job_id}/cancel").status_code == 409


def test_cancel_during_writing_discards_result(tmp_path, tone):
    release, writing = threading.Event(), threading.Event()

    def process(audio, out_dir, on_stage, on_process):
        fake_process(audio, out_dir, on_stage, on_process)
        writing.set()
        assert release.wait(5)
        return {"input_tokens": 1, "output_tokens": 1}

    with make_client(tmp_path, process) as test_client:
        job_id = upload(test_client, tone)
        assert writing.wait(5)
        test_client.post(f"/api/jobs/{job_id}/cancel")
        assert test_client.delete(f"/api/jobs/{job_id}").status_code == 409
        release.set()
        time.sleep(0.2)
        assert test_client.get(f"/api/jobs/{job_id}").json()["status"] == "canceled"
        assert test_client.delete(f"/api/jobs/{job_id}").status_code == 200


def test_delete_removes_everything(client, tone, tmp_path):
    job_id = wait_for(client, upload(client, tone), "done")["id"]
    assert client.delete(f"/api/jobs/{job_id}").status_code == 200
    assert not (tmp_path / job_id).exists()
    assert client.get(f"/api/jobs/{job_id}").status_code == 404
    assert client.get("/api/jobs").json() == []


def test_delete_refused_while_processing(tmp_path, tone):
    started, processes = threading.Event(), []
    with make_client(tmp_path, long_running_process(started, processes)) as test_client:
        job_id = upload(test_client, tone)
        assert started.wait(5)
        response = test_client.delete(f"/api/jobs/{job_id}")
        assert response.status_code == 409
        assert "먼저 멈춰" in response.json()["detail"]
        assert (tmp_path / job_id).exists()
        test_client.post(f"/api/jobs/{job_id}/cancel")
        processes[0].wait(5)


def test_delete_from_another_site_is_refused(client, tone, tmp_path):
    job_id = wait_for(client, upload(client, tone), "done")["id"]
    response = client.delete(f"/api/jobs/{job_id}", headers={"Origin": "https://evil.example"})
    assert response.status_code == 403
    assert (tmp_path / job_id).exists()


@pytest.mark.parametrize("job_id", ["..", "nope", "0" * 32])
def test_delete_unknown_job_is_not_found(client, job_id, tmp_path):
    assert client.delete(f"/api/jobs/{job_id}").status_code in (404, 405)
    assert tmp_path.exists()


SPEAKER_TURNS = [
    {"start": 0.0, "end": 2.0, "speaker": "SPEAKER_00", "text": "짧은 발언이다."},
    {"start": 2.0, "end": 12.0, "speaker": "SPEAKER_01", "text": "긴 발언이다."},
    {"start": 12.0, "end": 12.5, "speaker": "UNKNOWN", "text": "알 수 없는 발언이다."},
]


@pytest.fixture
def speaker_job(client, tone, tmp_path):
    job_id = wait_for(client, upload(client, tone), "done")["id"]
    (tmp_path / job_id / "turns.json").write_text(json.dumps(SPEAKER_TURNS, ensure_ascii=False), encoding="utf-8")
    client.put(f"/api/jobs/{job_id}/notes", json={"notes": "# 회의록: SPEAKER_01의 보고\n\n- 담당: SPEAKER_00\n"})
    return job_id


def test_speakers_are_numbered_by_speaking_time(client, speaker_job):
    speakers = client.get(f"/api/jobs/{speaker_job}").json()["speakers"]
    assert [(s["label"], s["name"], s["custom"], s["known"]) for s in speakers] == [
        ("SPEAKER_01", "화자 1", False, True),
        ("SPEAKER_00", "화자 2", False, True),
        ("UNKNOWN", "알 수 없음", False, False),
    ]
    assert speakers[0]["share"] == 80


def test_rename_speaker_keeps_notes_file_and_clears_confirmation(client, speaker_job, tmp_path):
    client.post(f"/api/jobs/{speaker_job}/confirm")
    job = client.put(f"/api/jobs/{speaker_job}/speakers/SPEAKER_01", json={"name": "  김  길동 "}).json()
    assert job["speakers"][0]["name"] == "김 길동"
    assert job["speakers"][0]["custom"] is True
    assert job["speakers"][0]["default_name"] == "화자 1"
    assert job["confirmed_at"] is None
    assert "SPEAKER_00" in (tmp_path / speaker_job / "notes.md").read_text(encoding="utf-8")


def test_empty_name_restores_default(client, speaker_job):
    client.put(f"/api/jobs/{speaker_job}/speakers/SPEAKER_01", json={"name": "길동"})
    job = client.put(f"/api/jobs/{speaker_job}/speakers/SPEAKER_01", json={"name": "   "}).json()
    assert job["speakers"][0]["name"] == "화자 1"
    assert job["speakers"][0]["custom"] is False


def test_download_uses_speaker_names(client, speaker_job):
    client.put(f"/api/jobs/{speaker_job}/speakers/SPEAKER_01", json={"name": "길동"})
    response = client.get(f"/api/jobs/{speaker_job}/download")
    assert response.text == "# 회의록: 길동의 보고\n\n- 담당: 화자 2\n"
    assert response.headers["content-type"].startswith("text/markdown")
    assert quote("길동") in response.headers["content-disposition"]


@pytest.mark.parametrize("label", ["UNKNOWN", "SPEAKER_99", "nope"])
def test_rename_unknown_speaker_is_not_found(client, speaker_job, label):
    assert client.put(f"/api/jobs/{speaker_job}/speakers/{label}", json={"name": "길동"}).status_code == 404


@pytest.mark.parametrize("name", ["a|b", "**굵게**", "[00:10]"])
def test_rename_rejects_markdown_characters(client, speaker_job, name):
    response = client.put(f"/api/jobs/{speaker_job}/speakers/SPEAKER_01", json={"name": name})
    assert response.status_code == 400
    assert client.get(f"/api/jobs/{speaker_job}").json()["speakers"][0]["custom"] is False


def test_rename_rejects_long_name(client, speaker_job):
    assert client.put(f"/api/jobs/{speaker_job}/speakers/SPEAKER_01", json={"name": "가" * 21}).status_code == 422


def test_rename_from_another_site_is_refused(client, speaker_job):
    response = client.put(
        f"/api/jobs/{speaker_job}/speakers/SPEAKER_01", json={"name": "변조"}, headers={"Origin": "https://evil.example"}
    )
    assert response.status_code == 403


def test_rename_before_done_is_refused(tmp_path, tone):
    started, processes = threading.Event(), []
    with make_client(tmp_path, long_running_process(started, processes)) as test_client:
        job_id = upload(test_client, tone)
        assert started.wait(5)
        response = test_client.put(f"/api/jobs/{job_id}/speakers/SPEAKER_00", json={"name": "길동"})
        assert response.status_code == 409
        test_client.post(f"/api/jobs/{job_id}/cancel")
        processes[0].wait(5)


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


def test_index_points_to_current_app_files(client):
    html = client.get("/").text
    assert 'type="module"' in html
    for name in ("js/main.js", "css/base.css", "css/responsive.css"):
        match = re.search(rf'"(/static/{name}\?v=[0-9a-f]{{12}})"', html)
        assert match and client.get(match.group(1)).status_code == 200


def test_static_files_are_revalidated(client):
    assert client.get("/static/js/main.js").headers["cache-control"] == "no-cache"
    assert client.get("/sw.js").headers["cache-control"] == "no-cache"


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
