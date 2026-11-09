"""이슈 초안을 만들어 저장하고, 사용자가 고른 것을 트래커에 등록한다."""

import hashlib
import json
import logging
import threading
from concurrent.futures import Future, ThreadPoolExecutor

from meeting_notes.errors import AppError, Conflict, Invalid, Upstream
from meeting_notes.issues.actions import action_items
from meeting_notes.issues.trackers import TrackerError
from meeting_notes.jobs.store import now

logger = logging.getLogger(__name__)

DRAFTS_FILE = "issue_drafts.json"
# 같은 일을 다루는 이슈를 찾으려고 열린 이슈의 설명 앞부분을 함께 보낸다.
ISSUE_SUMMARY_CHARS = 400
MAX_DESCRIBED_ISSUES = 60


def link_issues(tracker):
    """등록한 이슈 목록에 트래커에서 열 주소를 붙이는 함수를 만든다."""

    def links(items):
        return [{**item, "url": tracker.issue_url(item["key"]) if tracker else ""} for item in items]

    return links


class IssueService:
    def __init__(self, tracker, jobs, draft):
        self.tracker = tracker
        self.jobs = jobs
        self.draft = draft
        self.with_urls = link_issues(tracker)
        # 같은 회의의 초안을 동시에 요청하면 한 번만 만든다.
        self.drafting = {}
        self.lock = threading.Lock()

    def require(self):
        if self.tracker is None:
            raise Conflict("이슈 트래커가 설정되어 있지 않아요.")

    def status(self):
        if self.tracker is None:
            return {"enabled": False}
        return {
            "enabled": True,
            "name": self.tracker.name,
            "destination": self.tracker.destination,
            "after_register": self.tracker.after_register,
        }

    def summaries(self, issues):
        """열린 이슈마다 설명 앞부분을 가져온다. 제목만으로는 회의의 할 일과 같은 일인지 알기 어렵다."""

        def summary(issue):
            try:
                detail = self.tracker.issue(issue["key"])
            except (TrackerError, OSError):
                return ""
            description = detail.get("description") if isinstance(detail, dict) else ""
            return (description or "")[:ISSUE_SUMMARY_CHARS]

        with ThreadPoolExecutor(max_workers=8) as pool:
            found = list(pool.map(summary, issues[:MAX_DESCRIBED_ISSUES]))
        return found + [""] * (len(issues) - len(found))

    def make(self, job, notes, actions):
        """트래커의 현재 상태를 읽어 초안을 만들고, 트래커에 없는 값은 지운다."""
        tracker = self.tracker
        try:
            people, tags, issues = tracker.people(), tracker.tags(), tracker.open_issues()
        except (TrackerError, OSError) as error:
            logger.error("이슈 트래커 조회에 실패했다", exc_info=error)
            raise Upstream(f"{tracker.name}에 연결하지 못했어요. 잠시 후 다시 시도해 주세요.") from error
        epics = [{"key": issue["key"], "title": issue["title"]} for issue in issues if issue.get("type") == "epic"]
        space = {
            "people": people,
            "tags": tags,
            "epics": epics,
            "open_issues": [
                {**{key: issue.get(key) for key in ("key", "title", "type", "status", "tags", "assignees")}, "summary": summary}
                for issue, summary in zip(issues, self.summaries(issues))
            ],
        }
        rules = {"categories": tracker.categories, "priorities": tracker.priorities, "guide": tracker.guide}
        meeting = {"title": job.get("title") or job["name"], "date": job["created_at"][:10], "notes": notes}
        try:
            drafts = self.draft(meeting, actions, space, rules)
        except Exception as error:
            logger.error("작업 %s 이슈 초안 생성에 실패했다", job["id"], exc_info=error)
            raise Upstream("이슈 초안을 만들지 못했어요. 잠시 후 다시 시도해 주세요.") from error
        known = {issue["key"]: issue["title"] for issue in issues}
        for item in drafts:
            item["tags"] = [tag for tag in item["tags"] if tag in tags]
            item["assignees"] = [person for person in item["assignees"] if person in people]
            item["parent"] = item["parent"] if item["parent"] in known else ""
            item["category"] = item.get("category") if item.get("category") in tracker.categories else ""
            item["priority"] = item.get("priority") if item.get("priority") in tracker.priorities else ""
            if item["action"] == "comment" and item["existing_key"] not in known:
                item["action"] = "create"
            item["existing_title"] = known.get(item["existing_key"], "")
        return {
            "actions": actions,
            "drafts": drafts,
            "people": people,
            "tags": tags,
            "epics": epics,
            "issues": [{"key": issue["key"], "title": issue["title"]} for issue in issues],
        }

    def drafts(self, job_id, refresh=False):
        """저장한 초안을 돌려준다. 회의록이나 화자 이름이 바뀌었거나 refresh면 새로 만든다."""
        self.require()
        job = self.jobs.get(job_id)
        self.jobs.require_done(job)
        notes = self.jobs.named_notes(job)
        actions = action_items(notes)
        if not actions:
            raise AppError("회의록에 등록할 할 일이 없어요.")
        fingerprint = hashlib.sha256(notes.encode()).hexdigest()
        cache = self.jobs.store.path(job_id) / DRAFTS_FILE
        try:
            saved = json.loads(cache.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            saved = None
        if refresh or not saved or saved.get("fingerprint") != fingerprint:
            # 창을 닫았다 다시 열어도 초안을 두 번 만들지 않도록, 만드는 중이면 그 결과를 함께 기다린다.
            with self.lock:
                future = self.drafting.get(job_id)
                owner = future is None
                if owner:
                    future = self.drafting[job_id] = Future()
            if owner:
                try:
                    saved = {"fingerprint": fingerprint, "drafted_at": now(), **self.make(job, notes, actions)}
                    cache.write_text(json.dumps(saved, ensure_ascii=False), encoding="utf-8")
                    future.set_result(saved)
                except BaseException as error:
                    future.set_exception(error)
                finally:
                    with self.lock:
                        self.drafting.pop(job_id, None)
            saved = future.result()
        body = {key: value for key, value in saved.items() if key != "fingerprint"}
        return {**body, "registered": self.with_urls(job.get("issues") or [])}

    def register(self, job_id, create, comments):
        """고른 초안을 등록한다. create와 comments는 항목마다 source(할 일 번호)가 든 dict 목록이다."""
        self.require()
        tracker = self.tracker
        job = self.jobs.get(job_id)
        self.jobs.require_done(job)
        if not create and not comments:
            raise AppError("등록할 항목을 골라 주세요.")
        for item in create:
            if item["category"] not in (tracker.categories or [""]) or item["priority"] not in (tracker.priorities or [""]):
                raise Invalid("분류나 우선순위가 이 트래커에 없는 값이에요.")
        store = self.jobs.store
        results = []
        try:
            if create:
                payload = [{key: value for key, value in item.items() if key != "source" and value not in ("", [])} for item in create]
                keys = tracker.create(payload)
                if len(keys) != len(payload):
                    logger.warning("작업 %s: 이슈 %d건을 등록했는데 키는 %d개만 받았다", job_id, len(payload), len(keys))
                for item, key in zip(create, keys):
                    results.append({"source": item["source"], "kind": "create", "key": key, "title": item["title"]})
            for comment in comments:
                tracker.comment(comment["key"], comment["text"])
                results.append({"source": comment["source"], "kind": "comment", "key": comment["key"], "title": ""})
        except (TrackerError, OSError) as error:
            logger.error("작업 %s 이슈 등록에 실패했다", job_id, exc_info=error)
            if not results:
                raise Upstream(f"{tracker.name}에 등록하지 못했어요: {error}") from error
            store.update(job_id, issues=(job.get("issues") or []) + [{**r, "at": now()} for r in results])
            raise Upstream(
                f"{len(results)}건은 등록했지만 나머지는 등록하지 못했어요: {error}. "
                f"{tracker.name}에서 확인한 뒤 다시 시도해 주세요."
            ) from error
        registered = (job.get("issues") or []) + [{**result, "at": now()} for result in results]
        store.update(job_id, issues=registered)
        return {"results": self.with_urls(results), "registered": self.with_urls(registered)}
