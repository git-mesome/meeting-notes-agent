"""회의 녹음을 올리면 회의록 초안을 만들어 주는 웹 서버.

실행: uv run --env-file .env uvicorn app:create_app --factory
"""

import json
import logging
import os
import queue
import re
import shutil
import subprocess
import threading
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile
from starlette.middleware.trustedhost import TrustedHostMiddleware

logger = logging.getLogger("meeting_notes.app")

STATIC_DIR = Path(__file__).parent / "static"
ALLOWED_SUFFIXES = {".m4a", ".mp3", ".wav", ".flac", ".ogg", ".aac", ".mp4", ".webm"}
MAX_UPLOAD_BYTES = 1024**3
TOO_LARGE_MESSAGE = "파일이 너무 커요. 1GB 이하로 올려 주세요."
STILL_STOPPING_MESSAGE = "아직 멈추는 중이에요. 잠시 후 다시 시도해 주세요."
# 파일 이름 없이 본문으로 올라올 때 쓴다. 내용은 ffprobe로 따로 확인한다.
RAW_SUFFIXES = {
    "audio/mpeg": ".mp3",
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
    "audio/flac": ".flac",
    "audio/ogg": ".ogg",
    "audio/aac": ".aac",
    "audio/webm": ".webm",
}
# 로그인이 없으므로 서버는 127.0.0.1에만 열고 Tailscale로만 중계한다.
ALLOWED_HOSTS = ["127.0.0.1", "localhost", "*.ts.net"]
READ_ONLY_METHODS = {"GET", "HEAD", "OPTIONS"}
JOB_ID = re.compile(r"[0-9a-f]{32}")
ACTIVE_STATUSES = ("queued", "transcribing", "writing")

# 노트북 CPU에서 large-v3로 잰 값이다. 음성 1초를 처리하는 데 2.2~2.7초가 걸렸다.
SECONDS_PER_AUDIO_SECOND = 2.5

FAILURE_MESSAGES = {
    "transcribing": "음성을 글로 옮기지 못했어요. 다시 시도해 주세요.",
    "writing": "회의록을 쓰지 못했어요. 다시 시작하면 전사는 건너뛰고 회의록만 다시 써요.",
}

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Content-Security-Policy": (
        "default-src 'self'; script-src 'self'; media-src 'self'; "
        "style-src 'self' https://fonts.googleapis.com https://cdn.jsdelivr.net; "
        "font-src https://fonts.gstatic.com https://cdn.jsdelivr.net; "
        "frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
    ),
}


def now():
    return datetime.now(timezone.utc).isoformat()


def probe_duration(audio):
    """오디오 길이를 초 단위로 돌려준다. 오디오로 읽을 수 없으면 400 오류를 낸다."""
    result = subprocess.run(
        [
            "ffprobe", "-v", "error", "-select_streams", "a",
            "-show_entries", "stream=codec_type:format=duration", "-of", "json", str(audio),
        ],
        capture_output=True,
        text=True,
    )
    try:
        info = json.loads(result.stdout)
        if result.returncode != 0 or not info["streams"]:
            raise ValueError
        duration = float(info["format"]["duration"])
    except (json.JSONDecodeError, KeyError, ValueError) as error:
        raise HTTPException(400, "오디오를 읽을 수 없는 파일이에요. 녹음 파일을 다시 올려 주세요.") from error
    return duration


def notes_title(notes, fallback):
    first_line = notes.strip().splitlines()[0] if notes.strip() else ""
    title = re.sub(r"^#\s*(회의록\s*:\s*)?", "", first_line).strip() if first_line.startswith("#") else ""
    return title or fallback


def find_audio(job_dir):
    """올린 녹음을 찾는다. WhisperX가 audio.json도 만들므로 확장자까지 확인한다."""
    return next(path for path in job_dir.iterdir() if path.stem == "audio" and path.suffix in ALLOWED_SUFFIXES)


def copy_upload(source, target):
    copied = 0
    with open(target, "wb") as out:
        while chunk := source.read(1024 * 1024):
            copied += len(chunk)
            if copied > MAX_UPLOAD_BYTES:
                raise HTTPException(413, TOO_LARGE_MESSAGE)
            out.write(chunk)


def default_process(audio, out_dir, on_stage, on_process):
    from meeting_notes import load_glossary, process_audio

    glossary_path = Path("glossary.txt")
    glossary = load_glossary(glossary_path) if glossary_path.exists() else []
    return process_audio(audio, out_dir, glossary, on_stage, on_process)


class JobStore:
    """작업마다 폴더 하나를 쓰고 상태는 meta.json에 저장한다."""

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


class JobCanceled(Exception):
    """사용자가 처리를 중지했다."""


class Worker(threading.Thread):
    """녹음을 한 번에 한 건씩 처리한다."""

    def __init__(self, store, process):
        super().__init__(daemon=True)
        self.store = store
        self.process = process
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
            with self.lock:
                job = self.store.read(job_id)
                if job["status"] != "canceled":
                    self.store.update(
                        job_id, status="done", title=notes_title(notes, job["name"]), usage=usage, error=None
                    )
        except Exception as error:
            with self.lock:
                stage = self.store.read(job_id)["status"]
                if stage == "canceled":
                    return
                logger.error("작업 %s 처리에 실패했다", job_id, exc_info=error)
                message = FAILURE_MESSAGES.get(stage, FAILURE_MESSAGES["transcribing"])
                self.store.update(job_id, status="failed", error=message)

    def cancel(self, job_id):
        with self.lock:
            self.store.update(job_id, status="canceled", error=None)
            if self.current_job == job_id and self.current_process:
                self.current_process.terminate()

    def is_running(self, job_id):
        with self.lock:
            return self.current_job == job_id


def public_job(job, ahead=0):
    """화면에 보낼 항목만 고르고 남은 시간을 계산한다."""
    view = {
        key: job.get(key)
        for key in ("id", "name", "title", "status", "created_at", "duration_seconds", "error", "confirmed_at")
    }
    view["ahead"] = ahead
    view["estimated_seconds"] = job["duration_seconds"] * SECONDS_PER_AUDIO_SECOND
    view["elapsed_seconds"] = None
    if job["status"] == "transcribing":
        started = datetime.fromisoformat(job["stage_started_at"])
        view["elapsed_seconds"] = (datetime.now(timezone.utc) - started).total_seconds()
    return view


def public_jobs(store):
    jobs = store.all()
    active = sorted((j for j in jobs if j["status"] in ACTIVE_STATUSES), key=lambda j: j["created_at"])
    position = {job["id"]: index for index, job in enumerate(active)}
    return [public_job(job, position.get(job["id"], 0)) for job in jobs]


class NotesUpdate(BaseModel):
    notes: str = Field(min_length=1, max_length=1_000_000)


def create_app(data_dir="jobs", process=default_process):
    store = JobStore(data_dir)
    worker = Worker(store, process)

    @asynccontextmanager
    async def lifespan(_app):
        # 처리 중에 서버가 꺼졌던 작업을 오래된 순서대로 다시 넣는다.
        interrupted = [job for job in store.all() if job["status"] in ACTIVE_STATUSES]
        for job in sorted(interrupted, key=lambda job: job["created_at"]):
            store.update(job["id"], status="queued")
            worker.queue.put(job["id"])
        worker.start()
        yield

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=ALLOWED_HOSTS)

    @app.middleware("http")
    async def guard(request: Request, call_next):
        # 다른 웹사이트가 브라우저를 통해 보내는 쓰기 요청을 본문을 읽기 전에 막는다.
        origin = request.headers.get("origin")
        if request.method not in READ_ONLY_METHODS and origin and urlsplit(origin).netloc != request.headers.get("host"):
            return JSONResponse({"detail": "다른 사이트에서 보낸 요청은 처리하지 않아요."}, status_code=403)
        path = request.url.path
        response = await call_next(request)
        response.headers.update(SECURITY_HEADERS)
        if path.startswith("/api/") or path == "/":
            response.headers["Cache-Control"] = "no-store"
        return response

    def get_job(job_id):
        job = store.read(job_id)
        if job is None:
            raise HTTPException(404, "회의록을 찾을 수 없어요.")
        return job

    def require_done(job):
        if job["status"] != "done":
            raise HTTPException(409, "아직 회의록이 완성되지 않았어요.")

    @app.get("/api/jobs")
    def list_jobs():
        return public_jobs(store)

    def register_upload(job_id, name, suffix, incoming):
        """올라온 파일이 오디오인지 확인하고 처리 대기열에 넣는다."""
        audio = incoming.with_name(f"audio{suffix}")
        os.replace(incoming, audio)
        duration = probe_duration(audio)
        job = {
            "id": job_id,
            "name": name,
            "title": None,
            "status": "queued",
            "created_at": now(),
            "duration_seconds": duration,
            "error": None,
            "confirmed_at": None,
        }
        store.write(job)
        worker.queue.put(job_id)
        return next(view for view in public_jobs(store) if view["id"] == job_id)

    @app.post("/api/jobs", status_code=201)
    async def create_job(request: Request):
        # 웹 화면은 양식으로 보내고, 아이폰 단축어는 파일을 본문 그대로 보낼 수 있다.
        content_type = request.headers.get("content-type", "").split(";")[0].strip().lower()
        job_id = uuid.uuid4().hex
        job_dir = store.path(job_id)
        job_dir.mkdir()
        incoming = job_dir / "upload.tmp"
        try:
            if content_type == "multipart/form-data":
                async with request.form() as form:
                    upload = next((value for value in form.values() if isinstance(value, UploadFile)), None)
                    if upload is None:
                        raise HTTPException(400, "파일이 들어 있지 않아요. 녹음 파일을 올려 주세요.")
                    name = Path(upload.filename or "녹음").name[:200]
                    suffix = Path(name).suffix.lower()
                    if suffix not in ALLOWED_SUFFIXES:
                        allowed = ", ".join(sorted(s[1:] for s in ALLOWED_SUFFIXES))
                        raise HTTPException(400, f"올릴 수 없는 파일 형식이에요. {allowed} 파일을 올려 주세요.")
                    await run_in_threadpool(copy_upload, upload.file, incoming)
            else:
                suffix = RAW_SUFFIXES.get(content_type, ".m4a")
                name = f"아이폰 녹음{suffix}"
                copied = 0
                with open(incoming, "wb") as out:
                    async for chunk in request.stream():
                        copied += len(chunk)
                        if copied > MAX_UPLOAD_BYTES:
                            raise HTTPException(413, TOO_LARGE_MESSAGE)
                        out.write(chunk)
            return await run_in_threadpool(register_upload, job_id, name, suffix, incoming)
        except Exception:
            logger.warning("업로드를 거절했다: content_type=%s", content_type)
            shutil.rmtree(job_dir)
            raise

    @app.get("/api/jobs/{job_id}")
    def read_job(job_id: str):
        get_job(job_id)
        view = next(view for view in public_jobs(store) if view["id"] == job_id)
        job_dir = store.path(job_id)
        if view["status"] == "done":
            view["notes"] = (job_dir / "notes.md").read_text(encoding="utf-8")
            view["turns"] = json.loads((job_dir / "turns.json").read_text(encoding="utf-8"))
            view["edited"] = (job_dir / "notes.draft.md").exists()
        return view

    @app.put("/api/jobs/{job_id}/notes")
    def update_notes(job_id: str, body: NotesUpdate):
        job = get_job(job_id)
        require_done(job)
        notes_path = store.path(job_id) / "notes.md"
        draft_path = store.path(job_id) / "notes.draft.md"
        if not draft_path.exists():
            shutil.copyfile(notes_path, draft_path)
        temp = notes_path.with_suffix(".tmp")
        temp.write_text(body.notes, encoding="utf-8")
        os.replace(temp, notes_path)
        store.update(job_id, title=notes_title(body.notes, job["name"]), confirmed_at=None)
        return read_job(job_id)

    @app.post("/api/jobs/{job_id}/confirm")
    def confirm(job_id: str):
        require_done(get_job(job_id))
        store.update(job_id, confirmed_at=now())
        return read_job(job_id)

    @app.post("/api/jobs/{job_id}/retry")
    def retry(job_id: str):
        job = get_job(job_id)
        if job["status"] not in ("failed", "canceled"):
            raise HTTPException(409, "실패하거나 멈춘 작업만 다시 시작할 수 있어요.")
        if worker.is_running(job_id):
            raise HTTPException(409, STILL_STOPPING_MESSAGE)
        store.update(job_id, status="queued", error=None)
        worker.queue.put(job_id)
        return read_job(job_id)

    @app.post("/api/jobs/{job_id}/cancel")
    def cancel(job_id: str):
        job = get_job(job_id)
        if job["status"] not in ACTIVE_STATUSES:
            raise HTTPException(409, "처리 중인 작업만 멈출 수 있어요.")
        worker.cancel(job_id)
        return read_job(job_id)

    @app.delete("/api/jobs/{job_id}")
    def delete_job(job_id: str):
        job = get_job(job_id)
        if job["status"] in ACTIVE_STATUSES:
            raise HTTPException(409, "처리 중인 회의록은 먼저 멈춰 주세요.")
        if worker.is_running(job_id):
            raise HTTPException(409, STILL_STOPPING_MESSAGE)
        shutil.rmtree(store.path(job_id))
        return {"ok": True}

    @app.get("/api/jobs/{job_id}/audio")
    def audio(job_id: str):
        get_job(job_id)
        return FileResponse(find_audio(store.path(job_id)))

    @app.get("/api/jobs/{job_id}/download")
    def download(job_id: str):
        job = get_job(job_id)
        require_done(job)
        safe_title = re.sub(r'[\\/:*?"<>|\r\n]', "_", job["title"] or job["name"])[:80]
        return FileResponse(
            store.path(job_id) / "notes.md", media_type="text/markdown", filename=f"회의록 {safe_title}.md"
        )

    @app.get("/")
    def index():
        return FileResponse(STATIC_DIR / "index.html")

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    return app
