"""회의에서 함께 본 자료를 회의록 프롬프트에 넣을 블록으로 만든다."""

import base64
import re
from html.parser import HTMLParser

DOCUMENTS_DIR = "documents"
# PDF와 이미지는 Claude가 그대로 읽는다. 웹 페이지는 글만 꺼내 보낸다. PPT나 엑셀은 PDF로 내보내 올린다.
DOCUMENT_TYPES = {
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".txt": "text/plain",
    ".md": "text/plain",
    ".html": "text/html",
    ".htm": "text/html",
}
TEXT_TYPES = ("text/plain", "text/html")
# API 요청 한도는 32MB이고 base64로 바꾸면 4/3배가 된다. 전사문 자리를 남긴다.
MAX_DOCUMENTS_BYTES = 20 * 1024**2
# API가 받는 이미지 한 장의 한도.
MAX_IMAGE_BYTES = 5 * 1024**2
SIGNATURES = {
    "application/pdf": lambda head: head.startswith(b"%PDF"),
    "image/png": lambda head: head.startswith(b"\x89PNG"),
    "image/jpeg": lambda head: head.startswith(b"\xff\xd8\xff"),
    "image/gif": lambda head: head.startswith(b"GIF8"),
    "image/webp": lambda head: head[:4] == b"RIFF" and head[8:12] == b"WEBP",
}
# 줄 앞에 붙인 표시만 있고 내용은 없는 줄
PREFIX_ONLY = re.compile(r"\s*(#{1,6}|-)?\s*")
HEADINGS = {"h1", "h2", "h3", "h4", "h5", "h6"}


class PageText(HTMLParser):
    """웹 페이지에서 글만 꺼낸다. 제목, 목록, 표는 마크다운처럼 줄을 나눠 남긴다."""

    SKIPPED = {"script", "style", "noscript", "template", "svg", "iframe"}
    BLOCKS = {
        "title", "p", "div", "section", "article", "header", "footer", "main", "aside", "nav", "blockquote", "pre",
        "ul", "ol", "li", "dl", "dt", "dd", "table", "tr", "br", "hr", "figure", "figcaption", *HEADINGS,
    }  # fmt: skip

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.lines = [""]
        self.skipping = 0

    def newline(self, prefix=""):
        if PREFIX_ONLY.fullmatch(self.lines[-1]):
            self.lines[-1] = prefix or self.lines[-1]
        else:
            self.lines.append(prefix)

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIPPED:
            self.skipping += 1
        elif self.skipping:
            return
        elif tag in HEADINGS:
            self.newline("#" * int(tag[1]) + " ")
        elif tag == "li":
            self.newline("- ")
        elif tag in ("td", "th"):
            self.lines[-1] += " | " if self.lines[-1].strip() else "| "
        elif tag == "img" and (alt := dict(attrs).get("alt")):
            self.lines[-1] += f" [이미지: {alt}] "
        elif tag in self.BLOCKS:
            self.newline()

    def handle_endtag(self, tag):
        if tag in self.SKIPPED:
            self.skipping = max(0, self.skipping - 1)
        elif not self.skipping and tag in self.BLOCKS:
            self.newline()

    def handle_data(self, data):
        if not self.skipping:
            self.lines[-1] += data

    def text(self):
        lines = (" ".join(line.split()) for line in self.lines)
        return "\n".join(line for line in lines if not PREFIX_ONLY.fullmatch(line))


def read_text(path):
    """한국어 윈도우에서 만든 파일은 UTF-8이 아닐 때가 있어 CP949로 다시 읽는다."""
    data = path.read_bytes()
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("cp949", errors="replace")


def document_text(path, media_type):
    text = read_text(path)
    if media_type == "text/html":
        page = PageText()
        page.feed(text)
        page.close()
        return page.text()
    return text


def document_problem(path, suffix):
    """API가 거절할 파일이면 화면에 보여 줄 이유를 돌려준다. 거절되면 회의록 쓰기 전체가 실패한다."""
    media_type = DOCUMENT_TYPES[suffix]
    with path.open("rb") as file:
        head = file.read(12)
    if media_type in SIGNATURES and not SIGNATURES[media_type](head):
        return f"파일 내용이 {suffix[1:]} 형식이 아니에요. 원본 파일을 올려 주세요."
    if media_type.startswith("image/") and path.stat().st_size > MAX_IMAGE_BYTES:
        return f"이미지는 한 장에 {MAX_IMAGE_BYTES // 1024**2}MB까지 붙일 수 있어요. 화면 캡처나 작은 사진으로 올려 주세요."
    if media_type in TEXT_TYPES and not document_text(path, media_type).strip():
        if media_type == "text/html":
            return "페이지에서 글을 찾지 못했어요. 브라우저에서 PDF로 저장해서 올려 주세요."
        return "파일 내용이 비어 있어요."
    return None


def find_documents(job_dir):
    """붙인 순서대로 자료 파일을 돌려준다."""
    folder = job_dir / DOCUMENTS_DIR
    if not folder.is_dir():
        return []
    files = [path for path in folder.iterdir() if path.is_file() and path.suffix.lower() in DOCUMENT_TYPES]
    return sorted(files, key=lambda path: (path.stat().st_mtime, path.name))


def document_blocks(paths):
    """자료마다 이름을 알리는 글 블록과 내용 블록을 만든다. 질문보다 앞에 둔다."""
    blocks = []
    for path in paths:
        media_type = DOCUMENT_TYPES[path.suffix.lower()]
        if media_type in TEXT_TYPES:
            source = {"type": "text", "media_type": "text/plain", "data": document_text(path, media_type)}
            blocks.append({"type": "document", "source": source, "title": path.name})
            continue
        data = base64.standard_b64encode(path.read_bytes()).decode("ascii")
        source = {"type": "base64", "media_type": media_type, "data": data}
        if media_type == "application/pdf":
            blocks.append({"type": "document", "source": source, "title": path.name})
        else:
            blocks.append({"type": "text", "text": f"회의 자료 이미지: {path.name}"})
            blocks.append({"type": "image", "source": source})
    return blocks
