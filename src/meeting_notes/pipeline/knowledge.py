"""회사 폴더의 배경 지식과 용어를 프롬프트에 넣을 글로 만든다."""

import json
import re
from pathlib import Path

from meeting_notes import settings
from meeting_notes.pipeline.spelling import fix_spelling

MAX_TERM_DEFINITIONS = 40
MAX_DEFINITION_CHARS = 200


def load_knowledge(transcript, root=None, facts=()):
    """용어는 이름을 모두 넣고, 정의는 전사문에 나온 것만 넣는다. facts는 사용자가 확인해 준 사실(memory.py)이다."""
    root = Path(root) if root else settings.current().knowledge_dir
    parts = []
    context = root / "meeting_context.md"
    if context.exists():
        parts.append(fix_spelling(context.read_text(encoding="utf-8").strip()))
    if facts:
        parts.append("## 사용자가 지난 회의에서 확인한 사실\n" + "\n".join(f"- {fact}" for fact in facts))
    terms_path = root / "terms.json"
    if terms_path.exists():
        terms = json.loads(terms_path.read_text(encoding="utf-8"))
        names = []
        for term in terms:
            extras = [term.get("term_en"), *(term.get("aliases") or [])]
            extras = [extra for extra in extras if extra and extra != term["term"]]
            names.append(f"{term['term']}({', '.join(extras)})" if extras else term["term"])
        parts.append("## 표준 용어\n" + ", ".join(names))

        spoken = re.sub(r"\s+", "", transcript).casefold()
        found = []
        for term in terms:
            candidates = [term["term"], term.get("term_en"), *(term.get("aliases") or [])]
            keys = [re.sub(r"\s+", "", word).casefold() for word in candidates if word]
            if any(len(key) >= 2 and key in spoken for key in keys):
                found.append(f"- {term['term']}: {term['definition'][:MAX_DEFINITION_CHARS]}")
        if found:
            parts.append("## 이 회의에 나온 용어의 뜻\n" + "\n".join(found[:MAX_TERM_DEFINITIONS]))
    return fix_spelling("\n\n".join(parts))


def load_glossary(path):
    lines = path.read_text(encoding="utf-8").splitlines()
    return [line.strip() for line in lines if line.strip()]
