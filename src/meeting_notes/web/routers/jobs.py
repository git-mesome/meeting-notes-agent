"""회의 올리기와 녹음 더 올리기, 처리 상태, 참석자와 공개 범위, 회의 자료 붙이기."""

import logging
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile

from meeting_notes.errors import AppError, TooLarge
from meeting_notes.jobs.service import require_template
from meeting_notes.pipeline.audio import ALLOWED_SUFFIXES, MAX_RECORDINGS
from meeting_notes.pipeline.documents import MAX_DOCUMENTS_BYTES
from meeting_notes.pipeline.templates import DEFAULT_TEMPLATE, TEMPLATES
from meeting_notes.web.deps import Jobs, User, Users
from meeting_notes.web.schemas import AccessUpdate

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api")

MAX_UPLOAD_BYTES = 1024**3
TOO_LARGE_MESSAGE = "파일이 너무 커요. 한 번에 1GB 이하로 올려 주세요."
# 아이폰 단축어는 파일 이름 없이 본문으로 올린다. 내용은 ffprobe로 따로 확인한다.
RAW_SUFFIXES = {
    "audio/mpeg": ".mp3",
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
    "audio/flac": ".flac",
    "audio/ogg": ".ogg",
    "audio/aac": ".aac",
    "audio/webm": ".webm",
}


def audio_suffix(name):
    suffix = Path(name).suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        allowed = ", ".join(sorted(s[1:] for s in ALLOWED_SUFFIXES))
        raise AppError(f"올릴 수 없는 파일 형식이에요. {allowed} 파일을 올려 주세요.")
    return suffix


def copy_upload(source, target, limit=None, message=TOO_LARGE_MESSAGE):
    """받은 바이트 수를 돌려준다."""
    limit = MAX_UPLOAD_BYTES if limit is None else limit
    copied = 0
    with open(target, "wb") as out:
        while chunk := source.read(1024 * 1024):
            copied += len(chunk)
            if copied > limit:
                raise TooLarge(message)
            out.write(chunk)
    return copied


async def save_body(request, target):
    """아이폰 단축어가 파일 이름 없이 요청 본문으로 보낸 녹음을 받는다. 확장자는 Content-Type으로 정한다."""
    copied = 0
    with open(target, "wb") as out:
        async for chunk in request.stream():
            copied += len(chunk)
            if copied > MAX_UPLOAD_BYTES:
                raise TooLarge(TOO_LARGE_MESSAGE)
            out.write(chunk)
    return RAW_SUFFIXES.get(content_type(request), ".m4a")


def content_type(request):
    return request.headers.get("content-type", "").split(";")[0].strip().lower()


@router.get("/templates")
def list_templates():
    return [
        {"key": key, "label": template["label"], "description": template["description"]}
        for key, template in TEMPLATES.items()
    ]


@router.get("/jobs")
def list_jobs(jobs: Jobs):
    return jobs.list()


@router.post("/jobs", status_code=201)
async def create_job(request: Request, jobs: Jobs, user: User):
    """웹 화면은 양식으로 보내고, 아이폰 단축어는 파일을 본문 그대로 보낼 수 있다.

    양식에 녹음을 여럿 담으면 담은 순서대로 이어 회의 하나로 만든다. 1GB는 모두 합친 크기다.
    """
    template = request.query_params.get("template", DEFAULT_TEMPLATE)
    require_template(template)
    job_id, job_dir = jobs.new_job_dir()
    uploads = []
    try:
        if content_type(request) == "multipart/form-data":
            async with request.form() as form:
                files = [value for _, value in form.multi_items() if isinstance(value, UploadFile)]
                if not files:
                    raise AppError("파일이 들어 있지 않아요. 녹음 파일을 올려 주세요.")
                if len(files) > MAX_RECORDINGS:
                    raise AppError(f"녹음은 한 회의에 {MAX_RECORDINGS}개까지 올릴 수 있어요.")
                names = [Path(upload.filename or "녹음").name[:200] for upload in files]
                suffixes = [audio_suffix(name) for name in names]
                remaining = MAX_UPLOAD_BYTES
                for number, (upload, suffix) in enumerate(zip(files, suffixes), 1):
                    incoming = job_dir / f"upload-{number}.tmp"
                    remaining -= await run_in_threadpool(copy_upload, upload.file, incoming, remaining)
                    uploads.append((suffix, incoming))
                name = names[0] if len(names) == 1 else f"{names[0]} 외 {len(names) - 1}개"
        else:
            incoming = job_dir / "upload.tmp"
            suffix = await save_body(request, incoming)
            name = f"아이폰 녹음{suffix}"
            uploads.append((suffix, incoming))
        owner = {"sub": user["sub"], "name": user["name"]} if user else None
        return await run_in_threadpool(jobs.add, job_id, name, uploads, template, owner)
    except Exception:
        logger.warning("업로드를 거절했다: content_type=%s", content_type(request))
        jobs.discard(job_id)
        raise


@router.get("/jobs/{job_id}")
def read_job(job_id: str, jobs: Jobs):
    return jobs.detail(job_id)


# 아래의 {job_id}보다 먼저 둬야 latest를 회의 번호로 읽지 않는다.
@router.post("/jobs/latest/recordings")
async def add_recording_to_latest(request: Request, jobs: Jobs):
    """아이폰 '이어 올리기' 단축어. 마지막으로 올린 회의 뒤에 녹음을 붙인다."""
    return await receive_recording(request, jobs, jobs.latest_job_id())


@router.post("/jobs/{job_id}/recordings")
async def add_recording(job_id: str, request: Request, jobs: Jobs):
    """회의 끝에 녹음을 하나 더 잇는다. 새 녹음만 전사하고 회의록은 다시 쓴다. 처리하는 중이면 끝난 뒤 이어서 처리한다."""
    return await receive_recording(request, jobs, job_id)


async def receive_recording(request, jobs, job_id):
    """웹 화면은 양식으로, 아이폰 단축어는 요청 본문 그대로 보낸다."""
    incoming = jobs.recording_upload_path(job_id)
    try:
        if content_type(request) == "multipart/form-data":
            async with request.form() as form:
                upload = next((value for value in form.values() if isinstance(value, UploadFile)), None)
                if upload is None:
                    raise AppError("파일이 들어 있지 않아요. 녹음 파일을 올려 주세요.")
                suffix = audio_suffix(Path(upload.filename or "녹음").name)
                await run_in_threadpool(copy_upload, upload.file, incoming)
        else:
            suffix = await save_body(request, incoming)
        return await run_in_threadpool(jobs.add_recording, job_id, suffix, incoming)
    finally:
        incoming.unlink(missing_ok=True)


@router.post("/jobs/{job_id}/retry")
def retry(job_id: str, jobs: Jobs):
    return jobs.retry(job_id)


@router.post("/jobs/{job_id}/cancel")
def cancel(job_id: str, jobs: Jobs):
    return jobs.cancel(job_id)


@router.delete("/jobs/{job_id}")
def delete_job(job_id: str, jobs: Jobs):
    jobs.delete(job_id)
    return {"ok": True}


@router.put("/jobs/{job_id}/access")
def set_access(job_id: str, body: AccessUpdate, jobs: Jobs, users: Users):
    """참석자는 회의록을 고칠 수 있고, "참석자만 보기"를 켜면 다른 사람에게는 보이지 않는다(jobs/access.py)."""
    return jobs.set_access(job_id, body.attendees, body.private, users)


@router.get("/jobs/{job_id}/audio")
def audio(job_id: str, jobs: Jobs):
    return FileResponse(jobs.audio_path(job_id))


# 회의 자료


@router.post("/jobs/{job_id}/documents")
async def add_document(job_id: str, request: Request, jobs: Jobs):
    """회의에서 함께 본 자료를 하나 붙인다. 회의록을 쓰기 전이면 회의록을 쓸 때 함께 본다."""
    incoming = jobs.document_upload_path(job_id)
    try:
        async with request.form() as form:
            upload = next((value for value in form.values() if isinstance(value, UploadFile)), None)
            if upload is None:
                raise AppError("파일이 들어 있지 않아요. 자료 파일을 올려 주세요.")
            name = Path(upload.filename or "자료").name[:200]
            message = f"자료는 한 회의에 모두 합쳐 {MAX_DOCUMENTS_BYTES // 1024**2}MB까지 붙일 수 있어요."
            await run_in_threadpool(copy_upload, upload.file, incoming, MAX_DOCUMENTS_BYTES, message)
        return await run_in_threadpool(jobs.add_document, job_id, name, incoming)
    finally:
        incoming.unlink(missing_ok=True)


@router.get("/jobs/{job_id}/documents/{name}")
def read_document(job_id: str, name: str, jobs: Jobs):
    """내려받기로만 준다. 올라온 HTML이 이 사이트 안에서 열리면 그 안의 스크립트가 실행된다."""
    path = jobs.document_path(job_id, name)
    return FileResponse(path, filename=path.name, media_type="application/octet-stream")


@router.delete("/jobs/{job_id}/documents/{name}")
def delete_document(job_id: str, name: str, jobs: Jobs):
    return jobs.delete_document(job_id, name)
