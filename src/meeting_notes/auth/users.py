"""이 앱에 로그인한 적이 있는 사람. 회의 참석자를 고르는 목록으로 쓴다.

SSO에서 사용자 목록을 받지 않고, 로그인할 때마다 이름을 적어 둔다. 그래서 한 번도 로그인하지 않은 사람은
참석자로 고를 수 없다.
"""

import json
import threading
from datetime import datetime, timezone
from pathlib import Path

from meeting_notes.files import write_private


class UserBook:
    def __init__(self, root):
        self.path = Path(root) / "users.json"
        self.lock = threading.Lock()

    def _load(self):
        return json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else {}

    def seen(self, user):
        """로그인할 때 부른다. SSO에서 이름이 바뀌었으면 새 이름으로 적는다."""
        stamp = datetime.now(timezone.utc).isoformat()
        with self.lock:
            users = self._load()
            entry = users.get(str(user["sub"]), {"first_login": stamp})
            entry.update(name=user["name"], last_login=stamp)
            users[str(user["sub"])] = entry
            write_private(self.path, json.dumps(users, ensure_ascii=False))

    def get(self, sub):
        with self.lock:
            entry = self._load().get(str(sub))
        return {"sub": str(sub), "name": entry["name"]} if entry else None

    def list(self):
        with self.lock:
            users = self._load()
        return sorted(({"sub": sub, "name": entry["name"]} for sub, entry in users.items()), key=lambda person: person["name"])
