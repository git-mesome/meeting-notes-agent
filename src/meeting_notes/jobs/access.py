"""회의별 권한. 로그인을 켰을 때만 따진다. 사용자가 없으면 로그인이 꺼진 것이라 모두 할 수 있다.

| 할 일 | 할 수 있는 사람 |
|---|---|
| 보기: 회의록, 녹음, 전사문, 자료 내려받기, 질문, 검색 | 로그인한 사람 모두. "참석자만 보기"를 켠 회의는 고칠 수 있는 사람만 |
| 고치기: 회의록, 확인 필요, 화자 이름, 확정, 다시 쓰기, 자료, 이슈 등록, 중지와 다시 시작 | 올린 사람, 참석자, 관리자 |
| 관리: 지우기, 참석자와 공개 범위 정하기 | 올린 사람, 관리자 |

참석자는 올린 사람이 정한다(JobService.set_access). 로그인을 켜기 전에 올린 회의는 올린 사람이 없어 관리자만
고치고 관리한다. 관리자는 company.toml [auth]의 admin_subs다.
"""

from meeting_notes.errors import Forbidden, NotFound

VIEW, EDIT, MANAGE = "view", "edit", "manage"
DENIED = {
    EDIT: "이 회의록은 올린 사람과 참석자만 고칠 수 있어요.",
    MANAGE: "회의를 올린 사람만 할 수 있어요.",
}


def access(job, user, admins=frozenset()):
    """user가 이 회의에서 할 수 있는 일. 화면은 이 값을 받아 할 수 없는 버튼을 숨긴다."""
    if user is None:
        return {VIEW: True, EDIT: True, MANAGE: True}
    sub = str(user["sub"])
    owner = (job.get("owner") or {}).get("sub")
    manage = sub in admins or (owner is not None and sub == str(owner))
    edit = manage or any(str(person["sub"]) == sub for person in job.get("attendees") or [])
    return {VIEW: edit or not job.get("private"), EDIT: edit, MANAGE: manage}


def require(job, user, admins, level):
    allowed = access(job, user, admins)
    if not allowed[VIEW]:
        # 참석자만 보는 회의는 있다는 것도 알리지 않는다.
        raise NotFound("회의록을 찾을 수 없어요.")
    if not allowed[level]:
        raise Forbidden(DENIED[level])
