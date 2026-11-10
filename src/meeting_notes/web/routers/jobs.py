"""회의 올리기와 처리 상태, 회의 자료 붙이기."""

import logging
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile

from meeting_notes.errors import AppError, TooLarge
from meeting_notes.jobs.service import require_template
from meeting_notes.pipeline.audio import ALLOWED_SUFFIXES
from meeting_notes.pipeline.documents import MAX_DOCUMENTS_BYTES
from meeting_notes.pipeline.templates import DEFAULT_TEMPLATE, TEMPLATES
from meeting_notes.web.deps import Jobs, User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api")

MAX_UPLOAD_BYTES = 1024**3
TOO_LARGE_MESSAGE = "파일이 너무 커요. 1GB 이하로 올려 주세요."
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


def copy_upload(source, target, limit=None, message=TOO_LARGE_MESSAGE):
    limit = limit or MAX_UPLOAD_BYTES
    copied = 0
    with open(target, "wb") as out:
        while chunk := source.read(1024 * 1024):
            copied += len(chunk)
            if copied > limit:
                raise TooLarge(message)
            out.write(chunk)


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
    # 웹 화면은 양식으로 보내고, 아이폰 단축어는 파일을 본문 그대로 보낼 수 있다.
    content_type = request.headers.get("content-type", "").split(";")[0].strip().lower()
    template = request.query_params.get("template", DEFAULT_TEMPLATE)
    require_template(template)
    job_id, job_dir = jobs.new_job_dir()
    incoming = job_dir / "upload.tmp"
    try:
        if content_type == "multipart/form-data":
            async with request.form() as form:
                upload = next((value for value in form.values() if isinstance(value, UploadFile)), None)
                if upload is None:
                    raise AppError("파일이 들어 있지 않아요. 녹음 파일을 올려 주세요.")
                name = Path(upload.filename or "녹음").name[:200]
                suffix = Path(name).suffix.lower()
                if suffix not in ALLOWED_SUFFIXES:
                    allowed = ", ".join(sorted(s[1:] for s in ALLOWED_SUFFIXES))
                    raise AppError(f"올릴 수 없는 파일 형식이에요. {allowed} 파일을 올려 주세요.")
                await run_in_threadpool(copy_upload, upload.file, incoming)
        else:
            suffix = RAW_SUFFIXES.get(content_type, ".m4a")
            name = f"아이폰 녹음{suffix}"
            copied = 0
            with open(incoming, "wb") as out:
                async for chunk in request.stream():
                    copied += len(chunk)
                    if copied > MAX_UPLOAD_BYTES:
                        raise TooLarge(TOO_LARGE_MESSAGE)
                    out.write(chunk)
        owner = {"sub": user["sub"], "name": user["name"]} if user else None
        return await run_in_threadpool(jobs.add, job_id, name, suffix, incoming, template, owner)
    except Exception:
        logger.warning("업로드를 거절했다: content_type=%s", content_type)
        jobs.discard(job_id)
        raise


@router.get("/jobs/{job_id}")
def read_job(job_id: str, jobs: Jobs):
    return jobs.detail(job_id)


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
