"""파일 저장 도구."""

import os


def write_private(path, text):
    """본인만 읽을 수 있는 권한(600)으로 파일을 쓴다. 다 쓴 뒤에 바꿔 넣어 반쯤 쓴 파일이 남지 않게 한다."""
    temp = path.with_suffix(path.suffix + ".tmp")
    descriptor = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as out:
        out.write(text)
    os.replace(temp, path)
