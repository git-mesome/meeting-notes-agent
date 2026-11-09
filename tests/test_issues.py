import json
import shutil
import subprocess
import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from meeting_notes import llm, settings
from meeting_notes.issues import Tracker, TrackerError, load_tracker
from meeting_notes.issues.actions import action_items
from meeting_notes.issues.drafting import draft_issues
from meeting_notes.main import create_app
from meeting_notes.pipeline.spelling import fix_spelling
from meeting_notes.settings import Company

EXAMPLE = Path(__file__).parent.parent / "company.example"

NOTES = """# 회의록: 장비 교체 검토

## 요약
- 요약

## 액션 아이템
| 담당 | 할 일 | 기한 | 근거 |
|---|---|---|---|
| SPEAKER_00 | 교체 계획서 작성 | 미정 | [20:08] |
| 미정 | 지점 일정 정리 | 다음 주 | [11:39] |

## 확인 필요
- 없음
"""
TURNS = [{"start": 0.0, "end": 3.0, "speaker": "SPEAKER_00", "text": "발언"}]


def fake_process(audio, out_dir, on_stage, on_process):
    on_stage("transcribing")
    (out_dir / "turns.json").write_text(json.dumps(TURNS, ensure_ascii=False), encoding="utf-8")
    on_stage("writing")
    (out_dir / "notes.md").write_text(NOTES, encoding="utf-8")
    return {"input_tokens": 1, "output_tokens": 1}


class FakeTracker(Tracker):
    name = "보드"
    destination = "TEAM 보드"
    categories = ["기능", "버그"]
    priorities = ["보통", "낮음"]
    guide = "- 설명에는 완료 조건을 쓴다."
    after_register = "보드에서 확인해요."

    def __init__(self, fail_on=None):
        self.created, self.comments, self.fail_on = [], [], fail_on

    def people(self):
        return ["홍길순", "홍길동"]

    def tags(self):
        return ["플랫폼", "도구"]

    def open_issues(self):
        if self.fail_on == "read":
            raise TrackerError("연결 실패")
        return [
            {"key": "PLT-1", "title": "장비 교체 작업", "type": "epic", "status": "진행 중", "tags": ["플랫폼"], "assignees": []},
            {"key": "PLT-5", "title": "지점 작업 일정 관리", "type": "task", "status": "진행 중", "tags": ["플랫폼"], "assignees": ["홍길순"]},
        ]

    def issue(self, key):
        if key == "PLT-1":
            raise TrackerError("조회 실패")
        return {"key": key, "description": "## 배경\n" + "일정 비교 " * 100}

    def issue_url(self, key):
        return f"http://board.example/{key}"

    def create(self, issues):
        if self.fail_on == "create":
            raise TrackerError("등록 실패")
        self.created.append(issues)
        return [f"PLT-{7 + i}" for i in range(len(issues))]

    def comment(self, key, text):
        self.comments.append((key, text))


def fake_draft(meeting, actions, space, rules):
    fake_draft.seen = (meeting, actions, space, rules)
    return [
        {"source": 0, "action": "create", "title": "교체 계획서 작성", "description": "## 배경\n- 회의 [20:08]\n\n## 완료 조건\n- [ ] 계획서 공유",
         "category": "기능", "priority": "보통", "assignees": ["홍길동", "없는사람"], "tags": ["플랫폼", "없는태그"], "parent": "PLT-1",
         "due_date": "", "existing_key": "", "comment": "", "reason": ""},
        {"source": 1, "action": "comment", "title": "", "description": "", "category": "없는분류", "priority": "보통", "assignees": [],
         "tags": [], "parent": "NOPE-1", "due_date": "", "existing_key": "PLT-5", "comment": "지점 일정 정리 필요 [11:39]", "reason": ""},
    ]


@pytest.fixture(scope="session")
def tone(tmp_path_factory):
    path = tmp_path_factory.mktemp("audio") / "tone.m4a"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=1", str(path)], check=True)
    return path.read_bytes()


def make(tmp_path, tracker, draft=fake_draft):
    return TestClient(create_app(data_dir=tmp_path, process=fake_process, tracker=tracker, draft=draft), base_url="http://127.0.0.1")


def finished_job(client, tone):
    job_id = client.post("/api/jobs", files={"file": ("a.m4a", tone, "audio/mp4")}).json()["id"]
    deadline = time.time() + 20
    while client.get(f"/api/jobs/{job_id}").json()["status"] != "done":
        assert time.time() < deadline
        time.sleep(0.02)
    return job_id


def test_action_items_are_read_from_table():
    rows = action_items(NOTES)
    assert [(r["index"], r["owner"], r["task"], r["due"], r["evidence"]) for r in rows] == [
        (0, "SPEAKER_00", "교체 계획서 작성", "미정", "[20:08]"),
        (1, "미정", "지점 일정 정리", "다음 주", "[11:39]"),
    ]
    assert action_items("# 회의록\n\n## 요약\n- 없음\n") == []


def test_status_reports_whether_tracker_is_configured(tmp_path):
    with make(tmp_path, None) as client:
        assert client.get("/api/tracker").json() == {"enabled": False}
    with make(tmp_path / "b", FakeTracker()) as client:
        assert client.get("/api/tracker").json() == {
            "enabled": True, "name": "보드", "destination": "TEAM 보드", "after_register": "보드에서 확인해요."
        }


def test_drafts_are_cleaned_against_space(tmp_path, tone):
    with make(tmp_path, FakeTracker()) as client:
        job_id = finished_job(client, tone)
        client.put(f"/api/jobs/{job_id}/speakers/SPEAKER_00", json={"name": "홍길동"})
        body = client.post(f"/api/jobs/{job_id}/issues/drafts").json()
    first, second = body["drafts"]
    assert first["assignees"] == ["홍길동"] and first["tags"] == ["플랫폼"] and first["parent"] == "PLT-1"
    assert second["action"] == "comment" and second["existing_title"] == "지점 작업 일정 관리" and second["parent"] == ""
    assert first["category"] == "기능" and second["category"] == ""
    meeting, actions, space, rules = fake_draft.seen
    assert rules == {"categories": ["기능", "버그"], "priorities": ["보통", "낮음"], "guide": "- 설명에는 완료 조건을 쓴다."}
    assert actions[0]["owner"] == "홍길동"
    assert [e["key"] for e in space["epics"]] == ["PLT-1"]
    assert body["epics"] == [{"key": "PLT-1", "title": "장비 교체 작업"}]
    assert [issue["key"] for issue in body["issues"]] == ["PLT-1", "PLT-5"]
    # 설명 하나를 못 가져와도 초안은 만들고, 설명은 앞부분만 보낸다.
    summaries = {issue["key"]: issue["summary"] for issue in space["open_issues"]}
    assert summaries["PLT-1"] == "" and summaries["PLT-5"].startswith("## 배경") and len(summaries["PLT-5"]) == 400


def test_comment_on_unknown_issue_becomes_new_issue(tmp_path, tone):
    def draft(meeting, actions, space, rules):
        items = fake_draft(meeting, actions, space, rules)
        items[1]["existing_key"] = "PLT-999"
        return items

    with make(tmp_path, FakeTracker(), draft) as client:
        job_id = finished_job(client, tone)
        assert client.post(f"/api/jobs/{job_id}/issues/drafts").json()["drafts"][1]["action"] == "create"


def test_register_creates_and_comments_then_remembers(tmp_path, tone):
    tracker = FakeTracker()
    with make(tmp_path, tracker) as client:
        job_id = finished_job(client, tone)
        payload = {
            "create": [{"source": 0, "title": "교체 계획서 작성", "description": "## 배경\n- 내용", "category": "기능",
                        "priority": "보통", "assignees": [], "tags": ["플랫폼"], "parent": "PLT-1", "due_date": ""}],
            "comments": [{"source": 1, "key": "PLT-5", "text": "지점 일정 정리 필요"}],
        }
        response = client.post(f"/api/jobs/{job_id}/issues", json=payload)
        assert response.status_code == 200
        results = response.json()["results"]
        assert [(r["source"], r["kind"], r["key"], r["url"]) for r in results] == [
            (0, "create", "PLT-7", "http://board.example/PLT-7"),
            (1, "comment", "PLT-5", "http://board.example/PLT-5"),
        ]
        assert tracker.created == [[{"title": "교체 계획서 작성", "description": "## 배경\n- 내용", "category": "기능", "priority": "보통", "tags": ["플랫폼"], "parent": "PLT-1"}]]
        assert tracker.comments == [("PLT-5", "지점 일정 정리 필요")]
        registered = client.get(f"/api/jobs/{job_id}").json()["issues"]
        assert [(r["key"], r["url"]) for r in registered] == [("PLT-7", "http://board.example/PLT-7"), ("PLT-5", "http://board.example/PLT-5")]


def test_register_rejects_empty_and_invalid(tmp_path, tone):
    with make(tmp_path, FakeTracker()) as client:
        job_id = finished_job(client, tone)
        assert client.post(f"/api/jobs/{job_id}/issues", json={"create": [], "comments": []}).status_code == 400
        bad = {"create": [{"source": 0, "title": "제목", "description": "내용", "category": "feat", "priority": "보통"}]}
        assert client.post(f"/api/jobs/{job_id}/issues", json=bad).status_code == 422
        bad_date = {"create": [{"source": 0, "title": "제목", "description": "내용", "category": "기능", "priority": "보통", "due_date": "다음 주"}]}
        assert client.post(f"/api/jobs/{job_id}/issues", json=bad_date).status_code == 422
        bad_key = {"comments": [{"source": 0, "key": "plt-5; drop", "text": "x"}]}
        assert client.post(f"/api/jobs/{job_id}/issues", json=bad_key).status_code == 422


def test_register_from_another_site_is_refused(tmp_path, tone):
    tracker = FakeTracker()
    with make(tmp_path, tracker) as client:
        job_id = finished_job(client, tone)
        response = client.post(
            f"/api/jobs/{job_id}/issues",
            json={"comments": [{"source": 0, "key": "PLT-5", "text": "x"}]},
            headers={"Origin": "https://evil.example"},
        )
        assert response.status_code == 403
        assert tracker.comments == []


def test_tracker_failures_are_reported(tmp_path, tone):
    with make(tmp_path, FakeTracker(fail_on="read")) as client:
        job_id = finished_job(client, tone)
        assert client.post(f"/api/jobs/{job_id}/issues/drafts").status_code == 502
    with make(tmp_path / "b", FakeTracker(fail_on="create")) as client:
        job_id = finished_job(client, tone)
        payload = {"create": [{"source": 0, "title": "제목", "description": "내용", "category": "기능", "priority": "보통"}]}
        response = client.post(f"/api/jobs/{job_id}/issues", json=payload)
        assert response.status_code == 502 and "등록 실패" in response.json()["detail"]
        assert client.get(f"/api/jobs/{job_id}").json()["issues"] == []


def test_partial_failure_keeps_what_was_registered(tmp_path, tone):
    class CommentFails(FakeTracker):
        def comment(self, key, text):
            raise TrackerError("댓글 실패")

    with make(tmp_path, CommentFails()) as client:
        job_id = finished_job(client, tone)
        payload = {
            "create": [{"source": 0, "title": "제목", "description": "내용", "category": "기능", "priority": "보통"}],
            "comments": [{"source": 1, "key": "PLT-5", "text": "덧붙임"}],
        }
        response = client.post(f"/api/jobs/{job_id}/issues", json=payload)
        assert response.status_code == 502 and "1건은 등록했지만" in response.json()["detail"]
        assert [item["key"] for item in client.get(f"/api/jobs/{job_id}").json()["issues"]] == ["PLT-7"]


def test_draft_failure_hides_details(tmp_path, tone):
    def draft(*_):
        raise RuntimeError("비밀 내용")

    with make(tmp_path, FakeTracker(), draft) as client:
        job_id = finished_job(client, tone)
        response = client.post(f"/api/jobs/{job_id}/issues/drafts")
        assert response.status_code == 502 and "비밀" not in response.text


def test_endpoints_need_configuration(tmp_path, tone):
    with make(tmp_path, None) as client:
        job_id = finished_job(client, tone)
        assert client.post(f"/api/jobs/{job_id}/issues/drafts").status_code == 409


def test_draft_issues_requests_structured_output(monkeypatch):
    captured = {}

    class Message:
        stop_reason = "end_turn"
        content = [type("Block", (), {"type": "text", "text": '{"items": [{"title": "에이아이 검토"}]}'})()]

    class Client:
        class beta:
            class messages:
                @staticmethod
                def create(**kwargs):
                    captured.update(kwargs)
                    return Message()

    monkeypatch.setattr(llm.anthropic, "Anthropic", Client)
    rules = {"categories": ["기능", "버그"], "priorities": [], "guide": "- 설명에는 완료 조건을 쓴다."}
    assert draft_issues({"title": "t"}, [{"index": 0}], {"people": []}, rules) == [{"title": "AI 검토"}]
    schema = captured["output_config"]["format"]["schema"]["properties"]["items"]["items"]
    assert schema["properties"]["category"]["enum"] == ["기능", "버그"] and "priority" not in schema["properties"]
    assert set(schema["required"]) == set(schema["properties"])
    assert captured["system"].endswith("- 설명에는 완료 조건을 쓴다.")


def test_drafts_are_kept_until_notes_change(tmp_path, tone):
    calls = []

    def draft(meeting, actions, space, rules):
        calls.append(meeting["notes"])
        return fake_draft(meeting, actions, space, rules)

    with make(tmp_path, FakeTracker(), draft) as client:
        job_id = finished_job(client, tone)
        first = client.post(f"/api/jobs/{job_id}/issues/drafts").json()
        again = client.post(f"/api/jobs/{job_id}/issues/drafts").json()
        assert len(calls) == 1 and again["drafts"] == first["drafts"] and again["drafted_at"] == first["drafted_at"]
        assert "fingerprint" not in again
        client.post(f"/api/jobs/{job_id}/issues/drafts?refresh=true")
        assert len(calls) == 2
        client.put(f"/api/jobs/{job_id}/speakers/SPEAKER_00", json={"name": "홍길동"})
        client.post(f"/api/jobs/{job_id}/issues/drafts")
        assert len(calls) == 3 and "홍길동" in calls[-1]


def test_drafts_requested_twice_are_made_once(tmp_path, tone):
    started, release, calls = threading.Event(), threading.Event(), []

    def draft(meeting, actions, space, rules):
        calls.append(1)
        started.set()
        release.wait(5)
        return fake_draft(meeting, actions, space, rules)

    with make(tmp_path, FakeTracker(), draft) as client:
        job_id = finished_job(client, tone)
        results = []

        def post():
            results.append(client.post(f"/api/jobs/{job_id}/issues/drafts").json())

        first = threading.Thread(target=post)
        first.start()
        assert started.wait(5)
        second = threading.Thread(target=post)
        second.start()
        time.sleep(0.3)
        release.set()
        first.join(5)
        second.join(5)
    assert len(calls) == 1 and len(results) == 2 and results[0]["drafts"] == results[1]["drafts"]


def test_tracker_without_categories_takes_none(tmp_path, tone):
    class Plain(FakeTracker):
        categories, priorities = [], []

    with make(tmp_path, Plain()) as client:
        job_id = finished_job(client, tone)
        plain = {"create": [{"source": 0, "title": "제목", "description": "내용"}]}
        assert client.post(f"/api/jobs/{job_id}/issues", json=plain).status_code == 200
        tagged = {"create": [{"source": 0, "title": "제목", "description": "내용", "category": "기능"}]}
        assert client.post(f"/api/jobs/{job_id}/issues", json=tagged).status_code == 422


# 회사 폴더


def test_company_settings_are_read_from_folder(tmp_path):
    (tmp_path / "company.toml").write_text(
        '[server]\nallowed_hosts = ["meet.example"]\n\n[spelling]\n"쿠버네티스" = "Kubernetes"\n', encoding="utf-8"
    )
    (tmp_path / "glossary.txt").write_text("로드 밸런서\n\n배포\n", encoding="utf-8")
    company = Company(tmp_path)
    assert company.allowed_hosts == ["meet.example"]
    assert company.spelling == {"에이아이": "AI", "쿠버네티스": "Kubernetes"}
    assert company.glossary == ["로드 밸런서", "배포"]
    assert company.knowledge_dir == tmp_path / "knowledge"
    assert company.tracker() is None
    empty = Company(tmp_path / "없음")
    assert empty.allowed_hosts == settings.DEFAULT_ALLOWED_HOSTS and empty.glossary == []


def test_app_uses_company_hosts_and_spelling(tmp_path, monkeypatch):
    (tmp_path / "company.toml").write_text('[server]\nallowed_hosts = ["meet.example"]\n\n[spelling]\n"엔진엑스" = "nginx"\n', encoding="utf-8")
    monkeypatch.setattr(settings, "current", lambda: Company(tmp_path))
    with TestClient(create_app(data_dir=tmp_path / "jobs", process=fake_process, tracker=None), base_url="http://meet.example") as client:
        assert client.get("/api/jobs").status_code == 200
        assert client.get("/api/jobs", headers={"Host": "127.0.0.1"}).status_code == 400
    assert fix_spelling("엔진엑스와 에이아이") == "nginx와 AI"


def test_example_tracker_is_loaded_from_company_folder(tmp_path):
    shutil.copy(EXAMPLE / "example_tracker.py", tmp_path)
    tracker = load_tracker(tmp_path, {"module": "example_tracker", "people": ["홍길동"], "tags": ["화면"]})
    assert tracker.name == "연습용 트래커" and tracker.people() == ["홍길동"]
    assert tracker.create([{"title": "첫 이슈", "description": "내용"}, {"title": "둘째", "description": "내용"}]) == ["DEMO-1", "DEMO-2"]
    tracker.comment("DEMO-1", "덧붙임")
    assert [issue["key"] for issue in tracker.open_issues()] == ["DEMO-1", "DEMO-2"]
    assert tracker.issue("DEMO-1")["comments"] == ["덧붙임"]
    with pytest.raises(TrackerError):
        tracker.comment("DEMO-9", "x")


def test_example_company_folder_is_valid():
    company = Company(EXAMPLE)
    assert company.config["tracker"]["module"] == "example_tracker"
    assert company.glossary and (company.knowledge_dir / "meeting_context.md").exists()
    terms = json.loads((company.knowledge_dir / "terms.json").read_text(encoding="utf-8"))
    assert all({"term", "definition"} <= set(term) for term in terms)
