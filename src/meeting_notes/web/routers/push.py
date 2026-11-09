"""웹 푸시 구독."""

from fastapi import APIRouter

from meeting_notes.web.deps import Push
from meeting_notes.web.schemas import PushEndpoint, PushSubscription

router = APIRouter(prefix="/api/push")


@router.get("/key")
def push_key(push: Push):
    return {"key": push.public_key()}


@router.post("/subscribe")
def push_subscribe(body: PushSubscription, push: Push):
    push.subscribe(body.model_dump())
    return {"ok": True}


@router.post("/unsubscribe")
def push_unsubscribe(body: PushEndpoint, push: Push):
    push.unsubscribe(body.endpoint)
    return {"ok": True}
