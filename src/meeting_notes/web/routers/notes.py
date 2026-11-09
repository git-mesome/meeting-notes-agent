"""회의록 고치기, 확정, 다시 쓰기, 내려받기, 질문, 검색."""

from urllib.parse import quote

from fastapi import APIRouter
from fastapi.responses import Response

from meeting_notes.web.deps import Jobs
from meeting_notes.web.schemas import CheckUpdate, NotesUpdate, Question, Regenerate

router = APIRouter(prefix="/api")


@router.put("/jobs/{job_id}/notes")
def update_notes(job_id: str, body: NotesUpdate, jobs: Jobs):
    return jobs.edit_notes(job_id, body.notes)


@router.put("/jobs/{job_id}/checks/{index}")
def set_check(job_id: str, index: int, body: CheckUpdate, jobs: Jobs):
    """확인 필요 항목에 확인 표시를 한다."""
    return jobs.set_check(job_id, index, body.done)


@router.post("/jobs/{job_id}/confirm")
def confirm(job_id: str, jobs: Jobs):
    return jobs.confirm(job_id)


@router.post("/jobs/{job_id}/regenerate")
def regenerate(job_id: str, body: Regenerate, jobs: Jobs):
    return jobs.regenerate(job_id, body.template)


@router.get("/jobs/{job_id}/download")
def download(job_id: str, jobs: Jobs):
    title, notes = jobs.download(job_id)
    return Response(
        notes,
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename*=utf-8''{quote(f'회의록 {title}.md')}"},
    )


@router.get("/jobs/{job_id}/share")
def share(job_id: str, jobs: Jobs):
    """팀원과 나눌 HTML 파일로 내려받는다."""
    title, page = jobs.share(job_id)
    return Response(
        page,
        media_type="text/html; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename*=utf-8''{quote(f'회의록 {title}.html')}"},
    )


@router.post("/jobs/{job_id}/ask")
def ask(job_id: str, body: Question, jobs: Jobs):
    return jobs.ask(job_id, body.question)


@router.get("/search")
def search(jobs: Jobs, q: str = ""):
    return jobs.search(q)
