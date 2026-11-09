"""사용자가 직접 확인해 준 사실. 다음 회의록을 쓰거나 질문에 답할 때 표기와 이름을 바로잡는 데 쓴다.

"확인 필요" 항목을 체크하면서 확인한 내용을 적고 "다음 회의에도 AI가 알게 하기"를 켜면 여기에 쌓인다.
회의에 나오지 않은 사실을 회의록에 넣는 데는 쓰지 않는다(pipeline/templates.py의 배경 지식 규칙).
사람 이름이 들어가므로 본인만 읽을 수 있게 저장하고, "AI가 기억하는 내용" 화면에서 지운다.
"""

import json
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

from meeting_notes.files import write_private


class MemoryBook:
    def __init__(self, root):
        self.path = Path(root) / "memory.json"
        self.lock = threading.Lock()

    def _load(self):
        return json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else []

    def _save(self, items):
        write_private(self.path, json.dumps(items, ensure_ascii=False))

    def list(self):
        with self.lock:
            return self._load()

    def add(self, question, answer, job_id):
        """같은 질문을 다시 확인하면 답을 새로 바꾼다."""
        with self.lock:
            items = [item for item in self._load() if item["question"] != question]
            items.append(
                {
                    "id": uuid.uuid4().hex,
                    "question": question,
                    "answer": answer,
                    "job_id": job_id,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                }
            )
            self._save(items)

    def delete(self, item_id):
        with self.lock:
            items = self._load()
            remaining = [item for item in items if item["id"] != item_id]
            if len(remaining) == len(items):
                return False
            self._save(remaining)
            return True

    def facts(self):
        """프롬프트에 넣을 한 줄씩의 사실."""
        return [f"{item['question']} → {item['answer']}" for item in self.list()]
