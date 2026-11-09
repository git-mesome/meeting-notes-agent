"""팀원과 나눌 회의록 HTML을 만든다.

녹음을 듣지 않은 사람이 읽는 문서이므로 전사문과 근거 시각, 작성자가 검토할 "확인 필요"는 뺀다.
메일에 붙이거나 그대로 열 수 있게 스크립트 없이 스타일만 담은 파일 하나로 만든다.
"""

import html
import re
from datetime import datetime, timedelta, timezone

# 회의 날짜는 한국 시간으로 적는다. 한국은 서머타임이 없어 고정 시차로 충분하다.
KST = timezone(timedelta(hours=9), "KST")
TIME_REF = re.compile(r"\s*\[\d{1,2}:\d{2}(?::\d{2})?(?:\s*[-~–]\s*\d{1,2}:\d{2}(?::\d{2})?)?\]")
# 앱과 같은 글꼴. 인터넷이 없으면 시스템 글꼴(맑은 고딕 등)로 보인다.
FONT_URL = "https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/variable/pretendardvariable-dynamic-subset.min.css"
# 공유본에서 빼는 절과 표 열
HIDDEN_SECTIONS = ("확인 필요",)
HIDDEN_COLUMNS = ("근거",)

STYLE = """
body { margin: 0; background: #f2f4f6; color: #333d4b; font: 16px/1.7 "Pretendard Variable", Pretendard, -apple-system,
  "Apple SD Gothic Neo", "Malgun Gothic", "Noto Sans KR", sans-serif; word-break: keep-all; overflow-wrap: anywhere; }
main { max-width: 760px; margin: 0 auto; padding: 40px 24px 56px; }
header { margin-bottom: 24px; }
h1 { margin: 0 0 6px; color: #191f28; font-size: 26px; line-height: 1.35; }
.meta { margin: 0; color: #6b7684; font-size: 14px; }
section { margin-top: 16px; padding: 22px 24px; border-radius: 18px; background: #fff; }
h2 { margin: 0 0 10px; color: #191f28; font-size: 19px; }
h3 { margin: 18px 0 4px; color: #191f28; font-size: 16px; }
h2 + h3 { margin-top: 4px; }
ul, ol { margin: 0; padding-left: 20px; }
li { margin: 2px 0; }
p { margin: 0 0 8px; }
strong { color: #191f28; }
table { width: 100%; border-collapse: collapse; font-size: 15px; }
th, td { padding: 9px 8px; border-bottom: 1px solid #e5e8eb; text-align: left; vertical-align: top; }
th { color: #6b7684; font-size: 13px; font-weight: 600; }
footer { margin-top: 20px; color: #8b95a1; font-size: 13px; text-align: center; }
@media print { body { background: #fff; } section { padding: 0; margin-top: 20px; } }
"""


def inline(text):
    """**굵게**만 살리고 나머지는 글자 그대로 보이게 한다."""
    parts = re.split(r"\*\*(.+?)\*\*", text)
    return "".join(f"<strong>{html.escape(part)}</strong>" if index % 2 else html.escape(part) for index, part in enumerate(parts))


def cells(line):
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def render_table(lines):
    header = cells(lines[0])
    keep = [index for index, name in enumerate(header) if name not in HIDDEN_COLUMNS]
    rows = [cells(line) for line in lines[1:] if not set(line.replace("|", "").strip()) <= set("-: ")]
    head = "".join(f"<th>{inline(header[index])}</th>" for index in keep)
    body = "".join(
        "<tr>" + "".join(f"<td>{inline(row[index]) if index < len(row) else ''}</td>" for index in keep) + "</tr>"
        for row in rows
    )
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


def render_body(markdown):
    """회의록에 쓰는 마크다운(제목, 목록, 표, 굵게)만 HTML로 바꾼다."""
    out, block, kind = [], [], None

    def flush():
        nonlocal block, kind
        if kind == "ul":
            out.append("<ul>" + "".join(f"<li>{inline(item)}</li>" for item in block) + "</ul>")
        elif kind == "ol":
            out.append("<ol>" + "".join(f"<li>{inline(item)}</li>" for item in block) + "</ol>")
        elif kind == "table":
            out.append(render_table(block))
        block, kind = [], None

    for raw in markdown.splitlines():
        line = raw.strip()
        if line.startswith("|"):
            if kind != "table":
                flush()
            kind = "table"
            block.append(line)
            continue
        bullet = re.match(r"^[-*]\s+(.*)", line)
        number = re.match(r"^\d+[.)]\s+(.*)", line)
        if bullet or number:
            wanted = "ul" if bullet else "ol"
            if kind != wanted:
                flush()
            kind = wanted
            block.append((bullet or number).group(1))
            continue
        flush()
        if not line:
            continue
        if line.startswith("### "):
            out.append(f"<h3>{inline(line[4:])}</h3>")
        elif line.startswith("## "):
            out.append(f"<h2>{inline(line[3:])}</h2>")
        elif not line.startswith("# "):
            out.append(f"<p>{inline(line)}</p>")
    flush()
    return "\n".join(out)


def share_sections(notes):
    """제목 줄을 빼고, 근거 시각과 공유하지 않는 절을 지운 뒤 절(##)마다 나눈다."""
    text = TIME_REF.sub("", notes)
    sections = re.split(r"^(?=## )", text, flags=re.M)
    kept = []
    for section in sections:
        heading = section.split("\n", 1)[0].removeprefix("## ").strip()
        if not section.startswith("## ") or heading.startswith(HIDDEN_SECTIONS):
            continue
        kept.append(section)
    return kept


def render_share_html(title, created_at, duration_seconds, confirmed, notes):
    """공유용 HTML 문서 하나를 만든다. notes에는 화자 이름을 이미 넣어 둔다."""
    date = datetime.fromisoformat(created_at).astimezone(KST)
    minutes = max(1, round(duration_seconds / 60))
    meta = f"{date.year}년 {date.month}월 {date.day}일 · {minutes}분 회의"
    body = "\n".join(f"<section>\n{render_body(section)}\n</section>" for section in share_sections(notes))
    state = "확정본" if confirmed else "초안"
    return f"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)}</title>
<link rel="stylesheet" href="{FONT_URL}">
<style>{STYLE}</style>
</head>
<body>
<main>
<header>
<h1>{html.escape(title)}</h1>
<p class="meta">{html.escape(meta)}</p>
</header>
{body}
<footer>회의 녹음을 바탕으로 자동 작성 · {state}</footer>
</main>
</body>
</html>
"""
