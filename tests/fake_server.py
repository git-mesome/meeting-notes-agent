"""화면 개발용 서버. 실제 전사와 API 호출 없이 정해진 예시 회의록을 돌려준다.

실행: uv run uvicorn tests.fake_server:create --factory --port 8010
"""

import json
import os
import time

from app import create_app

SAMPLE_NOTES = """# 회의록: 3분기 방화벽 교체 일정 점검

## 요약
- 본사와 지점 두 곳의 방화벽 교체 순서를 정했다. 본사를 먼저 교체하고 지점은 2주 간격으로 진행한다.
- 야간 작업 인력 배정은 다음 회의에서 정한다.

## 결정 사항
- 본사 장비를 먼저 교체한다. [00:12] [01:05]
- 지점 교체는 2주 간격으로 진행한다. [01:40]

## 액션 아이템
| 담당 | 할 일 | 기한 | 근거 |
|---|---|---|---|
| 박지훈 | 본사 교체 작업 계획서를 작성한다 | 9월 12일 | [01:05] |
| 미정 | 지점 작업 일정을 현장과 조율한다 | 미정 | [01:40] [02:10] |

## 논의 내용
- **교체 순서**: 본사는 이중화가 되어 있어 위험이 낮다는 의견이 나왔다. [00:12]
- **작업 시간**: 평일 야간 작업을 기본으로 한다. 주말 작업은 현장 사정을 보고 다시 논의한다. [02:10]

## 확인 필요
- "방화벽 모델명"이 전사문에서 불분명하다. 장비 목록과 대조해야 한다. [00:48]
"""

SAMPLE_TURNS = [
    {"start": 0.0, "end": 11.0, "speaker": "SPEAKER_00", "text": "오늘은 방화벽 교체 일정을 점검하겠습니다."},
    {"start": 12.0, "end": 47.0, "speaker": "SPEAKER_00", "text": "본사는 이중화가 되어 있으니 먼저 교체해도 위험이 낮습니다."},
    {"start": 48.0, "end": 58.0, "speaker": "SPEAKER_01", "text": "모델이 어떤 장비였죠? 목록을 다시 봐야 할 것 같습니다."},
    {"start": 65.0, "end": 98.0, "speaker": "SPEAKER_00", "text": "그럼 본사부터 하고 계획서는 지훈 님이 12일까지 써 주세요."},
    {"start": 100.0, "end": 128.0, "speaker": "SPEAKER_02", "text": "지점은 2주 간격이면 현장에서 소화할 수 있습니다."},
    {"start": 130.0, "end": 170.0, "speaker": "SPEAKER_00", "text": "작업은 평일 야간을 기본으로 하고 주말은 다시 이야기합시다."},
]


def fake_process(_audio, out_dir, on_stage):
    delay = float(os.environ.get("FAKE_STAGE_SECONDS", "15"))
    on_stage("transcribing")
    time.sleep(delay)
    (out_dir / "turns.json").write_text(json.dumps(SAMPLE_TURNS, ensure_ascii=False), encoding="utf-8")
    on_stage("writing")
    time.sleep(delay / 3)
    (out_dir / "notes.md").write_text(SAMPLE_NOTES, encoding="utf-8")
    return {"input_tokens": 0, "output_tokens": 0}


def create():
    return create_app(data_dir=os.environ.get("FAKE_DATA_DIR", "jobs-fake"), process=fake_process)
