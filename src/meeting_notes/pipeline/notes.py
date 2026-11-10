"""전사문을 Claude에 보내 회의록을 받는다."""

import re

from meeting_notes import llm
from meeting_notes.pipeline.documents import document_blocks
from meeting_notes.pipeline.knowledge import load_knowledge
from meeting_notes.pipeline.spelling import fix_spelling
from meeting_notes.pipeline.templates import DEFAULT_TEMPLATE, system_prompt

# 회의록 길이 상한. 사람이 쓴 회의록은 전사문의 20% 안팎이었다.
NOTES_LENGTH_RATIO = 0.2
MIN_NOTES_CHARS = 800


def write_notes(transcript, glossary, template=DEFAULT_TEMPLATE, facts=(), documents=()):
    """documents는 회의에서 함께 본 자료 파일(pipeline/documents.py)이다."""
    user = f"<transcript>\n{transcript}\n</transcript>"
    if glossary:
        user = f"<glossary>\n{chr(10).join(glossary)}\n</glossary>\n\n{user}"
    knowledge = load_knowledge(transcript, facts=facts)
    if knowledge:
        user = f"<company_knowledge>\n{knowledge}\n</company_knowledge>\n\n{user}"
    max_chars = max(MIN_NOTES_CHARS, int(len(transcript) * NOTES_LENGTH_RATIO))
    system = system_prompt(template, max_chars, documents=bool(documents))
    content = [*document_blocks(documents), {"type": "text", "text": user}] if documents else user
    notes, usage = llm.stream("회의록 생성", system, content, "high", 64000)
    return fix_spelling(notes), usage


def notes_title(notes, fallback):
    """회의록 첫 줄의 "# 회의록: 제목"에서 제목을 꺼낸다."""
    first_line = notes.strip().splitlines()[0] if notes.strip() else ""
    title = re.sub(r"^#\s*(회의록\s*:\s*)?", "", first_line).strip() if first_line.startswith("#") else ""
    return title or fallback
