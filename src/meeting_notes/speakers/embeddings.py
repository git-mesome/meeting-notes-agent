"""회의별 화자 목소리 특징. 생체 정보이므로 본인만 읽을 수 있게 저장한다."""

import json

from meeting_notes.files import write_private

EMBEDDINGS_FILE = "speaker_embeddings.json"


def extract_embeddings(job_dir):
    """전사 결과에서 화자별 목소리 특징을 꺼내 따로 저장한다."""
    transcript_json = job_dir / "audio.json"
    if not transcript_json.exists():
        return {}
    embeddings = json.loads(transcript_json.read_text(encoding="utf-8")).get("speaker_embeddings") or {}
    if embeddings:
        write_private(job_dir / EMBEDDINGS_FILE, json.dumps(embeddings))
    return embeddings


def load_embeddings(job_dir):
    path = job_dir / EMBEDDINGS_FILE
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
