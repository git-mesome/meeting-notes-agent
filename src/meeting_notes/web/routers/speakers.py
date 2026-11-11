"""화자 이름과 등록한 목소리."""

from fastapi import APIRouter

from meeting_notes.web.deps import Admins, Jobs, User, Voices
from meeting_notes.web.schemas import SpeakerName

router = APIRouter(prefix="/api")


@router.put("/jobs/{job_id}/speakers/{label}")
def rename_speaker(job_id: str, label: str, body: SpeakerName, jobs: Jobs):
    return jobs.rename_speaker(job_id, label, body.name, body.remember)


@router.get("/voices")
def list_voices(voices: Voices, user: User, admins: Admins):
    return voices.list(user, admins)


@router.delete("/voices/{voice_id}")
def delete_voice(voice_id: str, voices: Voices, user: User, admins: Admins):
    voices.delete(voice_id, user, admins)
    return {"ok": True}
