"""회의에서 함께 본 자료 붙이기."""

import base64
import threading

import pytest

from meeting_notes import llm
from meeting_notes.pipeline import process
from meeting_notes.pipeline.documents import find_documents
from meeting_notes.pipeline.notes import write_notes
from meeting_notes.pipeline.templates import DOCUMENT_RULES
from meeting_notes.web.routers import jobs as jobs_router
from tests.test_app import client, fake_process, make_client, tone, upload, wait_for  # noqa: F401
from tests.test_process_audio import pipeline  # noqa: F401

PDF = b"%PDF-1.4 example"
PNG = b"\x89PNG\r\n\x1a\n example"


def attach(client, job_id, name, body=PDF):
    return client.post(f"/api/jobs/{job_id}/documents", files={"file": (name, body, "application/octet-stream")})


@pytest.fixture
def captured(monkeypatch):
    captured = {}

    class Block:
        type = "text"
        text = "# 회의록: 예시"

    class Message:
        stop_reason = "end_turn"
        content = [Block()]
        usage = None

    class Stream:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def get_final_message(self):
            return Message()

    class Client:
        class beta:
            class messages:
                @staticmethod
                def stream(**kwargs):
                    captured.update(kwargs)
                    return Stream()

    monkeypatch.setattr(llm.anthropic, "Anthropic", Client)
    return captured


def test_write_notes_sends_documents_before_transcript(tmp_path, captured):
    (tmp_path / "기획서.pdf").write_bytes(PDF)
    (tmp_path / "화면.png").write_bytes(PNG)
    (tmp_path / "메모.md").write_text("# 메모", encoding="utf-8")
    documents = [tmp_path / "기획서.pdf", tmp_path / "화면.png", tmp_path / "메모.md"]

    write_notes("전사문", [], documents=documents)

    content = captured["messages"][0]["content"]
    assert content[0] == {
        "type": "document",
        "source": {"type": "base64", "media_type": "application/pdf", "data": base64.b64encode(PDF).decode()},
        "title": "기획서.pdf",
    }
    assert content[1] == {"type": "text", "text": "회의 자료 이미지: 화면.png"}
    assert content[2]["type"] == "image" and content[2]["source"]["media_type"] == "image/png"
    assert content[3]["source"] == {"type": "text", "media_type": "text/plain", "data": "# 메모"}
    assert content[-1]["type"] == "text" and "<transcript>\n전사문\n</transcript>" in content[-1]["text"]
    assert DOCUMENT_RULES in captured["system"]


def test_write_notes_without_documents_is_unchanged(captured):
    write_notes("전사문", [])
    assert isinstance(captured["messages"][0]["content"], str)
    assert DOCUMENT_RULES not in captured["system"]


def test_documents_are_loaded_after_transcription(tmp_path, pipeline):  # noqa: F811
    loaded = []

    def load_documents():
        loaded.append(pipeline.transcribe)
        return ["자료.pdf"]

    process.process_audio(tmp_path / "audio.m4a", tmp_path, [], load_documents=load_documents)
    assert loaded == [1]
    assert pipeline.documents == ["자료.pdf"]


def test_document_attached_while_transcribing_is_used(tmp_path, tone):  # noqa: F811
    release = threading.Event()
    seen = []

    def slow_process(audio, out_dir, on_stage, on_process=None):
        on_stage("transcribing")
        release.wait(10)
        seen.append([path.name for path in find_documents(out_dir)])
        return fake_process(audio, out_dir, lambda _stage: None, on_process)

    with make_client(tmp_path, process=slow_process) as client:
        job_id = upload(client, tone)
        wait_for(client, job_id, "transcribing")
        response = attach(client, job_id, "기획서.pdf")
        assert response.status_code == 200
        assert response.json()["documents"] == [{"name": "기획서.pdf", "size": len(PDF)}]
        release.set()
        job = wait_for(client, job_id, "done")

    assert seen == [["기획서.pdf"]]
    assert job["documents_pending"] is False


def test_document_attached_after_notes_asks_for_rewrite(tmp_path, tone):  # noqa: F811
    with make_client(tmp_path) as client:
        job_id = upload(client, tone)
        wait_for(client, job_id, "done")

        assert attach(client, job_id, "기획서.pdf").json()["documents_pending"] is True
        client.post(f"/api/jobs/{job_id}/regenerate", json={"template": "general"})
        assert wait_for(client, job_id, "done")["documents_pending"] is False

        response = client.delete(f"/api/jobs/{job_id}/documents/기획서.pdf")
        assert response.status_code == 200
        assert response.json()["documents"] == []
        assert response.json()["documents_pending"] is True


def test_document_names_are_cleaned_and_kept_apart(client, tone):  # noqa: F811
    job_id = upload(client, tone)
    attach(client, job_id, "../회의:자료.PDF")
    documents = attach(client, job_id, "회의:자료.pdf").json()["documents"]
    assert [doc["name"] for doc in documents] == ["회의_자료.pdf", "회의_자료 (2).pdf"]

    response = client.get(f"/api/jobs/{job_id}/documents/회의_자료.pdf")
    assert response.status_code == 200
    assert response.content == PDF


@pytest.mark.parametrize("name", ["../meta.json", "meta.json", "없는 자료.pdf"])
def test_only_attached_documents_can_be_read(client, tone, name):  # noqa: F811
    job_id = upload(client, tone)
    assert client.get(f"/api/jobs/{job_id}/documents/{name}").status_code == 404
    assert client.delete(f"/api/jobs/{job_id}/documents/{name}").status_code == 404


def test_rejects_unsupported_document(client, tone, tmp_path):  # noqa: F811
    job_id = upload(client, tone)
    response = attach(client, job_id, "발표.pptx")
    assert response.status_code == 400
    assert "PDF" in response.json()["detail"]
    assert client.get(f"/api/jobs/{job_id}").json()["documents"] == []
    assert list((tmp_path / job_id / "documents").iterdir()) == []


@pytest.mark.parametrize(
    ("name", "body", "message"),
    [("기획서.pdf", PNG, "pdf 형식이 아니에요"), ("화면.png", b"not an image", "png 형식이 아니에요")],
)
def test_rejects_document_whose_content_does_not_match(client, tone, name, body, message):  # noqa: F811
    job_id = upload(client, tone)
    response = attach(client, job_id, name, body)
    assert response.status_code == 400
    assert message in response.json()["detail"]


def test_rejects_large_image(client, tone, monkeypatch):  # noqa: F811
    monkeypatch.setattr("meeting_notes.pipeline.documents.MAX_IMAGE_BYTES", len(PNG) - 1)
    job_id = upload(client, tone)
    assert attach(client, job_id, "화면.png", PNG).status_code == 400
    assert attach(client, job_id, "기획서.pdf").status_code == 200


def test_rejects_documents_over_total_limit(client, tone, tmp_path, monkeypatch):  # noqa: F811
    monkeypatch.setattr(jobs_router, "MAX_DOCUMENTS_BYTES", len(PDF) * 3)
    monkeypatch.setattr("meeting_notes.jobs.service.MAX_DOCUMENTS_BYTES", len(PDF) * 3)
    job_id = upload(client, tone)
    assert attach(client, job_id, "하나.pdf").status_code == 200
    assert attach(client, job_id, "둘.pdf").status_code == 200
    assert attach(client, job_id, "셋.pdf", PDF * 2).status_code == 413
    assert attach(client, job_id, "넷.pdf", PDF * 4).status_code == 413
    assert [doc["name"] for doc in client.get(f"/api/jobs/{job_id}").json()["documents"]] == ["하나.pdf", "둘.pdf"]
    assert sorted(path.name for path in (tmp_path / job_id / "documents").iterdir()) == ["둘.pdf", "하나.pdf"]


# 웹 페이지

PAGE = """<html><head><title>3분기 계획</title><style>.x{color:red}</style><script>alert(1)</script></head>
<body><h2>교체 순서</h2><ul><li><p>본사: FG-200F</p></li><li>지점 2주 &amp; 간격</li></ul>
<table><tr><th>지점</th><th>날짜</th></tr><tr><td>판교</td><td>9/26</td></tr></table>
<p>구성도 <img alt="망 구성도" src="a.png"> 참고<br>둘째 줄</p></body></html>"""
PAGE_TEXT = """3분기 계획
## 교체 순서
- 본사: FG-200F
- 지점 2주 & 간격
| 지점 | 날짜
| 판교 | 9/26
구성도 [이미지: 망 구성도] 참고
둘째 줄"""


def test_web_page_is_sent_as_its_text(tmp_path, captured):
    page = tmp_path / "계획.html"
    page.write_text(PAGE, encoding="utf-8")
    write_notes("전사문", [], documents=[page])
    assert captured["messages"][0]["content"][0] == {
        "type": "document",
        "source": {"type": "text", "media_type": "text/plain", "data": PAGE_TEXT},
        "title": "계획.html",
    }


def test_text_saved_in_cp949_is_read(tmp_path, captured):
    memo = tmp_path / "메모.txt"
    memo.write_bytes("지점 순서: 판교".encode("cp949"))
    write_notes("전사문", [], documents=[memo])
    assert captured["messages"][0]["content"][0]["source"]["data"] == "지점 순서: 판교"


def test_web_page_is_only_downloaded(client, tone):  # noqa: F811
    job_id = upload(client, tone)
    assert attach(client, job_id, "계획.HTM", PAGE.encode()).json()["documents"][0]["name"] == "계획.htm"
    response = client.get(f"/api/jobs/{job_id}/documents/계획.htm")
    assert response.headers["content-type"] == "application/octet-stream"
    assert response.headers["content-disposition"].startswith("attachment")


@pytest.mark.parametrize(
    ("name", "body", "message"),
    [
        ("빈 페이지.html", b"<html><script>render()</script></html>", "PDF로 저장"),
        ("빈 메모.txt", b" \n", "비어 있어요"),
    ],
)
def test_rejects_document_without_text(client, tone, name, body, message):  # noqa: F811
    job_id = upload(client, tone)
    response = attach(client, job_id, name, body)
    assert response.status_code == 400
    assert message in response.json()["detail"]
