import json
import subprocess
import time
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient

from meeting_notes.jobs.share import render_share_html, share_sections
from meeting_notes.main import create_app
from meeting_notes.pipeline.templates import TEMPLATES, system_prompt

NOTES = """# 회의록: 방화벽 교체 <점검>

## 요약
- 본사를 먼저 교체

## 안건
### 교체 순서 [00:12]
- **결정**: 본사 장비를 먼저 교체 [01:05]
- SPEAKER_00 의견: 이중화로 위험이 낮음 <script>alert(1)</script>

## 액션 아이템
| 담당 | 할 일 | 기한 | 근거 |
|---|---|---|---|
| SPEAKER_00 | 계획서 작성 | 9월 12일 | [01:05] [01:40] |

## 확인 필요
- 모델명 불분명 [00:48]
"""
TURNS = [
    {"start": 0.0, "end": 8.0, "speaker": "SPEAKER_00", "text": "본사부터 교체합시다."},
    {"start": 8.0, "end": 10.0, "speaker": "SPEAKER_01", "text": "네."},
]


def fake_process(audio, out_dir, on_stage, on_process):
    on_stage("transcribing")
    (out_dir / "turns.json").write_text(json.dumps(TURNS, ensure_ascii=False), encoding="utf-8")
    on_stage("writing")
    (out_dir / "notes.md").write_text(NOTES, encoding="utf-8")
    return {"input_tokens": 1, "output_tokens": 1}


@pytest.fixture(scope="module")
def tone(tmp_path_factory):
    path = tmp_path_factory.mktemp("audio") / "tone.m4a"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=1", str(path)], check=True)
    return path.read_bytes()


def test_share_html_drops_times_checks_and_evidence_column():
    page = render_share_html("방화벽 교체 <점검>", "2026-11-09T15:30:00+00:00", 125, False, NOTES)
    assert "[00:12]" not in page and "[01:05]" not in page and "00:48" not in page
    assert "확인 필요" not in page and "모델명" not in page
    assert "<th>근거</th>" not in page and "<th>담당</th><th>할 일</th><th>기한</th>" in page
    assert "<h3>교체 순서</h3>" in page and "<strong>결정</strong>: 본사 장비를 먼저 교체</li>" in page
    # 회의록 안의 글자는 그대로 보이게만 한다
    assert "<script>" not in page and "&lt;script&gt;" in page
    assert "<title>방화벽 교체 &lt;점검&gt;</title>" in page
    # 한국 시간으로 날짜를 적는다(UTC 15:30은 다음 날 00:30)
    assert "2026년 11월 10일 · 2분 회의" in page and "초안" in page
    assert render_share_html("t", "2026-11-09T01:00:00+00:00", 30, True, NOTES).count("확정본") == 1


def test_share_sections_keep_order_and_skip_title():
    assert [section.split("\n", 1)[0] for section in share_sections(NOTES)] == ["## 요약", "## 안건", "## 액션 아이템"]


def test_share_endpoint_names_speakers_and_downloads(tmp_path, tone):
    app = create_app(data_dir=tmp_path, process=fake_process, tracker=None, auth=None)
    with TestClient(app, base_url="http://127.0.0.1") as client:
        job_id = client.post("/api/jobs", files={"file": ("a.m4a", tone, "audio/mp4")}).json()["id"]
        deadline = time.time() + 20
        while client.get(f"/api/jobs/{job_id}").json()["status"] != "done":
            assert time.time() < deadline
            time.sleep(0.02)
        client.put(f"/api/jobs/{job_id}/speakers/SPEAKER_00", json={"name": "홍길동"})
        response = client.get(f"/api/jobs/{job_id}/share")
    assert response.status_code == 200 and response.headers["content-type"].startswith("text/html")
    assert quote("회의록 방화벽 교체 _점검_.html") in response.headers["content-disposition"]
    assert "홍길동 의견" in response.text and "SPEAKER_00" not in response.text
    assert "본사부터 교체합시다" not in response.text  # 전사문은 넣지 않는다


def test_general_template_puts_decisions_inside_each_agenda():
    general = TEMPLATES["general"]["format"]
    assert "## 안건" in general and "**결정**" in general
    assert "## 결정 사항" not in general and "## 안건별 논의" not in general
    assert "## 결정 사항" in TEMPLATES["weekly"]["format"]
    assert "결정의 근거부터 줄인다" in system_prompt("general", 1000)
