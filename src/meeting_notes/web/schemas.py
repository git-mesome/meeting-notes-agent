"""요청 본문 모델. 길이와 형식을 여기서 검사한다."""

from pydantic import BaseModel, Field


class NotesUpdate(BaseModel):
    notes: str = Field(min_length=1, max_length=1_000_000)


class CheckUpdate(BaseModel):
    done: bool
    note: str = Field(default="", max_length=300)
    remember: bool = False


class SpeakerName(BaseModel):
    name: str = Field(max_length=20)
    remember: bool = False


class Question(BaseModel):
    question: str = Field(min_length=1, max_length=500)


class Regenerate(BaseModel):
    template: str


class AccessUpdate(BaseModel):
    attendees: list[str] = Field(default_factory=list, max_length=100)
    private: bool = False


class IssueDraft(BaseModel):
    source: int
    title: str = Field(min_length=2, max_length=200)
    description: str = Field(min_length=1, max_length=20_000)
    category: str = Field(default="", max_length=40)
    priority: str = Field(default="", max_length=40)
    assignees: list[str] = Field(default_factory=list, max_length=20)
    tags: list[str] = Field(default_factory=list, max_length=8)
    parent: str = Field(default="", max_length=40)
    due_date: str = Field(default="", pattern=r"^(\d{4}-\d{2}-\d{2})?$")


class IssueComment(BaseModel):
    source: int
    key: str = Field(pattern=r"^[A-Za-z0-9#._-]{1,40}$")
    text: str = Field(min_length=1, max_length=10_000)


class IssueRegistration(BaseModel):
    create: list[IssueDraft] = Field(default_factory=list, max_length=20)
    comments: list[IssueComment] = Field(default_factory=list, max_length=20)


class PushKeys(BaseModel):
    p256dh: str = Field(max_length=300)
    auth: str = Field(max_length=100)


class PushSubscription(BaseModel):
    endpoint: str = Field(max_length=1000, pattern=r"^https://")
    keys: PushKeys


class PushEndpoint(BaseModel):
    endpoint: str = Field(max_length=1000)
