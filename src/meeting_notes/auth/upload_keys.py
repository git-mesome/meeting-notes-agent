"""아이폰 단축어가 녹음을 올릴 때 쓰는 사람별 키.

단축어는 SSO 로그인을 할 수 없어서, 로그인한 사람이 화면에서 키를 받아 단축어의 Authorization 헤더에 넣는다.
키로는 녹음 올리기(POST /api/jobs)만 할 수 있다(web/middleware.py). 키 원문은 받을 때 한 번만 보여 주고
SHA-256 값만 적어 두므로, 잃어버리면 새로 받는다. 한 사람에 키는 하나이고, 새로 받으면 이전 키는 못 쓴다.
"""

import hashlib
import json
import secrets
import threading
from datetime import datetime, timezone
from pathlib import Path

from meeting_notes.files import write_private

PREFIX = "mn_"


def digest(key):
    return hashlib.sha256(key.encode()).hexdigest()


class UploadKeys:
    def __init__(self, root):
        self.path = Path(root) / "upload-keys.json"
        self.lock = threading.Lock()

    def _load(self):
        return json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else {}

    def _without(self, keys, sub):
        return {hashed: entry for hashed, entry in keys.items() if entry["sub"] != str(sub)}

    def issue(self, user):
        """새 키를 만들어 원문을 돌려준다. 이 사람이 전에 받은 키는 지운다."""
        key = PREFIX + secrets.token_urlsafe(32)
        created_at = datetime.now(timezone.utc).isoformat()
        with self.lock:
            keys = self._without(self._load(), user["sub"])
            keys[digest(key)] = {"sub": str(user["sub"]), "name": user["name"], "created_at": created_at}
            write_private(self.path, json.dumps(keys, ensure_ascii=False))
        return {"key": key, "created_at": created_at}

    def created_at(self, sub):
        """이 사람이 지금 쓰는 키를 받은 때. 키가 없으면 None."""
        with self.lock:
            keys = self._load()
        return next((entry["created_at"] for entry in keys.values() if entry["sub"] == str(sub)), None)

    def revoke(self, sub):
        with self.lock:
            keys = self._load()
            kept = self._without(keys, sub)
            if len(kept) != len(keys):
                write_private(self.path, json.dumps(kept, ensure_ascii=False))

    def user(self, key):
        """키 주인({sub, name}). 맞는 키가 없으면 None."""
        if not key.startswith(PREFIX):
            return None
        with self.lock:
            entry = self._load().get(digest(key))
        return {"sub": entry["sub"], "name": entry["name"]} if entry else None
