"""AI chat request/response schemas for the /ai/chat endpoints."""

from typing import Literal

from pydantic import BaseModel, Field


class AiChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=8000)


class AiChatRequest(BaseModel):
    messages: list[AiChatMessage] = Field(min_length=1, max_length=40)
    buildingId: str | None = Field(default=None, max_length=50)
    sessionId: str | None = Field(
        default=None,
        max_length=50,
        description="If provided, the exchange is persisted into this session.",
    )


class AiChatResponse(BaseModel):
    reply: str
    sessionId: str | None = None


class ChatSessionCreate(BaseModel):
    buildingId: str | None = Field(default=None, max_length=50)
    title: str | None = Field(default=None, max_length=200)


class ChatSessionUpdate(BaseModel):
    title: str = Field(min_length=1, max_length=200)


class ChatMessageOut(BaseModel):
    id: str
    role: Literal["user", "assistant"]
    content: str
    createdAt: str


class ChatSessionSummary(BaseModel):
    id: str
    title: str
    buildingId: str | None
    buildingName: str | None
    createdAt: str
    lastMessageAt: str
    messageCount: int


class ChatSessionDetail(ChatSessionSummary):
    messages: list[ChatMessageOut]
