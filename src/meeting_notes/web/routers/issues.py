"""액션 아이템을 이슈 트래커에 등록."""

from fastapi import APIRouter

from meeting_notes.web.deps import Issues
from meeting_notes.web.schemas import IssueRegistration

router = APIRouter(prefix="/api")


@router.get("/tracker")
def tracker_status(issues: Issues):
    return issues.status()


@router.post("/jobs/{job_id}/issues/drafts")
def issue_drafts(job_id: str, issues: Issues, refresh: bool = False):
    return issues.drafts(job_id, refresh)


@router.post("/jobs/{job_id}/issues")
def register_issues(job_id: str, body: IssueRegistration, issues: Issues):
    create = [item.model_dump() for item in body.create]
    comments = [item.model_dump() for item in body.comments]
    return issues.register(job_id, create, comments)
