"""HTTP 계층(스프링의 Controller와 Filter에 해당).

    routers/       API 라우터
    schemas.py     요청 본문 모델(DTO)
    deps.py        라우터에 서비스를 넣어 주는 의존성
    middleware.py  보안 헤더, Host·Origin 검사, 로그인 검사
    pages.py       화면(index.html, 서비스 워커)과 로그인 안내 페이지
    static/        화면 파일
"""
