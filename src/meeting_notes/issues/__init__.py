"""회의록의 액션 아이템을 이슈 트래커에 등록한다.

    trackers.py   트래커 어댑터 규격(Tracker)과 회사 폴더에서 어댑터를 읽는 함수
    actions.py    회의록의 액션 아이템 표 읽기
    drafting.py   Claude로 이슈 초안 만들기
    service.py    초안 저장, 정리, 등록(라우터가 쓰는 서비스)
"""

from meeting_notes.issues.trackers import Tracker, TrackerError, load_tracker

__all__ = ["Tracker", "TrackerError", "load_tracker"]
