"""모든 요청에 거는 검사(스프링의 Filter에 해당)."""

from urllib.parse import quote, urlsplit

from fastapi import Request
from fastapi.responses import JSONResponse, RedirectResponse
from starlette.middleware.trustedhost import TrustedHostMiddleware

from meeting_notes.auth import SESSION_COOKIE

READ_ONLY_METHODS = {"GET", "HEAD", "OPTIONS"}
# 로그인하지 않아도 열리는 경로. 화면 파일과 로그인 과정만 연다.
PUBLIC_PREFIXES = ("/auth/", "/static/")

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


def is_public(path):
    return path.startswith(PUBLIC_PREFIXES) or path == "/sw.js"


def install(app, auth, allowed_hosts):
    """허용한 Host만 받고, 다른 사이트의 쓰기 요청과 로그인하지 않은 요청을 막고, 보안 헤더를 붙인다."""
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=allowed_hosts)

    @app.middleware("http")
    async def guard(request: Request, call_next):
        # 다른 웹사이트가 브라우저를 통해 보내는 쓰기 요청을 본문을 읽기 전에 막는다.
        origin = request.headers.get("origin")
        if request.method not in READ_ONLY_METHODS and origin and urlsplit(origin).netloc != request.headers.get("host"):
            return JSONResponse({"detail": "다른 사이트에서 보낸 요청은 처리하지 않아요."}, status_code=403)
        path = request.url.path
        user = auth.user(request.cookies.get(SESSION_COOKIE)) if auth else None
        if auth and user is None and not is_public(path):
            if path.startswith("/api/"):
                response = JSONResponse({"detail": "로그인이 필요해요."}, status_code=401)
            else:
                response = RedirectResponse(f"/auth/login?next={quote(path)}", status_code=303)
        else:
            request.state.user = user
            response = await call_next(request)
        response.headers.update(SECURITY_HEADERS)
        if path.startswith("/api/") or path == "/":
            response.headers["Cache-Control"] = "no-store"
        elif path.startswith("/static/") or path == "/sw.js":
            # 홈 화면 앱이 서버를 고친 뒤에도 예전 화면을 쓰지 않도록 매번 바뀌었는지 확인하게 한다.
            response.headers["Cache-Control"] = "no-cache"
        return response
