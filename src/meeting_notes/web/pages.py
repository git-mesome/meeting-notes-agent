"""화면 진입점(index.html)과 서비스 워커, 로그인 안내 페이지."""

import hashlib
import html
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse, HTMLResponse

STATIC_DIR = Path(__file__).parent / "static"
# index.html에 적은 순서대로 읽는다. responsive.css는 다른 규칙을 덮어쓰므로 마지막이어야 한다.
STYLESHEETS = ["base", "list", "detail", "waiting", "issues", "responsive"]

router = APIRouter()


def static_version(names):
    """화면 파일 내용이 바뀌면 주소도 바뀌게 해서, 브라우저가 저장해 둔 예전 화면 코드를 쓰지 않게 한다."""
    digest = hashlib.sha256()
    for name in names:
        digest.update((STATIC_DIR / name).read_bytes())
    return digest.hexdigest()[:12]


@router.get("/")
def index():
    page = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    scripts = sorted(f"js/{path.name}" for path in (STATIC_DIR / "js").glob("*.js"))
    styles = [f"css/{name}.css" for name in STYLESHEETS]
    style_version = static_version(styles)
    for name in styles:
        page = page.replace(f'"/static/{name}"', f'"/static/{name}?v={style_version}"')
    # 시작 모듈 주소에 모든 화면 모듈의 버전을 붙인다. 나머지 모듈은 응답마다 바뀌었는지 확인한다(no-cache).
    page = page.replace('"/static/js/main.js"', f'"/static/js/main.js?v={static_version(scripts)}"')
    return HTMLResponse(page)


@router.get("/sw.js")
def service_worker():
    # 서비스 워커는 범위를 넓게 쓰기 위해 최상위 경로에서 내보낸다.
    return FileResponse(STATIC_DIR / "sw.js", media_type="text/javascript", headers={"Cache-Control": "no-cache"})


def login_page(message, status):
    """로그인 실패 안내. 인라인 스타일과 스크립트 없이 만들어 보안 정책(CSP)을 지킨다."""
    body = (
        '<!doctype html><html lang="ko"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1"><title>로그인</title>'
        '<link rel="stylesheet" href="/static/css/base.css"></head><body><main class="page">'
        f'<p class="page-message">{html.escape(message)}</p>'
        '<p class="page-message"><a href="/auth/login">다시 로그인</a></p></main></body></html>'
    )
    return HTMLResponse(body, status_code=status)
