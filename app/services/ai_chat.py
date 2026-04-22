"""Gemini-backed chat service for the ComfortOS AI assistant widget.

The GEMINI_API_KEY is read from the environment (never from client requests).
"""

from google import genai
from google.genai import types

from ..config import settings
from ..schemas.ai import AiChatMessage

_SYSTEM_PROMPT = (
    "You are the ComfortOS AI assistant, embedded in a smart-building "
    "platform used by occupants and facility managers. Help users understand "
    "their dashboard, building environment data (temperature, CO2, humidity), "
    "complaints workflow, and navigation. Be concise (usually 1-3 sentences), "
    "practical, and friendly. If asked something outside the ComfortOS scope, "
    "answer briefly and offer to bring the conversation back to the building."
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


async def generate_reply(messages: list[AiChatMessage]) -> str:
    """Send the conversation to Gemini and return the assistant text."""
    client = _get_client()

    contents = [
        types.Content(
            role="user" if m.role == "user" else "model",
            parts=[types.Part.from_text(text=m.content)],
        )
        for m in messages
    ]

    response = await client.aio.models.generate_content(
        model=settings.gemini_model,
        contents=contents,
        config=types.GenerateContentConfig(
            system_instruction=_SYSTEM_PROMPT,
            max_output_tokens=1024,
        ),
    )

    return (response.text or "").strip()
