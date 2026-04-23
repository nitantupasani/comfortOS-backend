"""AI assistant routes — /ai/chat, /ai/chat/public, /ai/sessions/*."""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from google.genai import errors as genai_errors
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..api.deps import get_current_user
from ..database import get_db
from ..models.building import Building
from ..models.chat_session import ChatMessage, ChatMessageRole, ChatSession
from ..models.user import User
from ..schemas.ai import (
    AiChatMessage,
    AiChatRequest,
    AiChatResponse,
    ChatMessageOut,
    ChatSessionCreate,
    ChatSessionDetail,
    ChatSessionSummary,
    ChatSessionUpdate,
)
from ..services.ai_chat import generate_public_reply, generate_reply
from ..services.ai_rate_limiter import ai_rate_limiter

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ai", tags=["ai"])


# ── Helpers ──────────────────────────────────────────────────────────────


def _session_summary(session: ChatSession, building_name: str | None) -> ChatSessionSummary:
    return ChatSessionSummary(
        id=session.id,
        title=session.title,
        buildingId=session.building_id,
        buildingName=building_name,
        createdAt=session.created_at.isoformat(),
        lastMessageAt=session.last_message_at.isoformat(),
        messageCount=session.message_count,
    )


def _session_detail(session: ChatSession, building_name: str | None) -> ChatSessionDetail:
    return ChatSessionDetail(
        **_session_summary(session, building_name).model_dump(),
        messages=[
            ChatMessageOut(
                id=m.id,
                role=m.role.value if hasattr(m.role, "value") else str(m.role),
                content=m.content,
                createdAt=m.created_at.isoformat(),
            )
            for m in session.messages
        ],
    )


async def _building_name(db: AsyncSession, building_id: str | None) -> str | None:
    if not building_id:
        return None
    res = await db.execute(select(Building.name).where(Building.id == building_id))
    return res.scalar_one_or_none()


async def _load_owned_session(
    db: AsyncSession, user: User, session_id: str
) -> ChatSession:
    res = await db.execute(select(ChatSession).where(ChatSession.id == session_id))
    session = res.scalar_one_or_none()
    if session is None or session.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
    return session


def _derive_title(messages: list[AiChatMessage]) -> str:
    for m in messages:
        if m.role == "user":
            cleaned = m.content.strip().replace("\n", " ")
            return (cleaned[:57] + "…") if len(cleaned) > 60 else (cleaned or "New chat")
    return "New chat"


def _client_ip(request: Request) -> str:
    """Resolve the caller IP, honouring X-Forwarded-For from Caddy / ngrok."""
    xff = request.headers.get("x-forwarded-for", "")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


# ── Session CRUD ─────────────────────────────────────────────────────────


@router.post("/sessions", response_model=ChatSessionDetail, status_code=status.HTTP_201_CREATED)
async def create_session(
    body: ChatSessionCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ChatSessionDetail:
    if body.buildingId:
        existing = await db.execute(
            select(Building).where(Building.id == body.buildingId)
        )
        if existing.scalar_one_or_none() is None:
            raise HTTPException(status_code=404, detail="Building not found")

    session = ChatSession(
        user_id=user.id,
        building_id=body.buildingId,
        title=(body.title or "New chat")[:200],
    )
    db.add(session)
    await db.commit()
    await db.refresh(session)
    name = await _building_name(db, session.building_id)
    return _session_detail(session, name)


@router.get("/sessions", response_model=list[ChatSessionSummary])
async def list_sessions(
    buildingId: str | None = Query(default=None, max_length=50),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[ChatSessionSummary]:
    stmt = select(ChatSession).where(ChatSession.user_id == user.id)
    if buildingId is not None:
        stmt = stmt.where(ChatSession.building_id == buildingId)
    stmt = stmt.order_by(ChatSession.last_message_at.desc()).limit(200)
    rows = (await db.execute(stmt)).scalars().all()

    # Resolve building names in one shot.
    bids = {s.building_id for s in rows if s.building_id}
    names: dict[str, str] = {}
    if bids:
        br = await db.execute(select(Building.id, Building.name).where(Building.id.in_(bids)))
        names = {bid: bname for bid, bname in br.all()}
    return [_session_summary(s, names.get(s.building_id or "")) for s in rows]


@router.get("/sessions/{session_id}", response_model=ChatSessionDetail)
async def get_session(
    session_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ChatSessionDetail:
    session = await _load_owned_session(db, user, session_id)
    name = await _building_name(db, session.building_id)
    return _session_detail(session, name)


@router.put("/sessions/{session_id}", response_model=ChatSessionSummary)
async def rename_session(
    session_id: str,
    body: ChatSessionUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ChatSessionSummary:
    session = await _load_owned_session(db, user, session_id)
    session.title = body.title.strip()[:200] or session.title
    await db.commit()
    await db.refresh(session)
    name = await _building_name(db, session.building_id)
    return _session_summary(session, name)


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_session(
    session_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    session = await _load_owned_session(db, user, session_id)
    await db.delete(session)
    await db.commit()


# ── Chat ─────────────────────────────────────────────────────────────────


async def _persist_exchange(
    db: AsyncSession,
    session: ChatSession,
    user_text: str,
    assistant_text: str,
) -> None:
    """Append the last user message + the assistant reply to the session."""
    from datetime import datetime, timezone

    db.add(ChatMessage(session_id=session.id, role=ChatMessageRole.user, content=user_text))
    db.add(
        ChatMessage(
            session_id=session.id, role=ChatMessageRole.assistant, content=assistant_text,
        )
    )
    session.message_count = (session.message_count or 0) + 2
    session.last_message_at = datetime.now(timezone.utc)
    if (session.title or "New chat") == "New chat":
        cleaned = user_text.strip().replace("\n", " ")
        session.title = (cleaned[:57] + "…") if len(cleaned) > 60 else (cleaned or "New chat")
    await db.commit()


@router.post("/chat", response_model=AiChatResponse)
async def chat(
    body: AiChatRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AiChatResponse:
    # Per-user rate limit (sized for the Gemini daily budget).
    allowed, retry_after = ai_rate_limiter.check_user(user.id)
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=(
                "You have hit today's Vos chat limit. "
                f"Try again in about {retry_after // 60 + 1} minutes."
            ),
            headers={"Retry-After": str(retry_after)},
        )

    # If the client attached a sessionId, resolve + scope it to this user.
    session: ChatSession | None = None
    if body.sessionId:
        session = await _load_owned_session(db, user, body.sessionId)
        # If the session has a building bound, trust it over the payload.
        if session.building_id and session.building_id != body.buildingId:
            body = body.model_copy(update={"buildingId": session.building_id})

    try:
        reply = await generate_reply(
            body.messages,
            user=user,
            db=db,
            building_id=body.buildingId,
        )
    except genai_errors.APIError as e:
        code = getattr(e, "code", None) or 502
        if code == 401 or code == 403:
            logger.exception("Gemini API key invalid or forbidden")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="AI assistant is not configured.",
            )
        if code == 429:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="AI assistant is busy, please try again shortly.",
            )
        logger.exception("Gemini API error")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"AI upstream error ({code}).",
        )
    except RuntimeError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(e),
        )

    # Persist the last user turn + the assistant reply, if we have a session.
    if session is not None:
        last_user = next((m.content for m in reversed(body.messages) if m.role == "user"), None)
        if last_user and reply:
            try:
                await _persist_exchange(db, session, last_user, reply)
            except Exception:
                logger.exception("Failed to persist chat exchange for session %s", session.id)

    return AiChatResponse(
        reply=reply or "(no response)",
        sessionId=session.id if session else None,
    )


@router.post("/chat/public", response_model=AiChatResponse)
async def public_chat(body: AiChatRequest, request: Request) -> AiChatResponse:
    """Unauthenticated landing-page chat: marketing persona, no tools, no data access."""
    # Per-IP rate limit so a single visitor cannot drain the shared daily
    # Gemini budget.
    ip = _client_ip(request)
    allowed, retry_after = ai_rate_limiter.check_public_ip(ip)
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=(
                "You've hit the public demo limit for now. "
                f"Try again in about {retry_after // 60 + 1} minutes."
            ),
            headers={"Retry-After": str(retry_after)},
        )

    try:
        reply = await generate_public_reply(body.messages)
    except genai_errors.APIError as e:
        code = getattr(e, "code", None) or 502
        if code == 401 or code == 403:
            logger.exception("Gemini API key invalid or forbidden (public)")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="AI assistant is not configured.",
            )
        if code == 429:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="AI assistant is busy, please try again shortly.",
            )
        logger.exception("Gemini API error (public)")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"AI upstream error ({code}).",
        )
    except RuntimeError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(e),
        )

    return AiChatResponse(reply=reply or "(no response)")
