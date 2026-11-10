"""화면에 보낼 작업 정보. 대기 순서와 남은 시간을 붙인다."""

from datetime import datetime, timezone

from meeting_notes.jobs.store import ACTIVE_STATUSES

# 노트북 CPU에서 large-v3로 잰 값이다. 음성 1초를 처리하는 데 2.2~2.7초가 걸렸다.
SECONDS_PER_AUDIO_SECOND = 2.5


def public_job(job, ahead=0):
    """화면에 보낼 항목만 고르고 남은 시간을 계산한다."""
    view = {
        key: job.get(key)
        for key in ("id", "name", "title", "status", "created_at", "duration_seconds", "error", "confirmed_at")
    }
    view["private"] = bool(job.get("private"))
    view["ahead"] = ahead
    view["estimated_seconds"] = job["duration_seconds"] * SECONDS_PER_AUDIO_SECOND
    view["elapsed_seconds"] = None
    if job["status"] == "transcribing":
        started = datetime.fromisoformat(job["stage_started_at"])
        view["elapsed_seconds"] = (datetime.now(timezone.utc) - started).total_seconds()
    return view


def public_jobs(store, visible=lambda job: True):
    """visible이 거르는 회의는 빼되, 대기 순서는 보이지 않는 회의까지 세어 매긴다."""
    jobs = store.all()
    active = sorted((j for j in jobs if j["status"] in ACTIVE_STATUSES), key=lambda j: j["created_at"])
    position = {job["id"]: index for index, job in enumerate(active)}
    return [public_job(job, position.get(job["id"], 0)) for job in jobs if visible(job)]
