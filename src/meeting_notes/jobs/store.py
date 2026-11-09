"""작업마다 폴더 하나를 쓰고 상태는 meta.json에 저장한다."""

import json
import os
import re
import threading
from datetime import datetime, timezone
from pathlib import Path

JOB_ID = re.compile(r"[0-9a-f]{32}")
ACTIVE_STATUSES = ("queued", "transcribing", "writing")


def now():
    return datetime.now(timezone.utc).isoformat()


class JobStore:
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()

    def path(self, job_id):
        return self.root / job_id

    def read(self, job_id):
        meta = self.path(job_id) / "meta.json"
        if not JOB_ID.fullmatch(job_id) or not meta.exists():
            return None
        return json.loads(meta.read_text(encoding="utf-8"))

    def write(self, job):
        meta = self.path(job["id"]) / "meta.json"
        temp = meta.with_suffix(".tmp")
        temp.write_text(json.dumps(job, ensure_ascii=False), encoding="utf-8")
        os.replace(temp, meta)

    def update(self, job_id, **fields):
        with self.lock:
            job = self.read(job_id)
            job.update(fields)
            self.write(job)
            return job

    def all(self):
        jobs = [self.read(path.name) for path in self.root.iterdir() if path.is_dir()]
        return sorted((job for job in jobs if job), key=lambda job: job["created_at"], reverse=True)
