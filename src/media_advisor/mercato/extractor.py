"""Estrazione indiscrezioni di mercato dal transcript via PydanticAI.

Lavora sul transcript intero (no segmentazione): il mercato è un tema
trasversale e non vale la pena suddividere per topic.
"""

import os
import uuid
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field

from media_advisor.mercato.models import ConfidenceLevel, MercatoTip, TransferType
from media_advisor.models.transcript import TranscriptResponse
from media_advisor.pipeline.entity_normalizer import normalize_entity

# gpt-4o-mini has 128K context, but very long transcripts waste tokens and cost.
# ~80K chars ≈ 20K tokens — sufficient for any realistic video length.
_MAX_TRANSCRIPT_CHARS = 80_000

MERCATO_SYSTEM = """Sei un estrattore di indiscrezioni di calciomercato da transcript di video YouTube.

Il tuo compito è estrarre SOLO rumor/notizie di mercato concreti: trasferimenti, trattative, rinnovi, prestiti.

Per ogni indiscrezione estratta devi fornire:
- player_name: nome del calciatore (es. "Lukaku", "Osimhen")
- from_club: club cedente (null se non menzionato)
- to_club: club acquirente (null se non menzionato)
- transfer_type: "loan" | "permanent" | "free_agent" | "extension" | "unknown"
- confidence: livello di certezza secondo l'opinionista:
    "rumor"     → voce di corridoio, si dice, circola
    "likely"    → probabile, ci siamo quasi, avanzata
    "confirmed" → è fatta, confermato, ufficiale
    "denied"    → smentito, non si farà
- tip_text: sintesi in max 30 parole (italiano)
- quote_text: citazione VERBATIM dal transcript (sottostringa esatta)
- quote_start_sec: timestamp inizio (null se non disponibile)
- quote_end_sec: timestamp fine (null se non disponibile)

REGOLE:
- Estrai SOLO indiscrezioni che riguardano un calciatore specifico con almeno from_club O to_club
- NON estrarre: commenti tattici, prestazioni in campo, infortuni, formazioni
- NON estrarre: notizie già ufficiali pubbliche ovvie (es. "Lukaku è al Napoli" detto come dato di fatto narrativo)
- Se lo stesso calciatore è menzionato più volte per la stessa trattativa, estrai UNA sola tip (la più dettagliata)
- confidence "confirmed" solo se l'opinionista dice esplicitamente "è fatta", "confermato", "ufficiale"
- quote_text deve essere una substring esatta del transcript fornito"""


class _RawMercatoTip(BaseModel):
    player_name: str
    from_club: str | None = None
    to_club: str | None = None
    transfer_type: TransferType = "unknown"
    confidence: ConfidenceLevel = "rumor"
    tip_text: str
    quote_text: str
    quote_start_sec: float | None = None
    quote_end_sec: float | None = None


class _ExtractMercatoResult(BaseModel):
    tips: list[_RawMercatoTip] = Field(default_factory=list)


def _transcript_to_text(data: TranscriptResponse) -> str:
    if isinstance(data.transcript, list):
        text = " ".join(seg.text for seg in data.transcript if seg.text)
    else:
        text = str(data.transcript or "")
    return text[:_MAX_TRANSCRIPT_CHARS]


async def extract_mercato_tips(
    data: TranscriptResponse,
    video_id: str,
    channel_id: str,
    api_key: str,
    model: str = "gpt-4o-mini",
    context: dict[str, Any] | None = None,
) -> list[MercatoTip]:
    """Estrae indiscrezioni di mercato da un transcript.

    Returns lista di MercatoTip (può essere vuota se il video non è di mercato).
    """
    text = _transcript_to_text(data)
    if len(text) < 100:
        return []

    ctx = context or {}
    user_parts: list[str] = []
    if ctx.get("title"):
        user_parts.append(f"Titolo video: {ctx['title']}")
    if ctx.get("opinionist"):
        user_parts.append(f"Opinionista: {ctx['opinionist']}")
    if ctx.get("published_at"):
        user_parts.append(f"Data pubblicazione: {ctx['published_at']}")
    user_parts.append(f"\nTranscript:\n{text}")
    user_content = "\n".join(user_parts)

    parsed = await _run_extraction(api_key, model, user_content)

    now = datetime.now(timezone.utc)
    mentioned_at = ctx.get("mentioned_at") or now

    tips: list[MercatoTip] = []
    for raw in parsed.tips:
        player = normalize_entity(raw.player_name) or raw.player_name
        from_club = normalize_entity(raw.from_club) if raw.from_club else None
        to_club = normalize_entity(raw.to_club) if raw.to_club else None

        tips.append(
            MercatoTip(
                tip_id=str(uuid.uuid4()),
                video_id=video_id,
                channel_id=channel_id,
                mentioned_at=mentioned_at,
                extracted_at=now,
                player_name=player,
                from_club=from_club,
                to_club=to_club,
                transfer_type=raw.transfer_type,
                confidence=raw.confidence,
                tip_text=raw.tip_text,
                quote_text=raw.quote_text,
                quote_start_sec=raw.quote_start_sec,
                quote_end_sec=raw.quote_end_sec,
            )
        )
    return tips


async def _run_extraction(api_key: str, model: str, user_content: str) -> _ExtractMercatoResult:
    """Lancia l'estrazione AI. Prova PydanticAI, fallback su OpenAI diretto."""
    try:
        from pydantic_ai import Agent  # type: ignore[import-untyped]
        from pydantic_ai.models.openai import OpenAIModel  # type: ignore[import-untyped]

        os.environ.setdefault("OPENAI_API_KEY", api_key)
        try:
            llm = OpenAIModel(model, api_key=api_key)
        except TypeError:
            llm = OpenAIModel(model)

        agent: Agent[None, _ExtractMercatoResult] = Agent(
            llm,
            output_type=_ExtractMercatoResult,
            system_prompt=MERCATO_SYSTEM,
        )
        result = await agent.run(user_content)
        return result.output
    except Exception:
        return await _openai_fallback(api_key, model, user_content)


async def _openai_fallback(api_key: str, model: str, user_content: str) -> _ExtractMercatoResult:
    import json
    import openai  # type: ignore[import-untyped]

    client = openai.AsyncOpenAI(api_key=api_key)
    completion = await client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": MERCATO_SYSTEM},
            {"role": "user", "content": user_content},
        ],
        response_format={"type": "json_object"},
    )
    content = completion.choices[0].message.content
    if not content:
        return _ExtractMercatoResult()
    try:
        return _ExtractMercatoResult.model_validate(json.loads(content))
    except Exception:
        return _ExtractMercatoResult()
