"""회의 녹음을 올리면 회의록 초안을 만들어 주는 웹 서버.

실행: uv run --env-file .env uvicorn app:create_app --factory
"""

import hashlib
import hmac
import json
import logging
import os
import queue
import re
import shutil
import subprocess
import threading
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

logger = logging.getLogger("meeting_notes.app")

STATIC_DIR = Path(__file__).parent / "static"
ALLOWED_SUFFIXES = {".m4a", ".mp3", ".wav", ".flac", ".ogg", ".aac", ".mp4", ".webm"}
MAX_UPLOAD_BYTES = 1024**3
COOKIE_NAME = "session"
COOKIE_MAX_AGE = 30 * 24 * 3600
JOB_ID = re.compile(r"[0-9a-f]{32}")
ACTIVE_STATUSES = ("queued", "transcribing", "writing")

# 노트북 CPU에서 large-v3로 잰 값이다. 음성 1초를 처리하는 데 약 2.7초가 걸렸다.
SECONDS_PER_AUDIO_SECOND = 2.7

FAILURE_MESSAGES = {
    "transcribing": "음성을 글로 옮기지 못했습니다. 다시 시도하세요.",
    "writing": "회의록을 쓰지 못했습니다. 다시 시도하면 전사문은 그대로 두고 회의록만 다시 씁니다.",
}

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Content-Security-Policy": (
        "default-src 'self'; script-src 'self'; media-src 'self'; "
        "style-src 'self' https://fonts.googleapis.com; font-src https://fonts.gstatic.com; "
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
        raise HTTPException(400, "오디오를 읽을 수 없는 파일입니다. 녹음 파일을 다시 올리세요.") from error
    return duration


def notes_title(notes, fallback):
    first_line = notes.strip().splitlines()[0] if notes.strip() else ""
    title = re.sub(r"^#\s*(회의록\s*:\s*)?", "", first_line).strip() if first_line.startswith("#") else ""
    return title or fallback


def default_process(audio, out_dir, on_stage):
    from meeting_notes import load_glossary, process_audio

    glossary_path = Path("glossary.txt")
    glossary = load_glossary(glossary_path) if glossary_path.exists() else []
    return process_audio(audio, out_dir, glossary, on_stage)


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


class Worker(threading.Thread):
    """녹음을 한 번에 한 건씩 처리한다."""

    def __init__(self, store, process):
        super().__init__(daemon=True)
        self.store = store
        self.process = process
        self.queue = queue.Queue()

    def run(self):
        while True:
            self.handle(self.queue.get())

    def handle(self, job_id):
        job_dir = self.store.path(job_id)
        audio = next(job_dir.glob("audio.*"))

        def on_stage(stage):
            self.store.update(job_id, status=stage, stage_started_at=now())

        try:
            usage = self.process(audio, job_dir, on_stage)
            notes = (job_dir / "notes.md").read_text(encoding="utf-8")
            job = self.store.read(job_id)
            self.store.update(job_id, status="done", title=notes_title(notes, job["name"]), usage=usage, error=None)
        except Exception:
            logger.exception("작업 %s 처리에 실패했다", job_id)
            stage = self.store.read(job_id)["status"]
            message = FAILURE_MESSAGES.get(stage, FAILURE_MESSAGES["transcribing"])
            self.store.update(job_id, status="failed", error=message)


def public_job(job, ahead=0):
    """화면에 보낼 항목만 고르고 남은 시간을 계산한다."""
    view = {
        key: job.get(key)
        for key in ("id", "name", "title", "status", "created_at", "duration_seconds", "error", "confirmed_at")
    }
    view["ahead"] = ahead
    view["estimated_seconds"] = None
    view["elapsed_seconds"] = None
    if job["status"] == "transcribing":
        started = datetime.fromisoformat(job["stage_started_at"])
        view["estimated_seconds"] = job["duration_seconds"] * SECONDS_PER_AUDIO_SECOND
        view["elapsed_seconds"] = (datetime.now(timezone.utc) - started).total_seconds()
    return view


def public_jobs(store):
    jobs = store.all()
    active = sorted((j for j in jobs if j["status"] in ACTIVE_STATUSES), key=lambda j: j["created_at"])
    position = {job["id"]: index for index, job in enumerate(active)}
    return [public_job(job, position.get(job["id"], 0)) for job in jobs]


class Login(BaseModel):
    code: str = Field(max_length=200)


class NotesUpdate(BaseModel):
    notes: str = Field(min_length=1, max_length=1_000_000)


def create_app(data_dir="jobs", access_code=None, process=default_process):
    access_code = access_code or os.environ.get("ACCESS_CODE")
    if not access_code:
        raise RuntimeError("ACCESS_CODE 환경 변수가 필요하다. .env에 접속 코드를 넣는다.")
    session_token = hmac.new(access_code.encode(), b"meeting-notes-session", hashlib.sha256).hexdigest()

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

    @app.middleware("http")
    async def guard(request: Request, call_next):
        # 본문을 읽기 전에 막아야 하므로 의존성이 아니라 미들웨어에서 확인한다.
        path = request.url.path
        if path.startswith("/api/") and path != "/api/login":
            cookie = request.cookies.get(COOKIE_NAME, "")
            if not hmac.compare_digest(cookie.encode(), session_token.encode()):
                return JSONResponse({"detail": "접속 코드를 입력하세요."}, status_code=401)
        response = await call_next(request)
        response.headers.update(SECURITY_HEADERS)
        if path.startswith("/api/") or path == "/":
            response.headers["Cache-Control"] = "no-store"
        return response

    def get_job(job_id):
        job = store.read(job_id)
        if job is None:
            raise HTTPException(404, "회의록을 찾을 수 없습니다.")
        return job

    def require_done(job):
        if job["status"] != "done":
            raise HTTPException(409, "아직 회의록이 완성되지 않았습니다.")

    @app.post("/api/login")
    def login(body: Login, request: Request, response: Response):
        if not hmac.compare_digest(body.code.encode(), access_code.encode()):
            time.sleep(1)
            raise HTTPException(401, "접속 코드가 맞지 않습니다. 다시 입력하세요.")
        response.set_cookie(
            COOKIE_NAME,
            session_token,
            max_age=COOKIE_MAX_AGE,
            httponly=True,
            samesite="strict",
            secure=request.url.scheme == "https",
        )
        return {"ok": True}

    @app.post("/api/logout")
    def logout(response: Response):
        response.delete_cookie(COOKIE_NAME)
        return {"ok": True}

    @app.get("/api/jobs")
    def list_jobs():
        return public_jobs(store)

    @app.post("/api/jobs", status_code=201)
    def create_job(file: UploadFile = File(...)):
        name = Path(file.filename or "녹음").name[:200]
        suffix = Path(name).suffix.lower()
        if suffix not in ALLOWED_SUFFIXES:
            allowed = ", ".join(sorted(s[1:] for s in ALLOWED_SUFFIXES))
            raise HTTPException(400, f"올릴 수 없는 파일 형식입니다. {allowed} 파일을 올리세요.")
        job_id = uuid.uuid4().hex
        job_dir = store.path(job_id)
        job_dir.mkdir()
        audio = job_dir / f"audio{suffix}"
        try:
            copied = 0
            with open(audio, "wb") as out:
                while chunk := file.file.read(1024 * 1024):
                    copied += len(chunk)
                    if copied > MAX_UPLOAD_BYTES:
                        raise HTTPException(413, "파일이 너무 큽니다. 1GB 이하로 올리세요.")
                    out.write(chunk)
            duration = probe_duration(audio)
        except Exception:
            shutil.rmtree(job_dir)
            raise
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
        if job["status"] != "failed":
            raise HTTPException(409, "실패한 작업만 다시 시도할 수 있습니다.")
        store.update(job_id, status="queued", error=None)
        worker.queue.put(job_id)
        return read_job(job_id)

    @app.get("/api/jobs/{job_id}/audio")
    def audio(job_id: str):
        get_job(job_id)
        return FileResponse(next(store.path(job_id).glob("audio.*")))

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
