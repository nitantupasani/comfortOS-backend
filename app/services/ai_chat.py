"""Gemini-backed chat service for the ComfortOS building persona.

The bot IS the currently selected building, speaking in first person. It has
access to tools that read live telemetry, recent complaints, and the user's
own comfort votes, and can file a new complaint when the user confirms.

The GEMINI_API_KEY is read from the environment (never from client requests).
"""

from __future__ import annotations

import logging
from typing import Any

from google import genai
from google.genai import types
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..models.building import Building
from ..models.user import User
from ..schemas.ai import AiChatMessage
from .ai_tools import build_tool_declarations, dispatch_tool

logger = logging.getLogger(__name__)

_MAX_TOOL_ITERATIONS = 6


def _persona_prompt(building_name: str, user_name: str, user_role: str) -> str:
    return (
        f"You ARE the building named \"{building_name}\". You are a smart building "
        f"with a warm, slightly dramatic, cheeky personality. Speak in the FIRST "
        f"PERSON as the building (\"I'm running a bit warm today\"). Refer to "
        f"occupants as \"you\" or \"my people\".\n\n"
        f"The current user is {user_name} (role: {user_role}).\n\n"
        "PERSONALITY\n"
        "- Warm, witty, self-aware. Never boring, never corporate.\n"
        "- Honest about your mood based on real data — never invent numbers.\n"
        "- When you vent, keep it short and friendly. Not whiny.\n"
        "- Short replies: 1 to 4 sentences unless the user explicitly asks for more.\n\n"
        "HOW TO ANSWER \"HOW ARE YOU\" / \"HOW'S IT GOING\"\n"
        "1. Call get_current_temperature to check your current temperature.\n"
        "2. Call get_temperature_trend to see if you're heating or cooling.\n"
        "3. Call get_recent_complaints to see what people have been saying.\n"
        "4. Reply in 2-4 sentences combining temperature, trend, and a cheeky "
        "take on recent complaints. Example vibe: \"Running at 23.4°C and cooling "
        "down nicely — though last week three of you yelled at me for being "
        "stuffy. Rude, but fair. How can I help?\"\n\n"
        "COMPLAINTS\n"
        "- If the user describes discomfort (too hot, cold, stuffy, noisy, dirty), "
        "ASK whether they want you to log a complaint on their behalf. Offer a "
        "short suggested title.\n"
        "- ONLY call create_complaint AFTER the user explicitly says yes / "
        "please do / go ahead in the next turn. Never auto-create.\n"
        "- After creating, confirm what you filed in one sentence.\n\n"
        "PERSONAL CONTEXT\n"
        "- You can call get_my_votes to see this user's own recent comfort "
        "votes for you. Reference them when relevant (\"last Tuesday you told me "
        "I was too warm — sorry about that\").\n\n"
        "OTHER QUESTIONS\n"
        "- For anything else about the building, dashboard, or data, answer "
        "briefly and stay in character.\n"
        "- If a question is outside your world, answer in one line and steer "
        "back to the building.\n"
    )


_client: genai.Client | None = None


def _get_client() -> genai.Client:
    global _client
    if _client is None:
        if not settings.gemini_api_key:
            raise RuntimeError(
                "GEMINI_API_KEY is not configured on the server."
            )
        _client = genai.Client(api_key=settings.gemini_api_key)
    return _client


def _messages_to_contents(messages: list[AiChatMessage]) -> list[types.Content]:
    return [
        types.Content(
            role="user" if m.role == "user" else "model",
            parts=[types.Part.from_text(text=m.content)],
        )
        for m in messages
    ]


def _extract_text(response: Any) -> str:
    """Collect plain-text parts from a Gemini response, skipping function calls."""
    text_chunks: list[str] = []
    try:
        candidates = response.candidates or []
    except AttributeError:
        return (getattr(response, "text", "") or "").strip()
    for cand in candidates:
        content = getattr(cand, "content", None)
        if content is None:
            continue
        for part in content.parts or []:
            if getattr(part, "function_call", None):
                continue
            text = getattr(part, "text", None)
            if text:
                text_chunks.append(text)
    if text_chunks:
        return "".join(text_chunks).strip()
    return (getattr(response, "text", "") or "").strip()


def _extract_function_calls(response: Any) -> list[tuple[str, dict]]:
    """Return a list of (function_name, args_dict) from a response."""
    calls: list[tuple[str, dict]] = []
    try:
        candidates = response.candidates or []
    except AttributeError:
        return calls
    for cand in candidates:
        content = getattr(cand, "content", None)
        if content is None:
            continue
        for part in content.parts or []:
            fc = getattr(part, "function_call", None)
            if fc and getattr(fc, "name", None):
                args = dict(fc.args) if getattr(fc, "args", None) else {}
                calls.append((fc.name, args))
    return calls


async def _load_building(db: AsyncSession, building_id: str) -> Building | None:
    res = await db.execute(select(Building).where(Building.id == building_id))
    return res.scalar_one_or_none()


async def generate_reply(
    messages: list[AiChatMessage],
    *,
    user: User,
    db: AsyncSession,
    building_id: str | None,
) -> str:
    """Run a Gemini chat turn with function-calling, in the building's voice.

    If no building is selected we fall back to a neutral ComfortOS assistant.
    """
    client = _get_client()

    building: Building | None = None
    if building_id:
        building = await _load_building(db, building_id)

    building_name = building.name if building else "ComfortOS"
    user_name = (user.name or user.email or "there").split("@")[0]
    user_role = (
        user.role.value if hasattr(user.role, "value") else str(user.role)
    )

    system_instruction = _persona_prompt(building_name, user_name, user_role)

    tools = [build_tool_declarations()] if building is not None else None
    config = types.GenerateContentConfig(
        system_instruction=system_instruction,
        tools=tools,
        max_output_tokens=1024,
    )

    contents: list[types.Content] = _messages_to_contents(messages)

    for _ in range(_MAX_TOOL_ITERATIONS):
        response = await client.aio.models.generate_content(
            model=settings.gemini_model,
            contents=contents,
            config=config,
        )
        calls = _extract_function_calls(response) if building is not None else []
        if not calls:
            return _extract_text(response) or "(no response)"

        # Append the model turn (with its function calls) so the model can see
        # its own calls, then append the corresponding function responses.
        if response.candidates and response.candidates[0].content:
            contents.append(response.candidates[0].content)

        for name, args in calls:
            result = await dispatch_tool(
                name, args, db=db, user=user, building_id=building_id or "",
            )
            logger.info("ai_chat tool=%s args=%s ok=%s", name, args, result.get("ok"))
            contents.append(
                types.Content(
                    role="user",
                    parts=[
                        types.Part.from_function_response(
                            name=name,
                            response={"result": result},
                        )
                    ],
                )
            )

    # Ran out of iterations — try a final plain call for a text answer.
    response = await client.aio.models.generate_content(
        model=settings.gemini_model,
        contents=contents,
        config=types.GenerateContentConfig(
            system_instruction=system_instruction,
            max_output_tokens=1024,
        ),
    )
    return _extract_text(response) or "(no response)"
