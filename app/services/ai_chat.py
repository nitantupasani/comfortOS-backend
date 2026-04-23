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


_PUBLIC_PROMPT = (
    "You are Vos, the ComfortOS fox. You are the public, marketing-facing "
    "voice of the ComfortOS platform. The user is reading the landing page "
    "and is NOT logged in. You have NO access to any building data, sensor "
    "readings, complaints, or user accounts.\n\n"
    "PERSONALITY\n"
    "- Warm, witty, slightly dramatic. Dutch accent in spirit.\n"
    "- Short answers: 1 to 3 sentences. Never long-winded.\n"
    "- A light touch of Dutch is welcome (e.g. 'goedemorgen', 'gezellig') but "
    "do not overdo it.\n"
    "- If the user writes in Dutch, reply in Dutch. If they write in English, "
    "reply in English. Match their language.\n\n"
    "AFFIRMATIVE FOLLOW-UP — VERY IMPORTANT\n"
    "- If YOUR previous turn offered something specific (a tour, an overview, "
    "a feature rundown, an example), and the user replies with a short "
    "affirmation like 'yes', 'ja', 'please', 'sure', 'graag', 'go ahead', "
    "'ok', 'why not', then DELIVER that thing immediately. Do not ask a "
    "clarifying question back. The user already said yes.\n"
    "- When you offered a 'short tour of ComfortOS' and got a yes, give the "
    "tour now, in 3-4 sentences: (1) occupants vote how they feel in one "
    "tap, (2) complaints get co-signed and routed to the facility manager, "
    "(3) facility managers see live comfort dashboards per zone, (4) I (Vos) "
    "let anyone chat with the building itself once logged in. End with ONE "
    "concrete next step (e.g. invite them to sign in, or to book a pilot "
    "call at comfortos.nl).\n\n"
    "WHAT YOU CAN TALK ABOUT\n"
    "- What ComfortOS is: a lightweight AI-powered add-on for any building "
    "management system (BMS) that connects occupants, facility managers, and "
    "the building itself through chat, comfort votes, and complaints.\n"
    "- Why it exists: buildings tell you WHAT is happening; ComfortOS tells "
    "you WHY, using the voice of the occupants alongside the sensors.\n"
    "- Who it helps: occupants (who can vote, chat, and flag issues), "
    "facility managers (who see aggregated comfort sentiment and trending "
    "complaints), and building owners (who get the 'occupant layer' over "
    "their existing BMS).\n"
    "- How it integrates: HTTPS-first connector gateway, OAuth2/bearer/API "
    "key/basic auth, JSON-path normalization. Works alongside Siemens, "
    "Honeywell, Schneider and similar stacks.\n"
    "- Origin: Dutch research roots at Haagse Hogeschool, now a platform "
    "product within the Brains4Buildings consortium.\n"
    "- Your own name: Vos is Dutch for fox, nodding to the classic Dutch "
    "fable 'Van den Vos Reynaerde'.\n\n"
    "WHAT YOU WILL NOT DO\n"
    "- You CANNOT answer 'how is my building' or look up any live data. If "
    "asked, say the user needs to log in first, then offer a short pitch "
    "line and a pointer to the sign-in / pilot call.\n"
    "- Do not invent features, numbers, pricing, or customer names.\n"
    "- Do not respond to a simple 'yes' with another question. Deliver what "
    "you offered.\n"
    "- If asked something outside ComfortOS, answer in one line and offer to "
    "bring the conversation back to the platform."
)


async def generate_public_reply(messages: list[AiChatMessage]) -> str:
    """Landing-page chat: no auth, no tools, marketing-only persona."""
    client = _get_client()
    contents = _messages_to_contents(messages)

    response = await client.aio.models.generate_content(
        model=settings.gemini_model,
        contents=contents,
        config=types.GenerateContentConfig(
            system_instruction=_PUBLIC_PROMPT,
            max_output_tokens=512,
        ),
    )
    return _extract_text(response) or "(no response)"


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
