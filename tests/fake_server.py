"""화면 개발용 서버. 실제 전사와 API 호출 없이 정해진 예시 회의록을 돌려준다.

실행: uv run uvicorn tests.fake_server:create --factory --port 8010
"""

import json
import os
import time

from meeting_notes.issues import Tracker
from meeting_notes.main import create_app

SAMPLE_NOTES = """# 회의록: 3분기 방화벽 교체 일정 점검

## 요약
- 본사를 먼저 교체하고 지점은 2주 간격으로 진행
- 야간 작업 인력 배정은 다음 회의에서 결정

## 안건
### 교체 순서 [00:12]
- **결정**: 본사 장비를 먼저 교체 [01:05]
- 본사는 이중화가 되어 있어 교체 위험이 낮음
### 지점 교체 일정 [01:40]
- **결정**: 지점 교체는 2주 간격으로 진행 [01:40]
- 평일 야간 작업이 기본, 주말 작업은 현장 사정을 보고 다시 논의 [02:10]

## 액션 아이템
| 담당 | 할 일 | 기한 | 근거 |
|---|---|---|---|
| 박지훈 | 본사 교체 작업 계획서 작성 | 9월 12일 | [01:05] |
| SPEAKER_02 | 지점 작업 일정을 현장과 조율 | 미정 | [01:40] [02:10] |

## 확인 필요
- "방화벽 모델명"이 전사문에서 불분명. 장비 목록과 대조 필요 [00:48]
"""

SAMPLE_TURNS = [
    {"start": 0.0, "end": 11.0, "speaker": "SPEAKER_00", "text": "오늘은 방화벽 교체 일정을 점검하겠습니다."},
    {"start": 12.0, "end": 47.0, "speaker": "SPEAKER_00", "text": "본사는 이중화가 되어 있으니 먼저 교체해도 위험이 낮습니다."},
    {"start": 48.0, "end": 58.0, "speaker": "SPEAKER_01", "text": "모델이 어떤 장비였죠? 목록을 다시 봐야 할 것 같습니다."},
    {"start": 65.0, "end": 98.0, "speaker": "SPEAKER_00", "text": "그럼 본사부터 하고 계획서는 지훈 님이 12일까지 써 주세요."},
    {"start": 100.0, "end": 128.0, "speaker": "SPEAKER_02", "text": "지점은 2주 간격이면 현장에서 소화할 수 있습니다."},
    {"start": 130.0, "end": 170.0, "speaker": "SPEAKER_00", "text": "작업은 평일 야간을 기본으로 하고 주말은 다시 이야기합시다."},
]


SAMPLE_EMBEDDINGS = {"SPEAKER_00": [1.0, 0.0, 0.0], "SPEAKER_01": [0.0, 1.0, 0.0], "SPEAKER_02": [0.0, 0.0, 1.0]}


def fake_answer(_transcript, _notes, question):
    time.sleep(1)
    return f"'{question}'에 대한 예시 답변이에요. 본사부터 교체하기로 했어요. [00:12] [01:05]"


def fake_process(_audio, out_dir, on_stage, _on_process):
    delay = float(os.environ.get("FAKE_STAGE_SECONDS", "15"))
    on_stage("transcribing")
    time.sleep(delay)
    (out_dir / "turns.json").write_text(json.dumps(SAMPLE_TURNS, ensure_ascii=False), encoding="utf-8")
    (out_dir / "audio.json").write_text(json.dumps({"speaker_embeddings": SAMPLE_EMBEDDINGS}), encoding="utf-8")
    on_stage("writing")
    time.sleep(delay / 3)
    (out_dir / "notes.md").write_text(SAMPLE_NOTES, encoding="utf-8")
    return {"input_tokens": 0, "output_tokens": 0}


class FakeTracker(Tracker):
    name = "예시 보드"
    destination = "TEAM 보드"
    categories = ["기능", "버그"]
    priorities = ["보통", "낮음"]
    after_register = "보드에서 진행 상황을 확인해요."

    def people(self):
        return ["박지훈", "김철수"]

    def tags(self):
        return ["플랫폼", "도구"]

    def open_issues(self):
        return [
            {"key": "PLT-1", "title": "장비 교체 작업", "type": "epic", "status": "진행 중", "tags": ["플랫폼"], "assignees": []},
            {"key": "PLT-2", "title": "지점 작업 일정 관리", "type": "task", "status": "진행 중", "tags": ["플랫폼"], "assignees": []},
        ]

    def issue(self, key):
        return {"key": key, "description": ""}

    def issue_url(self, key):
        return f"http://board.example/{key}"

    def create(self, issues):
        time.sleep(0.5)
        return [f"PLT-{10 + i}" for i in range(len(issues))]

    def comment(self, key, text):
        pass


def fake_draft(_meeting, actions, _space, _rules):
    time.sleep(3)
    return [
        {"source": 0, "action": "create", "title": "본사 교체 작업 계획서 작성", "description": "## 배경\n- 회의 [01:05]\n\n## 요구사항\n- 본사 장비 교체 순서 정리\n\n## 완료 조건\n- [ ] 계획서 공유",
         "category": "기능", "priority": "보통", "assignees": ["박지훈"], "tags": ["플랫폼"], "parent": "PLT-1", "due_date": "", "existing_key": "", "comment": "", "reason": ""},
        {"source": 1, "action": "comment", "title": "", "description": "", "category": "기능", "priority": "보통", "assignees": [], "tags": [],
         "parent": "", "due_date": "", "existing_key": "PLT-2", "comment": "지점 교체는 2주 간격으로 진행 [01:40]", "reason": ""},
    ]


def create():
    return create_app(
        data_dir=os.environ.get("FAKE_DATA_DIR", "jobs-fake"),
        process=fake_process,
        answer=fake_answer,
        tracker=FakeTracker(),
        draft=fake_draft,
    )
