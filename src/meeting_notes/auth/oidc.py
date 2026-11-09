"""사내 SSO(OpenID Connect)로 로그인한다.

company.toml:
    [auth]
    issuer = "https://sso.example.com/oidc"   # /.well-known/openid-configuration 이 있는 주소
    client_id = "..."
    client_secret_env = "SSO_CLIENT_SECRET"   # .env에 둔 client secret의 변수 이름. 비우면 공개 클라이언트로 PKCE만 쓴다.
    role_claim = "role"                       # 역할이 들어 있는 클레임 이름
    allowed_roles = []                        # 비우면 로그인한 사람 모두 들어온다
    session_hours = 168

앱 주소는 컴퓨터마다 다르므로 .env의 PUBLIC_URL(예: http://meeting.example:8000)로 정한다. SSO에 등록할
redirect URI는 <PUBLIC_URL>/auth/callback이다. [auth]나 PUBLIC_URL이 없으면 로그인 없이 동작한다. 혼자 자기
컴퓨터에서 쓸 때를 위한 것이다.
"""

import base64
import hashlib
import json
import os
import secrets
import urllib.error
import urllib.parse
import urllib.request

import jwt

from meeting_notes.auth.session import Signer, b64, load_key, same

SESSION_COOKIE = "mn_session"
FLOW_COOKIE = "mn_login"
FLOW_SECONDS = 600


class AuthError(Exception):
    """로그인을 끝내지 못했다. 메시지는 화면에 그대로 보인다."""

    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def safe_next(path):
    """로그인 뒤 돌아갈 곳. 다른 사이트로 보내지 않도록 이 앱 안의 경로만 받는다."""
    if not path or not path.startswith("/") or path.startswith("//") or "\\" in path:
        return "/"
    return path


class OIDC:
    def __init__(self, settings, key_dir):
        self.issuer = settings["issuer"].rstrip("/")
        self.client_id = settings["client_id"]
        secret_env = settings.get("client_secret_env")
        self.client_secret = os.environ.get(secret_env) if secret_env else None
        self.base_url = settings["base_url"].rstrip("/")
        self.role_claim = settings.get("role_claim", "role")
        self.allowed_roles = settings.get("allowed_roles") or []
        self.session_seconds = int(settings.get("session_hours", 168)) * 3600
        self.secure = self.base_url.startswith("https://")
        self.signer = Signer(load_key(key_dir))
        self._discovery = None
        self._jwks = None

    @property
    def redirect_uri(self):
        return f"{self.base_url}/auth/callback"

    def discovery(self):
        if self._discovery is None:
            url = f"{self.issuer}/.well-known/openid-configuration"
            with urllib.request.urlopen(url, timeout=10) as response:
                self._discovery = json.loads(response.read())
        return self._discovery

    def login(self, next_path):
        """SSO 로그인 주소와, 돌아왔을 때 맞춰 볼 값을 담은 쿠키를 만든다."""
        state, nonce, verifier = secrets.token_urlsafe(24), secrets.token_urlsafe(24), secrets.token_urlsafe(48)
        challenge = b64(hashlib.sha256(verifier.encode()).digest())
        query = urllib.parse.urlencode(
            {
                "response_type": "code",
                "client_id": self.client_id,
                "redirect_uri": self.redirect_uri,
                "scope": "openid profile email",
                "state": state,
                "nonce": nonce,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            }
        )
        flow = self.signer.dumps({"state": state, "nonce": nonce, "verifier": verifier, "next": safe_next(next_path)}, FLOW_SECONDS)
        return f"{self.discovery()['authorization_endpoint']}?{query}", flow

    def finish(self, code, state, flow_cookie):
        """SSO에서 돌아온 코드를 토큰으로 바꾸고 ID 토큰을 검증해 사용자 정보를 돌려준다."""
        flow = self.signer.loads(flow_cookie or "")
        if not flow or not state or not same(flow["state"], state):
            raise AuthError("로그인 요청이 만료됐거나 맞지 않아요. 다시 로그인해 주세요.")
        tokens = self.exchange(code, flow["verifier"])
        claims = self.verify(tokens.get("id_token", ""), flow["nonce"])
        user = {
            "sub": claims["sub"],
            "name": claims.get("name") or claims.get("preferred_username") or claims["sub"],
            "username": claims.get("preferred_username", ""),
            "email": claims.get("email", ""),
            "role": claims.get(self.role_claim, ""),
        }
        if self.allowed_roles and user["role"] not in self.allowed_roles:
            raise AuthError("이 회의록을 쓸 수 있는 사용자가 아니에요. 관리자에게 문의해 주세요.", 403)
        return user, flow["next"]

    def exchange(self, code, verifier):
        form = {"grant_type": "authorization_code", "code": code, "redirect_uri": self.redirect_uri, "code_verifier": verifier}
        headers = {"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"}
        if self.client_secret:
            pair = f"{urllib.parse.quote(self.client_id, safe='')}:{urllib.parse.quote(self.client_secret, safe='')}"
            headers["Authorization"] = "Basic " + base64.b64encode(pair.encode()).decode()
        else:
            form["client_id"] = self.client_id
        request = urllib.request.Request(
            self.discovery()["token_endpoint"], data=urllib.parse.urlencode(form).encode(), headers=headers, method="POST"
        )
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                return json.loads(response.read())
        except (urllib.error.URLError, OSError) as error:
            raise AuthError("SSO에서 로그인을 확인하지 못했어요. 다시 로그인해 주세요.") from error

    def verify(self, id_token, nonce):
        if self._jwks is None:
            self._jwks = jwt.PyJWKClient(self.discovery()["jwks_uri"])
        try:
            key = self._jwks.get_signing_key_from_jwt(id_token)
            claims = jwt.decode(id_token, key, algorithms=["RS256"], audience=self.client_id, issuer=self.discovery()["issuer"])
        except jwt.PyJWTError as error:
            raise AuthError("SSO가 보낸 로그인 정보를 확인하지 못했어요.") from error
        if not same(claims.get("nonce", ""), nonce):
            raise AuthError("로그인 요청이 맞지 않아요. 다시 로그인해 주세요.")
        return claims

    def session(self, user):
        return self.signer.dumps(user, self.session_seconds)

    def user(self, cookie):
        data = self.signer.loads(cookie or "")
        return data if data and "sub" in data else None

    def logout_url(self):
        try:
            end = self.discovery().get("end_session_endpoint")
        except (urllib.error.URLError, OSError):
            return "/"
        if not end:
            return "/"
        query = urllib.parse.urlencode({"client_id": self.client_id, "post_logout_redirect_uri": f"{self.base_url}/"})
        return f"{end}?{query}"
