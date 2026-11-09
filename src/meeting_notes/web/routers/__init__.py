"""API 라우터(스프링의 @RestController에 해당). 요청을 받아 서비스를 부르고 결과를 돌려준다.

    jobs.py      회의 올리기, 목록, 상세, 멈추기, 다시 시작, 지우기, 녹음 재생
    notes.py     회의록 고치기, 확정, 다시 쓰기, 내려받기(마크다운, 공유용 HTML), 질문, 검색
    speakers.py  화자 이름, 등록한 목소리
    memory.py    AI가 기억하는 내용(사용자가 확인한 사실)
    issues.py    이슈 트래커 초안과 등록
    push.py      웹 푸시 구독
    auth.py      SSO 로그인과 로그아웃
"""
