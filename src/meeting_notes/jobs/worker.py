"""녹음을 한 번에 한 건씩 처리하는 큐."""

import json
import logging
import queue
import threading

from meeting_notes.jobs.store import now
from meeting_notes.pipeline.audio import find_audio, find_parts, join_parts
from meeting_notes.pipeline.notes import notes_title
from meeting_notes.pipeline.recordings import find_added, merge_recordings, needs_merge, take_added, untranscribed_seconds
from meeting_notes.speakers.embeddings import extract_embeddings

logger = logging.getLogger(__name__)

FAILURE_MESSAGES = {
    "transcribing": "음성을 글로 옮기지 못했어요. 다시 시도해 주세요.",
    "writing": "회의록을 쓰지 못했어요. 다시 시작하면 전사는 건너뛰고 회의록만 다시 써요.",
}


class JobCanceled(Exception):
    """사용자가 처리를 중지했다."""


class Worker(threading.Thread):
    def __init__(self, store, process, voices, push, transcribe=None):
        """process는 녹음 하나를 처리하고, transcribe는 나중에 더 올린 녹음만 전사한다(pipeline/recordings.py)."""
        super().__init__(daemon=True)
        self.store = store
        self.process = process
        self.transcribe = transcribe
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
            # 처리하면 전사문을 새로 쓰므로 그 전에 있던 화자를 적어 둔다.
            before = spoken_labels(job_dir)
            # 더 올린 녹음을 받아 두는 일(jobs/service.py)과 엇갈리지 않게 잠그고 꺼낸다.
            with self.lock:
                if find_added(job_dir):
                    take_added(job_dir)
            # 남은 시간은 새로 전사할 녹음 길이로 어림한다. 녹음 전체를 전사하면 전체 길이로 어림한다.
            self.store.update(job_id, transcribe_seconds=untranscribed_seconds(job_dir) if needs_merge(job_dir) else None)
            # 한 번에 올린 녹음은 잇는 것부터, 더 올린 녹음은 새 녹음 전사부터 전사 단계로 보여 준다.
            if find_parts(job_dir):
                on_stage("transcribing")
                join_parts(job_dir, on_process)
            if needs_merge(job_dir):
                on_stage("transcribing")
                merge_recordings(job_dir, self.transcribe, on_process)
            usage = self.process(find_audio(job_dir), job_dir, on_stage, on_process)
            notes = (job_dir / "notes.md").read_text(encoding="utf-8")
            recognized = self.recognize(job_id, job_dir, before)
            with self.lock:
                job = self.store.read(job_id)
                if job["status"] == "canceled":
                    return
                # 처리하는 동안 녹음을 더 올렸으면 알리지 않고 이어서 처리한다.
                more = bool(find_added(job_dir))
                self.store.update(
                    job_id,
                    status="queued" if more else "done",
                    title=notes_title(notes, job["name"]),
                    usage=usage,
                    error=None,
                    **recognized,
                )
                if more:
                    self.queue.put(job_id)
                    return
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

    def recognize(self, job_id, job_dir, before=frozenset()):
        """등록한 목소리와 대조해 이름을 붙인다. 실패해도 회의록 처리는 계속한다.

        이름을 붙인 적이 있는 회의는 before(처리 전에 있던 화자)를 빼고 새로 나온 화자만 대조한다.
        다시 쓸 때 사용자가 지운 이름을 되살리지 않고, 더 올린 녹음에서 처음 나온 사람에게만 이름을 붙인다.
        """
        try:
            embeddings = extract_embeddings(job_dir)
            job = self.store.read(job_id)
            names = job.get("speaker_names") or {}
            auto = job.get("auto_speakers") or {}
            if not embeddings:
                return {}
            # 발언이 전사되지 않은 화자가 먼저 짝지어지면 실제 발언자에게 이름이 붙지 않는다.
            speaking = spoken_labels(job_dir)
            if names or auto:
                speaking -= before
            matches = self.voices.match({label: value for label, value in embeddings.items() if label in speaking})
            # 한 이름은 한 화자에게만 붙인다. 앞 녹음에서 이미 붙인 이름은 건너뛴다.
            matches = {label: match for label, match in matches.items() if match["name"] not in names.values()}
            if not matches:
                return {}
            return {
                "speaker_names": names | {label: match["name"] for label, match in matches.items()},
                "auto_speakers": auto | {label: match["score"] for label, match in matches.items()},
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


def spoken_labels(job_dir):
    """전사문에서 말한 화자 라벨. 아직 전사문이 없으면 비어 있다."""
    path = job_dir / "turns.json"
    if not path.exists():
        return set()
    return {turn["speaker"] for turn in json.loads(path.read_text(encoding="utf-8"))}
