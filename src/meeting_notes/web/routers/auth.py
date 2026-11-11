"""SSO 로그인과 로그아웃, 로그인한 적 있는 사람 목록, 아이폰 단축어용 업로드 키. 로그인을 켜지 않았으면 첫 화면으로 보낸다."""

import logging

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

from meeting_notes.auth import FLOW_COOKIE, FLOW_SECONDS, SESSION_COOKIE, AuthError
from meeting_notes.errors import AppError
from meeting_notes.web.deps import Auth, Keys, User, Users
from meeting_notes.web.pages import login_page

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/api/me")
def me(auth: Auth, user: User):
    """sub는 관리자(company.toml [auth]의 admin_subs)로 적을 값을 찾을 때 쓴다."""
    return {"login": auth is not None, "name": user["name"] if user else None, "sub": user["sub"] if user else None}


@router.get("/api/users")
def users_list(users: Users, user: User):
    """회의 참석자로 고를 수 있는 사람. 로그인을 켜지 않았으면 고를 사람이 없다."""
    return users.list() if user else []


@router.get("/api/upload-key")
def upload_key(keys: Keys, user: User):
    """아이폰 단축어용 키를 받은 때. 키 원문은 받을 때 한 번만 보여 준다(auth/upload_keys.py)."""
    return {"created_at": keys.created_at(user["sub"]) if user else None}


@router.post("/api/upload-key", status_code=201)
def new_upload_key(keys: Keys, user: User):
    """새 키를 만든다. 전에 받은 키는 더 이상 쓸 수 없다."""
    if user is None:
        raise AppError("로그인을 켜지 않아 키 없이 단축어로 올릴 수 있어요.")
    return keys.issue(user)


@router.delete("/api/upload-key")
def delete_upload_key(keys: Keys, user: User):
    if user:
        keys.revoke(user["sub"])
    return {"ok": True}


@router.get("/auth/login")
def login(auth: Auth, next: str = "/"):
    if auth is None:
        return RedirectResponse("/", status_code=303)
    try:
        url, flow = auth.login(next)
    except OSError as error:
        logger.error("SSO 설정을 읽지 못했다", exc_info=error)
        return login_page("SSO에 연결하지 못했어요. 잠시 후 다시 시도해 주세요.", 502)
    response = RedirectResponse(url, status_code=303)
    response.set_cookie(FLOW_COOKIE, flow, max_age=FLOW_SECONDS, path="/auth", httponly=True, samesite="lax", secure=auth.secure)
    return response


@router.get("/auth/callback")
def login_callback(request: Request, auth: Auth, users: Users, code: str = "", state: str = "", error: str = ""):
    if auth is None:
        return RedirectResponse("/", status_code=303)
    if error or not code:
        return login_page("로그인을 마치지 못했어요.", 400)
    try:
        user, next_path = auth.finish(code, state, request.cookies.get(FLOW_COOKIE))
    except AuthError as failure:
        logger.warning("로그인 실패: %s", failure)
        return login_page(str(failure), failure.status)
    users.seen(user)
    response = RedirectResponse(next_path, status_code=303)
    response.set_cookie(
        SESSION_COOKIE,
        auth.session(user),
        max_age=auth.session_seconds,
        path="/",
        httponly=True,
        samesite="lax",
        secure=auth.secure,
    )
    response.delete_cookie(FLOW_COOKIE, path="/auth")
    return response


@router.get("/auth/logout")
def logout(auth: Auth):
    response = RedirectResponse(auth.logout_url() if auth else "/", status_code=303)
    response.delete_cookie(SESSION_COOKIE, path="/")
    return response
