"""회의록의 할 일을 올릴 이슈 트래커의 규격.

트래커마다 회사 폴더에 어댑터 파일 하나를 두고 company.toml의 [tracker]에서 고른다.

    [tracker]
    module = "jira"      # company/jira.py
    url = "..."          # 나머지 값은 어댑터의 create(settings)에 그대로 넘어간다

어댑터 파일에는 Tracker를 상속한 클래스와, 설정을 받아 그 객체를 돌려주는 create(settings) 함수를 둔다.
토큰은 company.toml이 아니라 .env에 두고 어댑터가 환경 변수에서 읽는다. 예시는 company.example/에 있다.
"""

import importlib.util


class TrackerError(Exception):
    """트래커가 요청을 처리하지 못했다. 메시지는 화면에 그대로 보인다."""


class Tracker:
    # 화면 문구에 쓰는 이름. 예: "Jira에 등록"
    name = "이슈 트래커"
    # 이슈가 올라가는 곳. 예: "WEB 프로젝트". 비우면 안내에서 뺀다.
    destination = ""
    # 이슈 분류와 우선순위로 고를 수 있는 값. 비우면 그 항목을 쓰지 않는다.
    categories = []
    priorities = []
    # 이슈 설명 양식처럼 초안을 쓸 때 더할 규칙
    guide = ""
    # 등록한 뒤 화면에 보여 줄 안내
    after_register = ""

    def issue_url(self, key):
        """이슈를 열 주소. 없으면 빈 문자열."""
        return ""

    def people(self):
        """담당자로 고를 수 있는 사람 이름 목록."""
        raise NotImplementedError

    def tags(self):
        """태그(레이블) 이름 목록."""
        raise NotImplementedError

    def open_issues(self):
        """열린 이슈 목록. 항목마다 key, title, type, status, tags, assignees를 둔다.

        type이 "epic"인 이슈는 새 이슈의 상위 이슈로 고를 수 있다.
        """
        raise NotImplementedError

    def issue(self, key):
        """이슈 하나. 같은 일을 다루는 이슈를 찾는 데 description을 쓴다."""
        raise NotImplementedError

    def create(self, issues):
        """이슈를 한 번에 만들고 새 이슈 키를 같은 순서로 돌려준다.

        항목마다 title, description이 있고 category, priority, assignees, tags, parent, due_date는 값이 있을 때만 들어온다.
        """
        raise NotImplementedError

    def comment(self, key, text):
        raise NotImplementedError


def load_tracker(root, settings):
    """회사 폴더의 어댑터 파일을 읽어 트래커를 만든다. 어댑터가 None을 돌려주면 연동하지 않는다."""
    name = settings["module"]
    spec = importlib.util.spec_from_file_location(f"company_tracker_{name}", root / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.create(settings)
