"""라우터 함수의 인자로 서비스를 넣어 준다(스프링의 생성자 주입에 해당).

main.create_app이 Services를 만들어 app.state에 두고, 라우터는 아래 별칭을 인자 타입으로 쓴다.
"""

from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Request

from meeting_notes.auth import OIDC
from meeting_notes.issues.service import IssueService
from meeting_notes.jobs.service import JobService
from meeting_notes.memory import MemoryBook
from meeting_notes.notifications.push import PushCenter
from meeting_notes.speakers.voices import VoiceBook


@dataclass
class Services:
    jobs: JobService
    issues: IssueService
    voices: VoiceBook
    memory: MemoryBook
    push: PushCenter
    auth: OIDC | None


def services(request: Request) -> Services:
    return request.app.state.services


def job_service(request: Request) -> JobService:
    return services(request).jobs


def issue_service(request: Request) -> IssueService:
    return services(request).issues


def voice_book(request: Request) -> VoiceBook:
    return services(request).voices


def memory_book(request: Request) -> MemoryBook:
    return services(request).memory


def push_center(request: Request) -> PushCenter:
    return services(request).push


def login(request: Request) -> OIDC | None:
    return services(request).auth


def current_user(request: Request) -> dict | None:
    """로그인한 사용자. 로그인을 켜지 않았으면 None이다(middleware.py가 채운다)."""
    return getattr(request.state, "user", None)


Jobs = Annotated[JobService, Depends(job_service)]
Issues = Annotated[IssueService, Depends(issue_service)]
Voices = Annotated[VoiceBook, Depends(voice_book)]
Memory = Annotated[MemoryBook, Depends(memory_book)]
Push = Annotated[PushCenter, Depends(push_center)]
Auth = Annotated[OIDC | None, Depends(login)]
User = Annotated[dict | None, Depends(current_user)]
