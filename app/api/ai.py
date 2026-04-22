"""AI assistant routes — POST /ai/chat."""

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from google.genai import errors as genai_errors

from ..api.deps import get_current_user
from ..models.user import User
from ..schemas.ai import AiChatRequest, AiChatResponse
from ..services.ai_chat import generate_reply

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ai", tags=["ai"])


@router.post("/chat", response_model=AiChatResponse)
async def chat(
    body: AiChatRequest,
    _user: User = Depends(get_current_user),
) -> AiChatResponse:
    try:
        reply = await generate_reply(body.messages)
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

    return AiChatResponse(reply=reply or "(no response)")
