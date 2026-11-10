"""녹음을 회의록으로 만드는 처리 단계.

    audio.py       오디오 확인과 음량 보정
    transcribe.py  WhisperX 전사·정렬·화자 구분
    turns.py       단어 단위 화자 분리, 환각 문구 제거, 전사문 만들기
    spelling.py    회사 표기 규칙
    knowledge.py   회사 배경 지식과 용어
    templates.py   회의 유형별 회의록 양식
    documents.py   회의에서 함께 본 자료
    notes.py       Claude로 회의록 쓰기
    process.py     위 단계를 이어서 녹음 하나를 처리한다
"""
