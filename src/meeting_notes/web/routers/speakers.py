"""화자 이름과 등록한 목소리."""

from fastapi import APIRouter

from meeting_notes.errors import NotFound
from meeting_notes.web.deps import Jobs, Voices
from meeting_notes.web.schemas import SpeakerName

router = APIRouter(prefix="/api")


@router.put("/jobs/{job_id}/speakers/{label}")
def rename_speaker(job_id: str, label: str, body: SpeakerName, jobs: Jobs):
    return jobs.rename_speaker(job_id, label, body.name, body.remember)


@router.get("/voices")
def list_voices(voices: Voices):
    return voices.list()


@router.delete("/voices/{voice_id}")
def delete_voice(voice_id: str, voices: Voices):
    if not voices.delete(voice_id):
        raise NotFound("등록된 목소리를 찾을 수 없어요.")
    return {"ok": True}
