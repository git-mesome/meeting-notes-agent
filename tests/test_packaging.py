import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent


def test_source_files_are_not_ignored_by_git():
    """데이터 폴더용 .gitignore 규칙이 같은 이름의 코드 폴더(jobs 패키지 등)를 빼먹지 않는지 확인한다."""
    if not (ROOT / ".git").exists():
        pytest.skip("git 저장소가 아니다")
    result = subprocess.run(
        ["git", "ls-files", "--others", "--ignored", "--exclude-standard", "src"],
        cwd=ROOT, capture_output=True, text=True, check=True,
    )
    assert [path for path in result.stdout.split() if "__pycache__" not in path] == []
