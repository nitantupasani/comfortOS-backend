"""AI chat request/response schemas for the /ai/chat endpoint."""

from typing import Literal

from pydantic import BaseModel, Field


class AiChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=8000)


class AiChatRequest(BaseModel):
    messages: list[AiChatMessage] = Field(min_length=1, max_length=40)
    buildingId: str | None = Field(default=None, max_length=50)


class AiChatResponse(BaseModel):
    reply: str
