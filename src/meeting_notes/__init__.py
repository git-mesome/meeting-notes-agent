"""회의 녹음을 화자별 전사문과 회의록으로 정리하는 웹 앱.

패키지 구성:
    main.py          앱 조립(라우터, 미들웨어, 서비스 연결)
    settings.py      회사 폴더와 환경 변수 설정
    web/             HTTP 계층: 라우터, 요청 모델, 미들웨어, 화면 파일
    jobs/            회의(작업) 저장, 처리 큐, 조회와 수정
    pipeline/        녹음 → 전사 → 발언 정리 → 회의록
    speakers/        화자 이름과 목소리 인식
    issues/          액션 아이템을 이슈 트래커에 등록
    auth/            사내 SSO 로그인
    notifications/   웹 푸시
    questions.py     회의 내용 질문
    memory.py        사용자가 확인해 준 사실(다음 회의에 참고)
    llm.py           Claude API 호출
    cli.py           명령줄 도구
"""
