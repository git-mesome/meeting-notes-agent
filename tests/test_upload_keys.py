"""아이폰 단축어용 업로드 키(auth/upload_keys.py). 키로는 녹음 올리기만 할 수 있다."""

import json

import pytest
from fastapi.testclient import TestClient

from meeting_notes.auth import OIDC, SESSION_COOKIE, UserBook
from meeting_notes.main import create_app
from meeting_notes.web.middleware import UPLOAD_KEY_NEEDED
from tests.test_app import fake_process, tone, wait_for  # noqa: F401

SETTINGS = {"issuer": "http://sso.example/oidc", "client_id": "meeting-notes", "base_url": "http://meet.example:8000"}
OWNER = {"sub": "u1", "name": "홍길동"}
OTHER = {"sub": "u2", "name": "김철수"}


@pytest.fixture
def site(tmp_path):
    oidc = OIDC(SETTINGS, tmp_path)
    users = UserBook(tmp_path)
    for person in (OWNER, OTHER):
        users.seen(person)
    app = create_app(data_dir=tmp_path, process=fake_process, tracker=None, auth=oidc)
    with TestClient(app, base_url="http://127.0.0.1") as client:

        def act_as(user=None):
            """user가 없으면 로그인하지 않은 단축어처럼 쿠키 없이 보낸다."""
            client.cookies.clear()
            if user:
                client.cookies.set(SESSION_COOKIE, oidc.session(user))
            return client

        yield act_as


def from_shortcut(client, tone, key=None):
    headers = {"Content-Type": "audio/x-m4a"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    return client.post("/api/jobs", content=tone, headers=headers)


def test_shortcut_uploads_with_key_as_its_owner(site, tone, tmp_path):
    refused = from_shortcut(site(), tone)
    assert refused.status_code == 401 and refused.json()["detail"] == UPLOAD_KEY_NEEDED

    owner = site(OWNER)
    assert owner.get("/api/upload-key").json() == {"created_at": None}
    issued = owner.post("/api/upload-key").json()
    assert issued["key"].startswith("mn_")
    assert owner.get("/api/upload-key").json() == {"created_at": issued["created_at"]}
    # 키 원문은 저장하지 않는다.
    assert issued["key"] not in (tmp_path / "upload-keys.json").read_text(encoding="utf-8")

    response = from_shortcut(site(), tone, issued["key"])
    assert response.status_code == 201
    job_id = response.json()["id"]
    meta = json.loads((tmp_path / job_id / "meta.json").read_text(encoding="utf-8"))
    assert meta["owner"] == OWNER
    assert wait_for(site(OWNER), job_id, "done")["access"]["manage"] is True


def test_key_only_uploads(site, tone):
    key = site(OWNER).post("/api/upload-key").json()["key"]
    shortcut = site()
    headers = {"Authorization": f"Bearer {key}"}
    assert shortcut.get("/api/jobs", headers=headers).status_code == 401
    assert shortcut.post("/api/upload-key", headers=headers).status_code == 401
    assert shortcut.get("/api/me", headers=headers).status_code == 401
    assert from_shortcut(shortcut, tone, "mn_fake").status_code == 401


def test_new_key_replaces_old_and_revoke_removes_it(site, tone):
    first = site(OWNER).post("/api/upload-key").json()["key"]
    second = site(OWNER).post("/api/upload-key").json()["key"]
    other = site(OTHER).post("/api/upload-key").json()["key"]
    assert from_shortcut(site(), tone, first).status_code == 401
    assert from_shortcut(site(), tone, second).status_code == 201

    assert site(OWNER).delete("/api/upload-key").status_code == 200
    assert site(OWNER).get("/api/upload-key").json() == {"created_at": None}
    assert from_shortcut(site(), tone, second).status_code == 401
    # 다른 사람의 키는 그대로 쓸 수 있다.
    assert from_shortcut(site(), tone, other).status_code == 201


def test_without_login_shortcut_needs_no_key(tmp_path, tone):
    app = create_app(data_dir=tmp_path, process=fake_process, tracker=None, auth=None)
    with TestClient(app, base_url="http://127.0.0.1") as client:
        assert from_shortcut(client, tone).status_code == 201
        assert client.get("/api/upload-key").json() == {"created_at": None}
        assert client.post("/api/upload-key").status_code == 400
