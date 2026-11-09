"""회의(작업) 하나는 jobs/<id>/ 폴더 하나다.

    store.py    meta.json 읽기·쓰기(Repository)
    worker.py   녹음을 한 건씩 처리하는 큐
    views.py    화면에 보낼 항목과 남은 시간
    search.py   회의록·전사문 검색 도구
    service.py  조회, 수정, 질문, 다시 쓰기 같은 작업(라우터가 쓰는 서비스)
"""
