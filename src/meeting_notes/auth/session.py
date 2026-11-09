"""로그인 상태를 담는 쿠키를 서명하고 확인한다."""

import base64
import hashlib
import hmac
import json
import secrets
import time
from pathlib import Path

from meeting_notes.files import write_private


def b64(data):
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def unb64(text):
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


class Signer:
    """쿠키 값을 서버만 아는 키로 서명해, 사용자가 고칠 수 없게 한다."""

    def __init__(self, key):
        self.key = key

    def dumps(self, data, seconds):
        body = b64(json.dumps({**data, "exp": int(time.time()) + seconds}, ensure_ascii=False).encode())
        return f"{body}.{b64(hmac.new(self.key, body.encode(), hashlib.sha256).digest())}"

    def loads(self, value):
        try:
            body, signature = value.split(".")
            expected = b64(hmac.new(self.key, body.encode(), hashlib.sha256).digest())
            if not hmac.compare_digest(signature, expected):
                return None
            data = json.loads(unb64(body))
        except (AttributeError, ValueError):
            return None
        return data if data.get("exp", 0) > time.time() else None


def same(a, b):
    """시간 차이로 값을 알아내지 못하게 비교한다. 한글이 섞여도 되도록 바이트로 바꿔 비교한다."""
    return hmac.compare_digest(str(a).encode(), str(b).encode())


def load_key(root):
    path = Path(root) / "session-key"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        write_private(path, secrets.token_hex(32))
    return bytes.fromhex(path.read_text().strip())
