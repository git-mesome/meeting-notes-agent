"""녹음을 한 번에 한 건씩 처리하는 큐."""

import json
import logging
import queue
import threading

from meeting_notes.jobs.store import now
from meeting_notes.pipeline.audio import find_audio
from meeting_notes.pipeline.notes import notes_title
from meeting_notes.speakers.embeddings import extract_embeddings

logger = logging.getLogger(__name__)

FAILURE_MESSAGES = {
    "transcribing": "음성을 글로 옮기지 못했어요. 다시 시도해 주세요.",
    "writing": "회의록을 쓰지 못했어요. 다시 시작하면 전사는 건너뛰고 회의록만 다시 써요.",
}


class JobCanceled(Exception):
    """사용자가 처리를 중지했다."""


class Worker(threading.Thread):
    def __init__(self, store, process, voices, push):
        super().__init__(daemon=True)
        self.store = store
        self.process = process
        self.voices = voices
        self.push = push
        self.queue = queue.Queue()
        self.lock = threading.Lock()
        self.current_job = None
        self.current_process = None

    def run(self):
        while True:
            self.handle(self.queue.get())

    def handle(self, job_id):
        job = self.store.read(job_id)
        if job is None or job["status"] != "queued":
            return  # 기다리는 동안 중지했거나 삭제했다.
        with self.lock:
            self.current_job = job_id
        try:
            self.run_job(job_id)
        finally:
            with self.lock:
                self.current_job = None
                self.current_process = None

    def run_job(self, job_id):
        job_dir = self.store.path(job_id)
        audio = find_audio(job_dir)

        def on_stage(stage):
            with self.lock:
                if self.store.read(job_id)["status"] == "canceled":
                    raise JobCanceled
                self.store.update(job_id, status=stage, stage_started_at=now())

        def on_process(process):
            with self.lock:
                self.current_process = process
                if self.store.read(job_id)["status"] == "canceled":
                    process.terminate()

        try:
            usage = self.process(audio, job_dir, on_stage, on_process)
            notes = (job_dir / "notes.md").read_text(encoding="utf-8")
            recognized = self.recognize(job_id, job_dir)
            with self.lock:
                job = self.store.read(job_id)
                if job["status"] == "canceled":
                    return
                self.store.update(
                    job_id, status="done", title=notes_title(notes, job["name"]), usage=usage, error=None, **recognized
                )
            self.notify("회의록이 완성됐어요", "눌러서 확인해 보세요", job_id)
        except Exception as error:
            with self.lock:
                stage = self.store.read(job_id)["status"]
                if stage == "canceled":
                    return
                logger.error("작업 %s 처리에 실패했다", job_id, exc_info=error)
                message = FAILURE_MESSAGES.get(stage, FAILURE_MESSAGES["transcribing"])
                self.store.update(job_id, status="failed", error=message)
            self.notify("회의록을 만들지 못했어요", "눌러서 다시 시도해 보세요", job_id)

    def recognize(self, job_id, job_dir):
        """등록한 목소리와 대조해 이름을 붙인다. 실패해도 회의록 처리는 계속한다."""
        try:
            embeddings = extract_embeddings(job_dir)
            job = self.store.read(job_id)
            if not embeddings or job.get("speaker_names") or job.get("auto_speakers"):
                return {}
            # 발언이 전사되지 않은 화자가 먼저 짝지어지면 실제 발언자에게 이름이 붙지 않는다.
            turns = json.loads((job_dir / "turns.json").read_text(encoding="utf-8"))
            speaking = {turn["speaker"] for turn in turns}
            matches = self.voices.match({label: value for label, value in embeddings.items() if label in speaking})
            if not matches:
                return {}
            return {
                "speaker_names": {label: match["name"] for label, match in matches.items()},
                "auto_speakers": {label: match["score"] for label, match in matches.items()},
            }
        except Exception as error:
            logger.error("작업 %s 화자 인식에 실패했다", job_id, exc_info=error)
            return {}

    def notify(self, title, body, job_id):
        try:
            self.push.notify(title, body, f"/#/jobs/{job_id}")
        except Exception as error:
            logger.warning("알림을 보내지 못했다: %s", type(error).__name__)

    def cancel(self, job_id):
        with self.lock:
            self.store.update(job_id, status="canceled", error=None)
            if self.current_job == job_id and self.current_process:
                self.current_process.terminate()

    def is_running(self, job_id):
        with self.lock:
            return self.current_job == job_id
