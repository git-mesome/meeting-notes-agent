"""앱 조립(스프링의 Application과 @Configuration에 해당). 서비스를 만들어 연결하고 라우터를 붙인다.

실행: uv run --env-file .env uvicorn meeting_notes.main:create_app --factory
"""

import json
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from meeting_notes import settings
from meeting_notes.errors import AppError
from meeting_notes.issues.service import IssueService, link_issues
from meeting_notes.jobs.service import JobService
from meeting_notes.jobs.store import JobStore
from meeting_notes.jobs.worker import Worker
from meeting_notes.memory import MemoryBook
from meeting_notes.notifications.push import PushCenter
from meeting_notes.pipeline.templates import DEFAULT_TEMPLATE
from meeting_notes.speakers.voices import VoiceBook
from meeting_notes.web import middleware, pages
from meeting_notes.web.deps import Services
from meeting_notes.web.routers import auth as auth_routes
from meeting_notes.web.routers import issues as issue_routes
from meeting_notes.web.routers import jobs as job_routes
from meeting_notes.web.routers import memory as memory_routes
from meeting_notes.web.routers import notes as notes_routes
from meeting_notes.web.routers import push as push_routes
from meeting_notes.web.routers import speakers as speaker_routes


def default_process(audio, out_dir, on_stage, on_process):
    from meeting_notes.pipeline.process import process_audio

    template = json.loads((out_dir / "meta.json").read_text(encoding="utf-8")).get("template", DEFAULT_TEMPLATE)
    # 작업 폴더는 결과 폴더 바로 아래에 있다. 사용자가 확인해 준 사실도 결과 폴더에 있다.
    facts = MemoryBook(out_dir.parent).facts()
    return process_audio(audio, out_dir, settings.current().glossary, on_stage, on_process, template, facts)


def default_answer(transcript, notes_text, question, facts=()):
    from meeting_notes.questions import answer_question

    return answer_question(transcript, notes_text, question, facts)


def default_draft(meeting, actions, space, rules):
    from meeting_notes.issues.drafting import draft_issues

    return draft_issues(meeting, actions, space, rules)


def create_app(
    data_dir="jobs",
    process=default_process,
    answer=default_answer,
    push_send=None,
    tracker="company",
    draft=default_draft,
    auth="company",
):
    """process, answer, draft는 녹음 처리와 Claude 호출을 맡는다. 테스트에서는 가짜를 넘긴다.

    tracker와 auth를 "company"로 두면 회사 폴더의 설정으로 만든다.
    """
    company = settings.current()
    tracker = company.tracker() if tracker == "company" else tracker
    auth = company.auth(data_dir) if auth == "company" else auth

    store = JobStore(data_dir)
    voices = VoiceBook(data_dir)
    memory = MemoryBook(data_dir)
    push_center = PushCenter(data_dir, send=push_send)
    worker = Worker(store, process, voices, push_center)
    job_service = JobService(store, worker, voices, answer, issue_links=link_issues(tracker), memory=memory)
    services = Services(
        jobs=job_service,
        issues=IssueService(tracker, job_service, draft),
        voices=voices,
        memory=memory,
        push=push_center,
        auth=auth,
    )

    @asynccontextmanager
    async def lifespan(_app):
        job_service.requeue_interrupted()
        worker.start()
        yield

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.services = services
    middleware.install(app, auth, company.allowed_hosts)

    @app.exception_handler(AppError)
    async def app_error(_request, error):
        return JSONResponse({"detail": error.message}, status_code=error.status)

    for routes in (job_routes, notes_routes, speaker_routes, memory_routes, issue_routes, push_routes, auth_routes, pages):
        app.include_router(routes.router)
    app.mount("/static", StaticFiles(directory=pages.STATIC_DIR), name="static")
    return app
