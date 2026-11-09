import base64
import hashlib
import json
import subprocess
import time
import urllib.parse

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from meeting_notes.auth import OIDC, Signer, oidc as auth_module, safe_next
from meeting_notes.main import create_app
from meeting_notes.settings import Company

ISSUER = "http://sso.example/oidc"
DISCOVERY = {
    "issuer": ISSUER,
    "authorization_endpoint": f"{ISSUER}/auth",
    "token_endpoint": f"{ISSUER}/token",
    "jwks_uri": f"{ISSUER}/jwks",
    "end_session_endpoint": f"{ISSUER}/session/end",
}
SETTINGS = {
    "issuer": ISSUER,
    "client_id": "meeting-notes",
    "client_secret_env": "SSO_SECRET",
    "base_url": "http://meet.example:8000",
    "role_claim": "team_role",
}


class Response:
    def __init__(self, body):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def read(self):
        return json.dumps(self.body).encode()


class FakeSSO:
    """discovery, 토큰 발급, 서명 키를 흉내 낸다."""

    def __init__(self):
        self.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.claims = {}
        self.token_requests = []

    def urlopen(self, request, timeout=None):
        url = request if isinstance(request, str) else request.full_url
        if url == f"{ISSUER}/.well-known/openid-configuration":
            return Response(DISCOVERY)
        if url == DISCOVERY["token_endpoint"]:
            self.token_requests.append((dict(request.header_items()), dict(urllib.parse.parse_qsl(request.data.decode()))))
            return Response({"access_token": "x", "id_token": self.id_token()})
        raise AssertionError(url)

    def id_token(self):
        now = int(time.time())
        claims = {"iss": ISSUER, "aud": SETTINGS["client_id"], "sub": "u1", "name": "홍길동", "preferred_username": "gildong",
                  "email": "gildong@example.com", "team_role": "member", "iat": now, "exp": now + 300, **self.claims}
        return jwt.encode(claims, self.key, algorithm="RS256", headers={"kid": "k1"})


class FakeJWKS:
    def __init__(self, public_key):
        self.public_key = public_key

    def get_signing_key_from_jwt(self, _token):
        return self.public_key


@pytest.fixture
def sso(monkeypatch):
    fake = FakeSSO()
    monkeypatch.setattr(auth_module.urllib.request, "urlopen", fake.urlopen)
    monkeypatch.setattr(auth_module.jwt, "PyJWKClient", lambda _uri: FakeJWKS(fake.key.public_key()))
    monkeypatch.setenv("SSO_SECRET", "s3cret")
    return fake


@pytest.fixture(scope="session")
def tone(tmp_path_factory):
    path = tmp_path_factory.mktemp("audio") / "tone.m4a"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=1", str(path)], check=True)
    return path.read_bytes()


def idle_process(audio, out_dir, on_stage, on_process):
    on_stage("transcribing")
    (out_dir / "turns.json").write_text("[]", encoding="utf-8")
    (out_dir / "notes.md").write_text("# 회의록: 시험\n", encoding="utf-8")
    return {"input_tokens": 0, "output_tokens": 0}


def make(tmp_path, settings=SETTINGS):
    oidc = OIDC(settings, tmp_path)
    return TestClient(create_app(data_dir=tmp_path, process=idle_process, tracker=None, auth=oidc), base_url="http://127.0.0.1")


def log_in(client, sso, next_path="/"):
    response = client.get("/auth/login", params={"next": next_path}, follow_redirects=False)
    assert response.status_code == 303
    query = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(response.headers["location"]).query))
    sso.claims.setdefault("nonce", query["nonce"])
    callback = client.get("/auth/callback", params={"code": "abc", "state": query["state"]}, follow_redirects=False)
    return query, callback


def test_without_auth_settings_everything_is_open(tmp_path):
    with TestClient(create_app(data_dir=tmp_path, process=idle_process, tracker=None, auth=None), base_url="http://127.0.0.1") as client:
        assert client.get("/api/jobs").status_code == 200
        assert client.get("/api/me").json() == {"login": False, "name": None}


def test_api_needs_login_and_pages_go_to_sso(tmp_path, sso):
    with make(tmp_path) as client:
        assert client.get("/api/jobs").status_code == 401
        page = client.get("/", follow_redirects=False)
        assert page.status_code == 303 and page.headers["location"] == "/auth/login?next=/"
        assert client.get("/static/js/main.js").status_code == 200
        assert client.get("/sw.js").status_code == 200


def test_login_flow_uses_pkce_and_opens_the_app(tmp_path, sso, tone):
    with make(tmp_path) as client:
        query, callback = log_in(client, sso, "/#/jobs/abc")
        assert query["client_id"] == "meeting-notes" and query["code_challenge_method"] == "S256"
        assert query["redirect_uri"] == "http://meet.example:8000/auth/callback" and query["scope"] == "openid profile email"
        assert callback.status_code == 303 and callback.headers["location"] == "/#/jobs/abc"

        headers, form = sso.token_requests[0]
        assert headers["Authorization"] == "Basic " + base64.b64encode(b"meeting-notes:s3cret").decode()
        challenge = base64.urlsafe_b64encode(hashlib.sha256(form["code_verifier"].encode()).digest()).rstrip(b"=").decode()
        assert challenge == query["code_challenge"] and form["code"] == "abc"

        assert client.get("/api/me").json() == {"login": True, "name": "홍길동"}
        job = client.post("/api/jobs", files={"file": ("a.m4a", tone, "audio/mp4")}).json()
        meta = json.loads((tmp_path / job["id"] / "meta.json").read_text(encoding="utf-8"))
        assert meta["owner"] == {"sub": "u1", "name": "홍길동"}


@pytest.mark.parametrize(
    "claims",
    [{"nonce": "다른 값"}, {"aud": "other-app"}, {"iss": "http://evil.example"}, {"exp": int(time.time()) - 10}],
)
def test_callback_rejects_tokens_that_do_not_match(tmp_path, sso, claims):
    sso.claims.update(claims)
    with make(tmp_path) as client:
        _, callback = log_in(client, sso)
        assert callback.status_code == 400
        assert client.get("/api/jobs").status_code == 401


def test_callback_rejects_wrong_state(tmp_path, sso):
    with make(tmp_path) as client:
        client.get("/auth/login", follow_redirects=False)
        response = client.get("/auth/callback", params={"code": "abc", "state": "가짜"}, follow_redirects=False)
        assert response.status_code == 400 and sso.token_requests == []


def test_roles_can_be_limited(tmp_path, sso):
    with make(tmp_path, {**SETTINGS, "allowed_roles": ["admin"]}) as client:
        _, callback = log_in(client, sso)
        assert callback.status_code == 403
        assert client.get("/api/jobs").status_code == 401


def test_forged_session_is_refused(tmp_path, sso):
    with make(tmp_path) as client:
        log_in(client, sso)
        value = client.cookies.get("mn_session")
        body, signature = value.split(".")
        forged = base64.urlsafe_b64encode(json.dumps({"sub": "admin", "name": "관리자", "exp": 2**40}).encode()).rstrip(b"=").decode()
        client.cookies.clear()
        client.cookies.set("mn_session", f"{forged}.{signature}")
        assert client.get("/api/jobs").status_code == 401
        client.cookies.clear()
        client.cookies.set("mn_session", f"{body}.{signature}")
        assert client.get("/api/jobs").status_code == 200


def test_logout_clears_session_and_ends_sso_session(tmp_path, sso):
    with make(tmp_path) as client:
        log_in(client, sso)
        response = client.get("/auth/logout", follow_redirects=False)
        assert response.headers["location"].startswith(f"{ISSUER}/session/end?")
        assert "post_logout_redirect_uri=http%3A%2F%2Fmeet.example%3A8000%2F" in response.headers["location"]
        assert client.get("/api/jobs").status_code == 401


def test_signer_rejects_tampering_and_expiry():
    signer = Signer(b"k" * 32)
    value = signer.dumps({"sub": "u1"}, 60)
    assert signer.loads(value)["sub"] == "u1"
    assert signer.loads(value[:-2] + "xx") is None
    assert signer.loads(signer.dumps({"sub": "u1"}, -1)) is None
    assert Signer(b"j" * 32).loads(value) is None


@pytest.mark.parametrize(
    ("path", "expected"),
    [("/#/jobs/abc", "/#/jobs/abc"), ("//evil.example", "/"), ("https://evil.example", "/"), ("/\\evil", "/"), ("", "/")],
)
def test_login_only_returns_to_this_app(path, expected):
    assert safe_next(path) == expected


def test_login_turns_on_only_where_public_url_is_set(tmp_path, monkeypatch):
    (tmp_path / "company.toml").write_text('[auth]\nissuer = "http://sso.example/oidc"\nclient_id = "meeting-notes"\n', encoding="utf-8")
    monkeypatch.delenv("PUBLIC_URL", raising=False)
    assert Company(tmp_path).auth(tmp_path / "keys") is None
    monkeypatch.setenv("PUBLIC_URL", "http://meet.example:8000/")
    company = Company(tmp_path)
    oidc = company.auth(tmp_path / "keys")
    assert oidc.redirect_uri == "http://meet.example:8000/auth/callback" and oidc.client_secret is None
    assert "meet.example" in company.allowed_hosts and "*.ts.net" in company.allowed_hosts
    assert Company(tmp_path / "없음").auth(tmp_path) is None
