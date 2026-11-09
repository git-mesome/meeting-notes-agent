"""등록한 사람의 목소리 특징을 저장하고 새 회의의 화자와 대조한다.

목소리 특징은 생체 정보다. 이 노트북 밖으로 보내지 않고, 사용자가 사람별로 직접 켠 경우에만 저장한다.
"""

import json
import math
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

from meeting_notes.files import write_private

# 같은 회의의 두 구간에서 잰 값은 같은 사람 0.81~0.93, 다른 사람 0.61 이하였다. 다른 이름을 붙이는 쪽이 더
# 해로우므로 높게 잡았다. 날짜와 장소가 다른 회의에서는 점수가 낮아질 수 있어 녹음이 쌓이면 다시 재야 한다.
MATCH_THRESHOLD = 0.75


def cosine(a, b):
    dot = sum(x * y for x, y in zip(a, b))
    size = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return dot / size if size else 0.0


class VoiceBook:
    def __init__(self, root):
        self.path = Path(root) / "voices.json"
        self.lock = threading.Lock()

    def _load(self):
        if not self.path.exists():
            return []
        return json.loads(self.path.read_text(encoding="utf-8"))

    def _save(self, voices):
        write_private(self.path, json.dumps(voices, ensure_ascii=False))

    def list(self):
        with self.lock:
            voices = self._load()
        return [{key: voice[key] for key in ("id", "name", "samples", "updated_at")} for voice in voices]

    def register(self, name, embedding):
        """이름이 같으면 평균을 내서 합친다."""
        with self.lock:
            voices = self._load()
            now = datetime.now(timezone.utc).isoformat()
            for voice in voices:
                if voice["name"] == name:
                    count = voice["samples"]
                    voice["embedding"] = [
                        (old * count + new) / (count + 1) for old, new in zip(voice["embedding"], embedding)
                    ]
                    voice["samples"] = count + 1
                    voice["updated_at"] = now
                    break
            else:
                voices.append(
                    {"id": uuid.uuid4().hex, "name": name, "embedding": embedding, "samples": 1, "updated_at": now}
                )
            self._save(voices)

    def delete(self, voice_id):
        with self.lock:
            voices = self._load()
            remaining = [voice for voice in voices if voice["id"] != voice_id]
            if len(remaining) == len(voices):
                return False
            self._save(remaining)
            return True

    def match(self, embeddings):
        """화자 라벨마다 가장 비슷한 사람을 찾는다. 한 사람은 한 화자에게만 붙인다."""
        with self.lock:
            voices = self._load()
        pairs = sorted(
            (
                (cosine(embedding, voice["embedding"]), label, voice["name"])
                for label, embedding in embeddings.items()
                for voice in voices
            ),
            reverse=True,
        )
        matches = {}
        used = set()
        for score, label, name in pairs:
            if score < MATCH_THRESHOLD:
                break
            if label not in matches and name not in used:
                matches[label] = {"name": name, "score": round(score, 3)}
                used.add(name)
        return matches
