"""회의 녹음을 올리면 회의록 초안을 만들어 주는 웹 서버.

실행: uv run --env-file .env uvicorn app:create_app --factory
"""

import hashlib
import json
import logging
import os
import queue
import re
import shutil
import subprocess
import threading
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote, urlsplit

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile
from starlette.middleware.trustedhost import TrustedHostMiddleware

import company
from note_templates import DEFAULT_TEMPLATE, TEMPLATES
from push import PushCenter
from trackers import TrackerError
from voices import VoiceBook, write_private

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
READ_ONLY_METHODS = {"GET", "HEAD", "OPTIONS"}
JOB_ID = re.compile(r"[0-9a-f]{32}")
SPEAKER_LABEL = re.compile(r"SPEAKER_\d+")
# 회의록 마크다운에 그대로 들어가므로 표와 강조, 시각 표시에 쓰는 기호를 막는다.
FORBIDDEN_NAME_CHARS = re.compile(r"[|*\[\]]")
ACTIVE_STATUSES = ("queued", "transcribing", "writing")

# 노트북 CPU에서 large-v3로 잰 값이다. 음성 1초를 처리하는 데 2.2~2.7초가 걸렸다.
SECONDS_PER_AUDIO_SECOND = 2.5
ISSUE_SUMMARY_CHARS = 400
DRAFTS_FILE = "issue_drafts.json"
MAX_DESCRIBED_ISSUES = 60

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
    from meeting_notes import process_audio

    glossary = company.current().glossary
    template = json.loads((out_dir / "meta.json").read_text(encoding="utf-8")).get("template", DEFAULT_TEMPLATE)
    return process_audio(audio, out_dir, glossary, on_stage, on_process, template)


def default_draft(meeting, actions, space, rules):
    from meeting_notes import draft_issues

    return draft_issues(meeting, actions, space, rules)


def issue_summaries(tracker, issues):
    """열린 이슈마다 설명 앞부분을 가져온다. 제목만으로는 회의의 할 일과 같은 일인지 알기 어렵다."""

    def summary(issue):
        try:
            detail = tracker.issue(issue["key"])
        except (TrackerError, OSError):
            return ""
        description = detail.get("description") if isinstance(detail, dict) else ""
        return (description or "")[:ISSUE_SUMMARY_CHARS]

    with ThreadPoolExecutor(max_workers=8) as pool:
        found = list(pool.map(summary, issues[:MAX_DESCRIBED_ISSUES]))
    return found + [""] * (len(issues) - len(found))


def action_items(notes):
    """회의록의 액션 아이템 표를 행 목록으로 읽는다."""
    section = re.search(r"^## 액션 아이템\s*$(.*?)(?=^## |\Z)", notes, re.M | re.S)
    if not section:
        return []
    rows = []
    for line in section.group(1).splitlines():
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if not line.strip().startswith("|") or len(cells) < 2 or cells[0] == "담당" or set("".join(cells)) <= set("-: "):
            continue
        cells += [""] * (4 - len(cells))
        rows.append({"index": len(rows), "owner": cells[0], "task": cells[1], "due": cells[2], "evidence": cells[3]})
    return rows


def default_answer(transcript, notes, question):
    from meeting_notes import answer_question

    return answer_question(transcript, notes, question)


def extract_embeddings(job_dir):
    """전사 결과에서 화자별 목소리 특징을 꺼내 따로 저장한다."""
    transcript_json = job_dir / "audio.json"
    if not transcript_json.exists():
        return {}
    embeddings = json.loads(transcript_json.read_text(encoding="utf-8")).get("speaker_embeddings") or {}
    if embeddings:
        write_private(job_dir / "speaker_embeddings.json", json.dumps(embeddings))
    return embeddings


def load_embeddings(job_dir):
    path = job_dir / "speaker_embeddings.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


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


def speaker_list(turns, custom_names, auto_speakers=None, voiced=()):
    """말한 시간이 긴 순서로 화자를 정리한다. 이름을 정하지 않은 화자는 "화자 N"으로 부른다."""
    totals = {}
    for turn in turns:
        totals[turn["speaker"]] = totals.get(turn["speaker"], 0) + turn["end"] - turn["start"]
    total = sum(totals.values()) or 1
    speakers = []
    rank = 0
    for label, seconds in sorted(totals.items(), key=lambda item: item[1], reverse=True):
        known = label != "UNKNOWN"
        rank += known
        default_name = f"화자 {rank}" if known else "알 수 없음"
        custom = custom_names.get(label)
        speakers.append(
            {
                "label": label,
                "name": custom or default_name,
                "default_name": default_name,
                "custom": bool(custom),
                "auto": label in (auto_speakers or {}),
                "has_voice": label in voiced,
                "known": known,
                "share": round(seconds / total * 100),
                "color": (rank - 1) % 6 if known else 0,
            }
        )
    return speakers


def apply_speaker_names(text, speakers):
    names = {speaker["label"]: speaker["name"] for speaker in speakers}
    return SPEAKER_LABEL.sub(lambda match: names.get(match.group(), match.group()), text)


def public_jobs(store):
    jobs = store.all()
    active = sorted((j for j in jobs if j["status"] in ACTIVE_STATUSES), key=lambda j: j["created_at"])
    position = {job["id"]: index for index, job in enumerate(active)}
    return [public_job(job, position.get(job["id"], 0)) for job in jobs]


def plain_text(markdown):
    """검색 결과에 보여 주려고 마크다운 기호와 근거 시각을 뺀다."""
    return re.sub(r"\[\d{1,2}:\d{2}(?::\d{2})?\]|[#|*]+|^\s*-+\s*$", " ", markdown, flags=re.M)


def search_pattern(query):
    """전사문은 띄어쓰기가 불규칙하므로 공백을 무시하고 찾는다."""
    letters = [re.escape(char) for char in query if not char.isspace()]
    return re.compile(r"\s*".join(letters), re.IGNORECASE) if letters else None


def snippet(text, match, around=40):
    start = max(0, match.start() - around)
    end = min(len(text), match.end() + around)
    body = " ".join(text[start:end].split())
    return f"{'…' if start else ''}{body}{'…' if end < len(text) else ''}"


class NotesUpdate(BaseModel):
    notes: str = Field(min_length=1, max_length=1_000_000)


class SpeakerName(BaseModel):
    name: str = Field(max_length=20)
    remember: bool = False


class Question(BaseModel):
    question: str = Field(min_length=1, max_length=500)


class Regenerate(BaseModel):
    template: str


class IssueDraft(BaseModel):
    source: int
    title: str = Field(min_length=2, max_length=200)
    description: str = Field(min_length=1, max_length=20_000)
    category: str = Field(default="", max_length=40)
    priority: str = Field(default="", max_length=40)
    assignees: list[str] = Field(default_factory=list, max_length=20)
    tags: list[str] = Field(default_factory=list, max_length=8)
    parent: str = Field(default="", max_length=40)
    due_date: str = Field(default="", pattern=r"^(\d{4}-\d{2}-\d{2})?$")


class IssueComment(BaseModel):
    source: int
    key: str = Field(pattern=r"^[A-Za-z0-9#._-]{1,40}$")
    text: str = Field(min_length=1, max_length=10_000)


class IssueRegistration(BaseModel):
    create: list[IssueDraft] = Field(default_factory=list, max_length=20)
    comments: list[IssueComment] = Field(default_factory=list, max_length=20)


class PushKeys(BaseModel):
    p256dh: str = Field(max_length=300)
    auth: str = Field(max_length=100)


class PushSubscription(BaseModel):
    endpoint: str = Field(max_length=1000, pattern=r"^https://")
    keys: PushKeys


class PushEndpoint(BaseModel):
    endpoint: str = Field(max_length=1000)


def create_app(
    data_dir="jobs", process=default_process, answer=default_answer, push_send=None, tracker="company", draft=default_draft
):
    # 이슈 트래커는 회사 폴더의 어댑터로 만든다. 테스트에서는 객체를 직접 넘긴다.
    tracker = company.current().tracker() if tracker == "company" else tracker
    store = JobStore(data_dir)
    voices = VoiceBook(data_dir)
    push = PushCenter(data_dir, send=push_send)
    worker = Worker(store, process, voices, push)

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
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=company.current().allowed_hosts)

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
        elif path.startswith("/static/") or path == "/sw.js":
            # 홈 화면 앱이 서버를 고친 뒤에도 예전 화면을 쓰지 않도록 매번 바뀌었는지 확인하게 한다.
            response.headers["Cache-Control"] = "no-cache"
        return response

    def get_job(job_id):
        job = store.read(job_id)
        if job is None:
            raise HTTPException(404, "회의록을 찾을 수 없어요.")
        return job

    def load_turns(job_id):
        return json.loads((store.path(job_id) / "turns.json").read_text(encoding="utf-8"))

    def require_done(job):
        if job["status"] != "done":
            raise HTTPException(409, "아직 회의록이 완성되지 않았어요.")

    def job_speakers(job, turns=None):
        turns = load_turns(job["id"]) if turns is None else turns
        voiced = load_embeddings(store.path(job["id"]))
        return speaker_list(turns, job.get("speaker_names") or {}, job.get("auto_speakers"), voiced)

    def load_questions(job_id):
        path = store.path(job_id) / "questions.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else []

    def require_template(template):
        if template not in TEMPLATES:
            raise HTTPException(400, "없는 양식이에요.")

    @app.get("/api/templates")
    def list_templates():
        return [
            {"key": key, "label": template["label"], "description": template["description"]}
            for key, template in TEMPLATES.items()
        ]

    @app.get("/api/search")
    def search(q: str = ""):
        pattern = search_pattern(q[:100])
        if pattern is None:
            return []
        results = []
        for job in store.all():
            if job["status"] != "done":
                continue
            turns = load_turns(job["id"])
            speakers = job_speakers(job, turns)
            names = {speaker["label"]: speaker["name"] for speaker in speakers}
            title = apply_speaker_names(job.get("title") or job["name"], speakers)
            notes = plain_text(apply_speaker_names((store.path(job["id"]) / "notes.md").read_text(encoding="utf-8"), speakers))
            hits = [
                {"start": turn["start"], "speaker": names.get(turn["speaker"], ""), "text": snippet(turn["text"], found)}
                for turn in turns
                if (found := pattern.search(turn["text"]))
            ]
            in_notes = pattern.search(notes)
            if not (hits or in_notes or pattern.search(title)):
                continue
            results.append(
                {
                    "id": job["id"],
                    "title": title,
                    "created_at": job["created_at"],
                    "duration_seconds": job["duration_seconds"],
                    "notes": snippet(notes, in_notes) if in_notes else None,
                    "hits": hits[:3],
                    "hit_count": len(hits),
                }
            )
        return results

    def require_tracker():
        if tracker is None:
            raise HTTPException(409, "이슈 트래커가 설정되어 있지 않아요.")

    def with_urls(items):
        return [{**item, "url": tracker.issue_url(item["key"]) if tracker else ""} for item in items]

    @app.get("/api/tracker")
    def tracker_status():
        if tracker is None:
            return {"enabled": False}
        return {
            "enabled": True,
            "name": tracker.name,
            "destination": tracker.destination,
            "after_register": tracker.after_register,
        }

    drafting = {}
    drafting_lock = threading.Lock()

    def make_drafts(job, notes, actions):
        try:
            people, tags, issues = tracker.people(), tracker.tags(), tracker.open_issues()
        except (TrackerError, OSError) as error:
            logger.error("이슈 트래커 조회에 실패했다", exc_info=error)
            raise HTTPException(502, f"{tracker.name}에 연결하지 못했어요. 잠시 후 다시 시도해 주세요.") from error
        epics = [{"key": issue["key"], "title": issue["title"]} for issue in issues if issue.get("type") == "epic"]
        summaries = issue_summaries(tracker, issues)
        space = {
            "people": people,
            "tags": tags,
            "epics": epics,
            "open_issues": [
                {**{key: issue.get(key) for key in ("key", "title", "type", "status", "tags", "assignees")}, "summary": summary}
                for issue, summary in zip(issues, summaries)
            ],
        }
        rules = {"categories": tracker.categories, "priorities": tracker.priorities, "guide": tracker.guide}
        meeting = {"title": job.get("title") or job["name"], "date": job["created_at"][:10], "notes": notes}
        try:
            drafts = draft(meeting, actions, space, rules)
        except Exception as error:
            logger.error("작업 %s 이슈 초안 생성에 실패했다", job["id"], exc_info=error)
            raise HTTPException(502, "이슈 초안을 만들지 못했어요. 잠시 후 다시 시도해 주세요.") from error
        known = {issue["key"]: issue["title"] for issue in issues}
        for item in drafts:
            item["tags"] = [tag for tag in item["tags"] if tag in tags]
            item["assignees"] = [person for person in item["assignees"] if person in people]
            item["parent"] = item["parent"] if item["parent"] in known else ""
            item["category"] = item.get("category") if item.get("category") in tracker.categories else ""
            item["priority"] = item.get("priority") if item.get("priority") in tracker.priorities else ""
            if item["action"] == "comment" and item["existing_key"] not in known:
                item["action"] = "create"
            item["existing_title"] = known.get(item["existing_key"], "")
        return {
            "actions": actions,
            "drafts": drafts,
            "people": people,
            "tags": tags,
            "epics": epics,
            "issues": [{"key": issue["key"], "title": issue["title"]} for issue in issues],
        }

    @app.post("/api/jobs/{job_id}/issues/drafts")
    def issue_drafts(job_id: str, refresh: bool = False):
        job = get_job(job_id)
        require_done(job)
        require_tracker()
        speakers = job_speakers(job)
        notes = apply_speaker_names((store.path(job_id) / "notes.md").read_text(encoding="utf-8"), speakers)
        actions = action_items(notes)
        if not actions:
            raise HTTPException(400, "회의록에 등록할 할 일이 없어요.")
        # 만든 초안은 저장해 두고, 회의록이나 화자 이름이 바뀌었을 때만 새로 만든다.
        fingerprint = hashlib.sha256(notes.encode()).hexdigest()
        cache = store.path(job_id) / DRAFTS_FILE
        try:
            saved = json.loads(cache.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            saved = None
        if refresh or not saved or saved.get("fingerprint") != fingerprint:
            # 창을 닫았다 다시 열어도 초안을 두 번 만들지 않도록, 만드는 중이면 그 결과를 함께 기다린다.
            with drafting_lock:
                future = drafting.get(job_id)
                owner = future is None
                if owner:
                    future = drafting[job_id] = Future()
            if owner:
                try:
                    saved = {"fingerprint": fingerprint, "drafted_at": now(), **make_drafts(job, notes, actions)}
                    cache.write_text(json.dumps(saved, ensure_ascii=False), encoding="utf-8")
                    future.set_result(saved)
                except BaseException as error:
                    future.set_exception(error)
                finally:
                    with drafting_lock:
                        drafting.pop(job_id, None)
            saved = future.result()
        body = {key: value for key, value in saved.items() if key != "fingerprint"}
        return {**body, "registered": with_urls(job.get("issues") or [])}

    @app.post("/api/jobs/{job_id}/issues")
    def register_issues(job_id: str, body: IssueRegistration):
        job = get_job(job_id)
        require_done(job)
        require_tracker()
        if not body.create and not body.comments:
            raise HTTPException(400, "등록할 항목을 골라 주세요.")
        for item in body.create:
            if item.category not in (tracker.categories or [""]) or item.priority not in (tracker.priorities or [""]):
                raise HTTPException(422, "분류나 우선순위가 이 트래커에 없는 값이에요.")
        results = []
        try:
            if body.create:
                payload = []
                for item in body.create:
                    issue = item.model_dump(exclude={"source"})
                    payload.append({key: value for key, value in issue.items() if value not in ("", [])})
                keys = tracker.create(payload)
                if len(keys) != len(payload):
                    logger.warning("작업 %s: 이슈 %d건을 등록했는데 키는 %d개만 받았다", job_id, len(payload), len(keys))
                for item, key in zip(body.create, keys):
                    results.append({"source": item.source, "kind": "create", "key": key, "title": item.title})
            for comment in body.comments:
                tracker.comment(comment.key, comment.text)
                results.append({"source": comment.source, "kind": "comment", "key": comment.key, "title": ""})
        except (TrackerError, OSError) as error:
            logger.error("작업 %s 이슈 등록에 실패했다", job_id, exc_info=error)
            if not results:
                raise HTTPException(502, f"{tracker.name}에 등록하지 못했어요: {error}") from error
            store.update(job_id, issues=(job.get("issues") or []) + [{**r, "at": now()} for r in results])
            raise HTTPException(
                502,
                f"{len(results)}건은 등록했지만 나머지는 등록하지 못했어요: {error}. "
                f"{tracker.name}에서 확인한 뒤 다시 시도해 주세요.",
            ) from error
        registered = (job.get("issues") or []) + [{**result, "at": now()} for result in results]
        store.update(job_id, issues=registered)
        return {"results": with_urls(results), "registered": with_urls(registered)}

    @app.get("/api/voices")
    def list_voices():
        return voices.list()

    @app.delete("/api/voices/{voice_id}")
    def delete_voice(voice_id: str):
        if not voices.delete(voice_id):
            raise HTTPException(404, "등록된 목소리를 찾을 수 없어요.")
        return {"ok": True}

    @app.get("/api/push/key")
    def push_key():
        return {"key": push.public_key()}

    @app.post("/api/push/subscribe")
    def push_subscribe(body: PushSubscription):
        push.subscribe(body.model_dump())
        return {"ok": True}

    @app.post("/api/push/unsubscribe")
    def push_unsubscribe(body: PushEndpoint):
        push.unsubscribe(body.endpoint)
        return {"ok": True}

    @app.get("/api/jobs")
    def list_jobs():
        return public_jobs(store)

    def register_upload(job_id, name, suffix, incoming, template):
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
            "template": template,
        }
        store.write(job)
        worker.queue.put(job_id)
        return next(view for view in public_jobs(store) if view["id"] == job_id)

    @app.post("/api/jobs", status_code=201)
    async def create_job(request: Request):
        # 웹 화면은 양식으로 보내고, 아이폰 단축어는 파일을 본문 그대로 보낼 수 있다.
        content_type = request.headers.get("content-type", "").split(";")[0].strip().lower()
        template = request.query_params.get("template", DEFAULT_TEMPLATE)
        require_template(template)
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
            return await run_in_threadpool(register_upload, job_id, name, suffix, incoming, template)
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
            # 목록을 읽기 전에 읽은 상태를 쓰면, 그 사이에 끝난 작업의 화자 이름이 빠진다.
            job = get_job(job_id)
            view["notes"] = (job_dir / "notes.md").read_text(encoding="utf-8")
            view["turns"] = load_turns(job_id)
            view["speakers"] = job_speakers(job, view["turns"])
            view["edited"] = (job_dir / "notes.draft.md").exists()
            view["template"] = job.get("template", DEFAULT_TEMPLATE)
            view["questions"] = load_questions(job_id)
            view["issues"] = with_urls(job.get("issues") or [])
        return view

    @app.put("/api/jobs/{job_id}/notes")
    def update_notes(job_id: str, body: NotesUpdate):
        from meeting_notes import fix_spelling

        job = get_job(job_id)
        require_done(job)
        body.notes = fix_spelling(body.notes)
        notes_path = store.path(job_id) / "notes.md"
        draft_path = store.path(job_id) / "notes.draft.md"
        if not draft_path.exists():
            shutil.copyfile(notes_path, draft_path)
        temp = notes_path.with_suffix(".tmp")
        temp.write_text(body.notes, encoding="utf-8")
        os.replace(temp, notes_path)
        store.update(job_id, title=notes_title(body.notes, job["name"]), confirmed_at=None)
        return read_job(job_id)

    @app.put("/api/jobs/{job_id}/speakers/{label}")
    def rename_speaker(job_id: str, label: str, body: SpeakerName):
        job = get_job(job_id)
        require_done(job)
        if not SPEAKER_LABEL.fullmatch(label) or all(turn["speaker"] != label for turn in load_turns(job_id)):
            raise HTTPException(404, "화자를 찾을 수 없어요.")
        name = " ".join(body.name.split())
        if FORBIDDEN_NAME_CHARS.search(name):
            raise HTTPException(400, "이름에 | * [ ] 기호는 쓸 수 없어요.")
        if body.remember and name:
            embedding = load_embeddings(store.path(job_id)).get(label)
            if embedding is None:
                raise HTTPException(409, "이 회의에는 목소리 정보가 없어요. 새로 올린 녹음부터 등록할 수 있어요.")
            voices.register(name, embedding)
        names = dict(job.get("speaker_names") or {})
        if name:
            names[label] = name
        else:
            names.pop(label, None)
        auto = {key: value for key, value in (job.get("auto_speakers") or {}).items() if key != label}
        store.update(job_id, speaker_names=names, auto_speakers=auto, confirmed_at=None)
        return read_job(job_id)

    @app.post("/api/jobs/{job_id}/ask")
    def ask(job_id: str, body: Question):
        job = get_job(job_id)
        require_done(job)
        from meeting_notes import format_transcript

        turns = load_turns(job_id)
        speakers = job_speakers(job, turns)
        transcript = apply_speaker_names(format_transcript(turns), speakers)
        notes = apply_speaker_names((store.path(job_id) / "notes.md").read_text(encoding="utf-8"), speakers)
        question = body.question.strip()
        try:
            text = answer(transcript, notes, question)
        except Exception as error:
            logger.error("작업 %s 질문에 답하지 못했다", job_id, exc_info=error)
            raise HTTPException(502, "답을 받지 못했어요. 잠시 후 다시 시도해 주세요.") from error
        item = {"question": question, "answer": text, "asked_at": now()}
        questions = load_questions(job_id) + [item]
        (store.path(job_id) / "questions.json").write_text(json.dumps(questions, ensure_ascii=False), encoding="utf-8")
        return item

    @app.post("/api/jobs/{job_id}/regenerate")
    def regenerate(job_id: str, body: Regenerate):
        job = get_job(job_id)
        require_done(job)
        require_template(body.template)
        if worker.is_running(job_id):
            raise HTTPException(409, STILL_STOPPING_MESSAGE)
        job_dir = store.path(job_id)
        shutil.copyfile(job_dir / "notes.md", job_dir / "notes.previous.md")
        (job_dir / "notes.draft.md").unlink(missing_ok=True)
        store.update(job_id, status="queued", template=body.template, confirmed_at=None, error=None)
        worker.queue.put(job_id)
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
        speakers = job_speakers(job)
        notes = (store.path(job_id) / "notes.md").read_text(encoding="utf-8")
        title = apply_speaker_names(job["title"] or job["name"], speakers)
        safe_title = re.sub(r'[\\/:*?"<>|\r\n]', "_", title)[:80]
        return Response(
            apply_speaker_names(notes, speakers),
            media_type="text/markdown; charset=utf-8",
            headers={"Content-Disposition": f"attachment; filename*=utf-8''{quote(f'회의록 {safe_title}.md')}"},
        )

    @app.get("/sw.js")
    def service_worker():
        # 서비스 워커는 범위를 넓게 쓰기 위해 최상위 경로에서 내보낸다.
        return FileResponse(STATIC_DIR / "sw.js", media_type="text/javascript", headers={"Cache-Control": "no-cache"})

    @app.get("/")
    def index():
        # 파일 내용이 바뀌면 주소도 바뀌게 해서, 브라우저가 저장해 둔 예전 화면 코드를 쓰지 않게 한다.
        html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
        for name in ("style.css", "app.js"):
            version = hashlib.sha256((STATIC_DIR / name).read_bytes()).hexdigest()[:12]
            html = html.replace(f'"/static/{name}"', f'"/static/{name}?v={version}"')
        return HTMLResponse(html)

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    return app
