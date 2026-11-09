"""회의록과 전사문 검색 도구."""

import re


def plain_text(markdown):
    """검색 결과에 보여 주려고 마크다운 기호와 근거 시각을 뺀다."""
    return re.sub(r"\[\d{1,2}:\d{2}(?::\d{2})?\]|[#|*]+|^\s*-+\s*$", " ", markdown, flags=re.M)


def search_pattern(query):
    """전사문은 띄어쓰기가 불규칙하므로 공백을 무시하고 찾는다."""
    letters = [re.escape(char) for char in query if not char.isspace()]
    return re.compile(r"\s*".join(letters), re.IGNORECASE) if letters else None


def snippet(text, match, around=40):
    start = max(0, match.start() - around)
    end = min(len(text), match.end() + around)
    body = " ".join(text[start:end].split())
    return f"{'…' if start else ''}{body}{'…' if end < len(text) else ''}"
