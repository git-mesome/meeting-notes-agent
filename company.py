"""회사마다 다른 설정을 회사 폴더 하나에서 읽는다.

회사 폴더는 기본으로 프로젝트의 company/를 쓰고, 환경 변수 COMPANY_DIR로 바꿀 수 있다. 사내 정보가 들어가므로
커밋하지 않는다. 구조와 설정 항목은 company.example/을 본다.

    company/
      company.toml   접속 허용 주소, 표기 규칙, 이슈 트래커 설정
      knowledge/     회의록을 쓸 때 참고할 배경 지식(meeting_context.md)과 용어 사전(terms.json)
      glossary.txt   전사할 때 알려 줄 기술 용어
      <어댑터>.py    이슈 트래커 어댑터(trackers.py의 규격을 따른다)
"""

import os
import tomllib
from functools import cache
from pathlib import Path

DEFAULT_DIR = Path(__file__).parent / "company"
DEFAULT_ALLOWED_HOSTS = ["127.0.0.1", "localhost", "*.ts.net"]
# 회사와 관계없이 지키는 표기. company.toml의 [spelling]이 여기에 더해진다.
DEFAULT_SPELLING = {"에이아이": "AI"}


class Company:
    def __init__(self, root):
        self.root = Path(root)
        path = self.root / "company.toml"
        self.config = tomllib.loads(path.read_text(encoding="utf-8")) if path.exists() else {}

    @property
    def knowledge_dir(self):
        return self.root / "knowledge"

    @property
    def glossary(self):
        path = self.root / "glossary.txt"
        if not path.exists():
            return []
        return [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]

    @property
    def allowed_hosts(self):
        return self.config.get("server", {}).get("allowed_hosts", DEFAULT_ALLOWED_HOSTS)

    @property
    def spelling(self):
        return {**DEFAULT_SPELLING, **self.config.get("spelling", {})}

    def tracker(self):
        """[tracker]에 적은 어댑터로 이슈 트래커를 만든다. 설정이 없으면 None."""
        from trackers import load_tracker

        settings = self.config.get("tracker")
        return load_tracker(self.root, settings) if settings else None


@cache
def current():
    return Company(os.environ.get("COMPANY_DIR") or DEFAULT_DIR)
