"""연습용 이슈 트래커 어댑터. 이슈를 이 폴더의 issues.json에 저장한다.

실제 트래커(Jira, GitHub Issues, 사내 도구 등)를 붙일 때는 이 파일을 복사해 메서드 안을 그 트래커의 API 호출로
바꾸고, company.toml의 [tracker] module에 새 파일 이름을 적는다. 규격은 src/meeting_notes/issues/trackers.py에 있다.
"""

import json
import threading
from pathlib import Path

from meeting_notes.issues import Tracker, TrackerError


class FileTracker(Tracker):
    name = "연습용 트래커"
    destination = "issues.json"
    categories = ["기능", "버그"]
    priorities = ["높음", "보통", "낮음"]
    guide = '- description에는 "## 배경"과 "## 완료 조건"(- [ ] 체크리스트)을 쓴다.'
    after_register = "회사 폴더의 issues.json에 저장했어요."

    def __init__(self, path, people, tags):
        self.path = path
        self.members = people
        self.labels = tags
        self.lock = threading.Lock()

    def _load(self):
        return json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else []

    def _save(self, issues):
        self.path.write_text(json.dumps(issues, ensure_ascii=False, indent=2), encoding="utf-8")

    def people(self):
        return self.members

    def tags(self):
        return self.labels

    def open_issues(self):
        return [
            {
                "key": issue["key"],
                "title": issue["title"],
                "type": issue.get("type", "task"),
                "status": "열림",
                "tags": issue.get("tags", []),
                "assignees": issue.get("assignees", []),
            }
            for issue in self._load()
        ]

    def issue(self, key):
        for issue in self._load():
            if issue["key"] == key:
                return issue
        raise TrackerError(f"{key} 이슈가 없어요.")

    def create(self, issues):
        with self.lock:
            stored = self._load()
            keys = []
            for issue in issues:
                key = f"DEMO-{len(stored) + 1}"
                stored.append({"key": key, "type": "task", "comments": [], **issue})
                keys.append(key)
            self._save(stored)
        return keys

    def comment(self, key, text):
        with self.lock:
            stored = self._load()
            for issue in stored:
                if issue["key"] == key:
                    issue.setdefault("comments", []).append(text)
                    self._save(stored)
                    return
        raise TrackerError(f"{key} 이슈가 없어요.")


def create(settings):
    path = Path(__file__).parent / settings.get("file", "issues.json")
    return FileTracker(path, settings.get("people", []), settings.get("tags", []))
