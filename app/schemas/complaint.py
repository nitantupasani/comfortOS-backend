"""Pydantic schemas for complaints."""

from pydantic import BaseModel, Field


ComplaintTypeLiteral = str  # validated server-side against ComplaintType enum


class ComplaintCreate(BaseModel):
    buildingId: str
    complaintType: ComplaintTypeLiteral  # "hot" | "cold" | "air_quality" | "cleanliness" | "other"
    title: str = Field(min_length=1, max_length=200)
    description: str | None = None


class ComplaintCommentResponse(BaseModel):
    id: str
    complaintId: str
    authorId: str
    authorName: str
    authorRole: str
    body: str
    createdAt: str


class ComplaintCommentCreate(BaseModel):
    body: str = Field(min_length=1, max_length=2000)


class ComplaintResponse(BaseModel):
    id: str
    buildingId: str
    buildingName: str
    createdBy: str
    authorName: str
    complaintType: str
    title: str
    description: str | None
    createdAt: str
    cosignCount: int
    cosignerIds: list[str]
    viewerHasCosigned: bool
    comments: list[ComplaintCommentResponse]
