"""액션 아이템을 이슈 트래커에 등록. 회의록을 고칠 수 있는 사람만 한다(jobs/access.py)."""

from fastapi import APIRouter

from meeting_notes.jobs.access import EDIT
from meeting_notes.web.deps import Issues, Jobs
from meeting_notes.web.schemas import IssueRegistration

router = APIRouter(prefix="/api")


@router.get("/tracker")
def tracker_status(issues: Issues):
    return issues.status()


@router.post("/jobs/{job_id}/issues/drafts")
def issue_drafts(job_id: str, issues: Issues, jobs: Jobs, refresh: bool = False):
    jobs.get(job_id, EDIT)
    return issues.drafts(job_id, refresh)


@router.post("/jobs/{job_id}/issues")
def register_issues(job_id: str, body: IssueRegistration, issues: Issues, jobs: Jobs):
    jobs.get(job_id, EDIT)
    create = [item.model_dump() for item in body.create]
    comments = [item.model_dump() for item in body.comments]
    return issues.register(job_id, create, comments)
