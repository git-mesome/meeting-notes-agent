"""회의록의 액션 아이템 표를 읽는다."""

import re


def action_items(notes):
    """회의록의 액션 아이템 표를 행 목록으로 읽는다."""
    section = re.search(r"^## 액션 아이템\s*$(.*?)(?=^## |\Z)", notes, re.M | re.S)
    if not section:
        return []
    rows = []
    for line in section.group(1).splitlines():
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if not line.strip().startswith("|") or len(cells) < 2 or cells[0] == "담당" or set("".join(cells)) <= set("-: "):
            continue
        cells += [""] * (4 - len(cells))
        rows.append({"index": len(rows), "owner": cells[0], "task": cells[1], "due": cells[2], "evidence": cells[3]})
    return rows
