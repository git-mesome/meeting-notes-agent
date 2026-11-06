"""테스트가 이 노트북의 회사 폴더(company/)를 읽지 않도록 빈 회사 폴더를 쓴다."""

import os
import tempfile

import company

os.environ["COMPANY_DIR"] = tempfile.mkdtemp(prefix="company-")
company.current.cache_clear()
