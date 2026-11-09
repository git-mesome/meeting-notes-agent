"""AI가 기억하는 내용: 사용자가 확인 필요 항목을 확인하며 남긴 사실."""

from fastapi import APIRouter

from meeting_notes.errors import NotFound
from meeting_notes.web.deps import Memory

router = APIRouter(prefix="/api/memory")


@router.get("")
def list_memory(memory: Memory):
    return memory.list()


@router.delete("/{item_id}")
def delete_memory(item_id: str, memory: Memory):
    if not memory.delete(item_id):
        raise NotFound("기억한 내용을 찾을 수 없어요.")
    return {"ok": True}
