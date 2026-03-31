"""Step 2B — Claim extraction from segments using PydanticAI.

Porting of src/pipeline/extractor.ts — replaces manual JSON schema with
Pydantic-validated output via pydantic-ai.
"""

import uuid
from typing import Any

from pydantic import BaseModel, Field

from media_advisor.models.claims import (
    Claim,
    ClaimTypeValue,
    DimensionValue,
    EntityTypeValue,
    EvidenceQuote,
    ModalityValue,
    StanceValue,
    Theme,
)
from media_advisor.pipeline.segmenter import Segment

EXTRACT_SYSTEM = """Sei un estrattore di claim da transcript di video sportivi/calcio.
Per ogni SEGMENTO di transcript:
1. Estrai al massimo 4 claim atomici (una frase concreta ciascuno, non periodi lunghi)
2. Per OGNI claim DEVI includere quote_text: una citazione VERBATIM dal testo del segmento che supporta il claim
3. La quote DEVE essere copiata esattamente dal transcript (sottostringa del segment)
4. target_entity: squadra, giocatore, allenatore, arbitro, ecc.
5. claim_text: sintesi atomica in 1 frase (max ~20 parole)
6. dimension: performance, tactics, market, finance, leadership, injury, lineup_prediction, refereeing, fan_behavior, standings, europe, rivalry, media
7. claim_type: FACT, OBSERVATION, INTERPRETATION, JUDGEMENT, PRESCRIPTION, PREDICTION, META_INFO_QUALITY
8. micro_themes: 1-3 temi del segmento con weight 0-100 — usa nomi in italiano, al singolare, senza maiuscole (es. "infortunio", "mercato", "tattica")

REGOLE IMPORTANTI:
- NON estrarre claim meta sull'autore/host del video (es. "X è appassionato di Y", "X si chiama Y", "X risponde alle domande", "X vuole analizzare", "l'opinionista fa/dice")
- NON estrarre claim su intro, saluti, call-to-action o parti di auto-presentazione
- NON estrarre claim che descrivono il formato del video invece del contenuto calcistico
- ESTRAI solo posizioni, fatti, interpretazioni, previsioni concreti su giocatori/squadre/eventi specifici
- target_entity deve essere un calciatore, squadra, allenatore, arbitro — NON "opinionista", "autore", "commentatore", "community"

REGOLE DI PRECISIONE:
- Se un'entità viene CITATA come paragone/precedente/esempio (es. "come ha fatto X"), NON costruire un claim del tipo "X ha commentato Y" — costruisci invece "X è citato come precedente per Y"
- Le dichiarazioni di lealtà di un giocatore verso la squadra DEVONO essere estratte come claim separato (claim_type: FACT, dimension: leadership)
- Il SILENZIO o la mancanza di comunicazione di una squadra è dimension "media", NON "performance" o "tactics"
- La perdita di un familiare o evento personale di un giocatore è dimension "leadership" (aspetto morale/motivazionale), NON "injury"
- EVITA di estrarre più claim che affermano la stessa sostanza con parole diverse (es. "ha avuto infortuni" + "ha avuto problemi fisici" + "non si sentiva bene" sullo stesso soggetto nello stesso segmento = estrai UN solo claim, il più specifico con quote migliore)"""


class _RawClaim(BaseModel):
    target_entity: str
    entity_type: EntityTypeValue
    dimension: DimensionValue
    claim_type: ClaimTypeValue
    stance: StanceValue
    intensity: int = Field(ge=0, le=3)
    modality: ModalityValue
    claim_text: str
    quote_text: str
    tags: list[str] = Field(default_factory=list, max_length=6)


class _RawMicroTheme(BaseModel):
    theme: str
    weight: float = Field(ge=0, le=100)


class _ExtractResult(BaseModel):
    claims: list[_RawClaim] = Field(default_factory=list, max_length=4)
    micro_themes: list[_RawMicroTheme] = Field(default_factory=list)


async def extract_claims_from_segment(
    segment: Segment,
    video_id: str,
    api_key: str,
    model: str = "gpt-4o-mini",
    context: dict[str, Any] | None = None,
) -> tuple[list[Claim], list[Theme]]:
    """Extract claims from a single segment using PydanticAI structured output."""
    if not segment.text or len(segment.text) < 30:
        return [], []

    ctx = context or {}
    user_parts = [
        f"Segmento ({segment.segment_id}, {round(segment.start_sec)}s-{round(segment.end_sec)}s):\n"
    ]
    if ctx.get("title"):
        user_parts.append(f"Titolo video: {ctx['title']}")
    if ctx.get("opinionist"):
        user_parts.append(f"Opinionista: {ctx['opinionist']}")
    if ctx.get("published_at"):
        user_parts.append(f"Data: {ctx['published_at']}\n")
    user_parts.append(f"Testo:\n{segment.text}")
    user_content = "\n".join(user_parts)

    try:
        from pydantic_ai import Agent  # type: ignore[import-untyped]
        from pydantic_ai.models.openai import OpenAIModel  # type: ignore[import-untyped]

        # pydantic-ai has changed constructor signatures across versions.
        # Prefer explicit key, but fall back to env-based auth when needed.
        import os

        os.environ.setdefault("OPENAI_API_KEY", api_key)
        try:
            llm = OpenAIModel(model, api_key=api_key)
        except TypeError:
            llm = OpenAIModel(model)
        agent: Agent[None, _ExtractResult] = Agent(
            llm,
            output_type=_ExtractResult,
            system_prompt=EXTRACT_SYSTEM,
        )
        result = await agent.run(user_content)
        parsed = result.output
    except (ImportError, Exception):
        # Fallback: use openai directly if pydantic-ai not installed
        parsed = await _extract_openai_fallback(api_key, model, user_content)

    claims: list[Claim] = []
    for raw in parsed.claims or []:
        quote = EvidenceQuote(
            quote_text=raw.quote_text,
            start_sec=segment.start_sec,
            end_sec=segment.end_sec,
            confidence=0.9,
        )
        claims.append(
            Claim(
                claim_id=str(uuid.uuid4()),
                video_id=video_id,
                segment_id=segment.segment_id,
                target_entity=raw.target_entity,
                entity_type=raw.entity_type,
                dimension=raw.dimension,
                claim_type=raw.claim_type,
                stance=raw.stance,
                intensity=min(3, max(0, raw.intensity)),  # type: ignore[arg-type]
                modality=raw.modality,
                claim_text=raw.claim_text,
                evidence_quotes=[quote],
                tags=raw.tags[:6],
            )
        )

    themes = [
        Theme(theme=t.theme, weight=min(100.0, max(0.0, t.weight)))
        for t in (parsed.micro_themes or [])
    ]
    return claims, themes


async def _extract_openai_fallback(
    api_key: str, model: str, user_content: str
) -> _ExtractResult:
    """Fallback extractor using openai SDK directly (structured output)."""
    import json

    import openai  # type: ignore[import-untyped]

    client = openai.AsyncOpenAI(api_key=api_key)
    completion = await client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": EXTRACT_SYSTEM},
            {"role": "user", "content": user_content},
        ],
        # Avoid `json_schema` strict mode: OpenAI requires a schema shape that doesn't
        # match Pydantic's default JSON Schema (additionalProperties/required rules).
        response_format={"type": "json_object"},
    )
    content = completion.choices[0].message.content
    if not content:
        return _ExtractResult()
    return _ExtractResult.model_validate(json.loads(content))
