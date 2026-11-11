"""회의별 권한(jobs/access.py). 세션 쿠키를 바꿔 끼워 여러 사람으로 요청한다."""

import pytest
from fastapi.testclient import TestClient

from meeting_notes.auth import OIDC, SESSION_COOKIE, UserBook
from meeting_notes.jobs.store import JobStore
from meeting_notes.main import create_app
from meeting_notes.speakers.voices import VoiceBook
from tests.test_app import fake_process, tone, upload, wait_for  # noqa: F401
from tests.test_features import fake_process as voice_process

SETTINGS = {
    "issuer": "http://sso.example/oidc",
    "client_id": "meeting-notes",
    "base_url": "http://meet.example:8000",
    "admin_subs": ["admin"],
}
OWNER = {"sub": "u1", "name": "홍길동"}
ATTENDEE = {"sub": "u2", "name": "김철수"}
OTHER = {"sub": "u3", "name": "이영희"}
ADMIN = {"sub": "admin", "name": "관리자"}


def open_site(tmp_path, process):
    oidc = OIDC(SETTINGS, tmp_path)
    users = UserBook(tmp_path)
    for person in (OWNER, ATTENDEE, OTHER, ADMIN):
        users.seen(person)
    app = create_app(data_dir=tmp_path, process=process, tracker=None, auth=oidc)
    with TestClient(app, base_url="http://127.0.0.1") as client:

        def act_as(user):
            client.cookies.set(SESSION_COOKIE, oidc.session(user))
            return client

        yield act_as


@pytest.fixture
def site(tmp_path):
    yield from open_site(tmp_path, fake_process)


@pytest.fixture
def voice_site(tmp_path):
    """화자마다 목소리 특징을 남기는 처리로 연다."""
    yield from open_site(tmp_path, voice_process)


def meeting(site, tone, **access):
    """OWNER가 올린 회의. access가 있으면 참석자와 공개 범위를 정한다."""
    client = site(OWNER)
    job_id = upload(client, tone)
    wait_for(client, job_id, "done")
    if access:
        assert client.put(f"/api/jobs/{job_id}/access", json=access).status_code == 200
    return job_id


def test_everyone_sees_but_only_owner_and_attendees_edit(site, tone):
    job_id = meeting(site, tone, attendees=[ATTENDEE["sub"]])

    other = site(OTHER)
    job = other.get(f"/api/jobs/{job_id}").json()
    assert job["access"] == {"view": True, "edit": False, "manage": False}
    assert job["owner"] == OWNER and job["attendees"] == [ATTENDEE] and job["login"] is True
    assert other.get(f"/api/jobs/{job_id}/audio").status_code == 200
    assert other.get(f"/api/jobs/{job_id}/download").status_code == 200
    refused = [
        other.put(f"/api/jobs/{job_id}/notes", json={"notes": "# 회의록: 바꿈\n"}),
        other.put(f"/api/jobs/{job_id}/speakers/SPEAKER_00", json={"name": "누군가"}),
        other.post(f"/api/jobs/{job_id}/confirm"),
        other.post(f"/api/jobs/{job_id}/regenerate", json={"template": "general"}),
        other.post(f"/api/jobs/{job_id}/issues/drafts"),
        other.post(f"/api/jobs/{job_id}/documents", files={"file": ("메모.txt", "자료".encode(), "text/plain")}),
        other.put(f"/api/jobs/{job_id}/access", json={"attendees": [OTHER["sub"]]}),
        other.delete(f"/api/jobs/{job_id}"),
    ]
    assert [response.status_code for response in refused] == [403] * len(refused)
    assert refused[0].json()["detail"] == "이 회의록은 올린 사람과 참석자만 고칠 수 있어요."

    attendee = site(ATTENDEE)
    assert attendee.get(f"/api/jobs/{job_id}").json()["access"] == {"view": True, "edit": True, "manage": False}
    assert attendee.put(f"/api/jobs/{job_id}/notes", json={"notes": "# 회의록: 바꿈\n"}).status_code == 200
    assert attendee.post(f"/api/jobs/{job_id}/confirm").status_code == 200
    assert attendee.put(f"/api/jobs/{job_id}/access", json={"attendees": []}).status_code == 403
    assert attendee.delete(f"/api/jobs/{job_id}").status_code == 403

    assert site(OWNER).delete(f"/api/jobs/{job_id}").status_code == 200


def test_private_meeting_is_hidden_from_everyone_else(site, tone):
    job_id = meeting(site, tone, attendees=[ATTENDEE["sub"]], private=True)

    other = site(OTHER)
    assert [job["id"] for job in other.get("/api/jobs").json()] == []
    assert other.get(f"/api/jobs/{job_id}").status_code == 404
    assert other.get(f"/api/jobs/{job_id}/audio").status_code == 404
    assert other.get("/api/search", params={"q": "예시"}).json() == []

    for person in (ATTENDEE, ADMIN):
        client = site(person)
        assert [job["id"] for job in client.get("/api/jobs").json()] == [job_id]
        assert [result["id"] for result in client.get("/api/search", params={"q": "예시"}).json()] == [job_id]


def test_attendees_are_people_who_have_logged_in(site, tone):
    job_id = meeting(site, tone)
    owner = site(OWNER)
    missing = owner.put(f"/api/jobs/{job_id}/access", json={"attendees": ["nobody"]})
    assert missing.status_code == 404
    # 올린 사람은 참석자 목록에 넣지 않고, 같은 사람은 한 번만 넣는다.
    job = owner.put(f"/api/jobs/{job_id}/access", json={"attendees": ["u1", "u2", "u2"]}).json()
    assert job["attendees"] == [ATTENDEE] and job["private"] is False
    assert owner.get("/api/users").json() == [ADMIN, ATTENDEE, OTHER, OWNER]  # 이름 가나다순


def test_admin_manages_meetings_uploaded_before_login(site, tone, tmp_path):
    job_id = meeting(site, tone)
    JobStore(tmp_path).update(job_id, owner=None)

    assert site(OWNER).put(f"/api/jobs/{job_id}/notes", json={"notes": "# 회의록: 바꿈\n"}).status_code == 403
    admin = site(ADMIN)
    assert admin.get(f"/api/jobs/{job_id}").json()["access"] == {"view": True, "edit": True, "manage": True}
    assert admin.put(f"/api/jobs/{job_id}/access", json={"attendees": [OWNER["sub"]]}).status_code == 200
    assert site(OWNER).put(f"/api/jobs/{job_id}/notes", json={"notes": "# 회의록: 바꿈\n"}).status_code == 200


def test_voices_are_shared_but_only_registrant_or_admin_deletes(voice_site, tone, tmp_path):
    owner = voice_site(OWNER)
    job_id = upload(owner, tone)
    wait_for(owner, job_id, "done")
    owner.put(f"/api/jobs/{job_id}/speakers/SPEAKER_00", json={"name": "길동", "remember": True})
    VoiceBook(tmp_path).register("예전 목소리", [0.0, 0.0, 1.0])  # 로그인을 켜기 전에 등록한 목소리

    other = voice_site(OTHER)
    voices = {voice["name"]: voice for voice in other.get("/api/voices").json()}
    assert voices["길동"]["owner"] == OWNER and voices["길동"]["can_delete"] is False
    assert voices["예전 목소리"]["owner"] is None and voices["예전 목소리"]["can_delete"] is False
    refused = other.delete(f"/api/voices/{voices['길동']['id']}")
    assert refused.status_code == 403 and refused.json()["detail"] == "목소리를 등록한 사람과 관리자만 지울 수 있어요."

    # 다른 사람이 올린 회의에서도 알아본다.
    attendee = voice_site(ATTENDEE)
    second = upload(attendee, tone)
    job = wait_for(attendee, second, "done")
    assert next(s for s in job["speakers"] if s["label"] == "SPEAKER_00")["name"] == "길동"

    assert voice_site(OWNER).delete(f"/api/voices/{voices['길동']['id']}").status_code == 200
    assert voice_site(OWNER).delete(f"/api/voices/{voices['예전 목소리']['id']}").status_code == 403
    assert voice_site(ADMIN).delete(f"/api/voices/{voices['예전 목소리']['id']}").status_code == 200
    assert voice_site(OTHER).get("/api/voices").json() == []


def test_without_login_everyone_can_do_everything(tmp_path, tone):
    app = create_app(data_dir=tmp_path, process=fake_process, tracker=None, auth=None)
    with TestClient(app, base_url="http://127.0.0.1") as client:
        job_id = upload(client, tone)
        job = wait_for(client, job_id, "done")
        assert job["access"] == {"view": True, "edit": True, "manage": True}
        assert job["login"] is False and job["owner"] is None
        assert client.get("/api/users").json() == []
