"""Estrazione indiscrezioni di mercato dal transcript via PydanticAI.

Lavora sul transcript intero (no segmentazione): il mercato è un tema
trasversale e non vale la pena suddividere per topic.
"""

import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from media_advisor.mercato.models import ConfidenceLevel, MercatoTip, TransferType
from media_advisor.mercato.player_normalizer import get_player_list_for_prompt, normalize_player_name
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
- confidence_note: breve nota (max 10 parole) che spiega il livello di fiducia, es.:
    "fasi finali dell'accordo", "obbligo di riscatto scattato", "smentito dall'agente",
    "non sta trattando con nessuno", "trattativa avanzata", "basi dell'accordo raggiunte"
    (null se non c'è nulla di specifico da aggiungere)
- tip_text: sintesi in max 30 parole (italiano)
- quote_text: citazione VERBATIM dal transcript (sottostringa esatta)
- quote_start_sec: timestamp inizio (null se non disponibile)
- quote_end_sec: timestamp fine (null se non disponibile)

REGOLE:
- ESAURISCI tutti i giocatori con notizie di mercato menzionati nel transcript: non fermarti al primo
- Estrai SOLO indiscrezioni che riguardano un calciatore specifico con almeno from_club O to_club
- ESTRAI ANCHE le smentite/denied: se l'opinionista dice che una trattativa NON esiste, NON sta avvenendo, è smentita → confidence "denied", extracta come tip
- ESTRAI ANCHE operazioni separate per lo stesso giocatore: riscatto confermato + cessione pianificata = 2 tip distinte
- NON estrarre: commenti tattici, prestazioni in campo, infortuni, formazioni, episodi di partita, arbitri, classifiche
- NON estrarre: opinioni generiche ("serve un difensore", "dovrebbero comprare X") senza notizia/rumor concreto
- NON estrarre: semplici DATI BIOGRAFICI o di appartenenza ("X è al Y", "milita nel Y") se NON è parte di una notizia di mercato
- NON estrarre: notizie già ufficiali pubbliche ovvie dette come contesto narrativo (es. "Lukaku è al Napoli" come premessa)
- Se lo stesso calciatore è menzionato più volte per LA STESSA operazione, estrai UNA sola tip (la più dettagliata)
- confidence "confirmed" solo se l'opinionista dice esplicitamente "è fatta", "confermato", "ufficiale", "è scattato l'obbligo"
- confidence "denied" se dice esplicitamente "non sta trattando", "non c'è trattativa", "è smentita", "l'agente nega"
- quote_text deve essere una substring esatta del transcript fornito
- from_club / to_club: impostali SOLO se compaiono esplicitamente nel contesto della quote_text (niente inferenze)
- Per rinnovi/extension: from_club e to_club sono lo stesso club (es. Juventus→Juventus)
- Per tip "denied": from_club/to_club rappresentano il trasferimento VOCIFERATO che viene smentito (es. "non va al Besiktas" → to_club="Besiktas")
- Se non trovi segnali linguistici di MERCATO (trattativa/offerta/contatti/rinnovo/visite/firma/prestito/clausola/riscatto/cessione/smentita ecc.), NON estrarre"""


class _RawMercatoTip(BaseModel):
    player_name: str
    from_club: str | None = None
    to_club: str | None = None
    transfer_type: TransferType = "unknown"
    confidence: ConfidenceLevel = "rumor"
    confidence_note: str | None = None
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


def _slug(s: str) -> str:
    return "".join(ch.lower() for ch in s.strip() if ch.isalnum())


def _slug_name(s: str) -> str:
    return "".join(ch for ch in _slug(s) if ch.isalnum())


def _clubs_match(a: str | None, b: str | None) -> bool:
    """Match club names loosely (e.g. Juve vs Juventus)."""
    if not a or not b:
        return False
    sa, sb = _slug_name(a), _slug_name(b)
    if not sa or not sb:
        return False
    if sa == sb:
        return True
    # substring match for meaningful tokens
    return (len(sa) >= 3 and sa in sb) or (len(sb) >= 3 and sb in sa)


def _club_in_quote(club: str | None, quote: str) -> bool:
    if not club:
        return False
    q = quote
    # Try common abbreviations/aliases without hardcoding a huge dictionary:
    # also compare with a few normalized variants.
    variants = {club}
    cslug = _slug_name(club)
    if cslug.endswith("juventus"):
        variants.add("juve")
    if cslug.endswith("internazionale"):
        variants.add("inter")
    if cslug.endswith("associazioneacalciomilan") or cslug.endswith("milan"):
        variants.add("milan")
    if cslug.endswith("societasportivacalcionapoli") or cslug.endswith("napoli"):
        variants.add("napoli")
    if cslug.endswith("asroma"):
        variants.add("roma")
    if cslug.endswith("ssclazio") or cslug.endswith("lazio"):
        variants.add("lazio")

    for v in variants:
        if _clubs_match(v, q):
            return True
        if _slug_name(v) in _slug_name(q):
            return True
    return False


_MERCATO_SIGNAL: tuple[str, ...] = (
    "mercato",
    "calciomercato",
    "trattativa",
    "trattative",
    "trattativ",
    "trattando",
    "contatti",
    "contatto",
    "offerta",
    "offerto",
    "rilancio",
    "proposta",
    "accordo",
    "intesa",
    "chiusura",
    "chiudere",
    "firma",
    "firmare",
    "rinnovo",
    "rinnovare",
    "prolungamento",
    "clausola",
    "rescissione",
    "prestito",
    "in prestito",
    "obbligo",
    "diritto",
    "opzione",
    "visite mediche",
    "commissioni",
    "agente",
    "procura",
    "trovato l'accordo",
    "operazione",
    "arriva",
    "va via",
    "cedere",
    "cessione",
    "non tratta",
    "nega ",
    "riscatt",     # riscatto / riscattare / riscattato
    "vend",        # vendere / venduto / vendibile
    "acquist",     # acquistare / acquisto
)

_NON_MERCATO_SIGNAL: tuple[str, ...] = (
    "partita",
    "gol",
    "assist",
    "rigore",
    "arbitro",
    "fallo",
    "espuls",
    "ammon",
    "tattic",
    "modulo",
    "difesa",
    "attacco",
    "formazione",
    "infortun",
    "recuper",
    "condizione",
    "classifica",
    "champions",
    "europa",
)


def _contains_any(haystack: str, needles: tuple[str, ...]) -> bool:
    h = haystack.lower()
    return any(n in h for n in needles)


def _quote_mentions_entity(quote: str, entity: str) -> bool:
    q = _slug(quote)
    e = _slug(entity)
    if not e:
        return False
    if e in q:
        return True
    # fallback: last token (surname-ish) match, but avoid short noise
    tokens = [t for t in entity.replace("-", " ").split() if len(t) >= 4]
    if not tokens:
        return False
    return _slug(tokens[-1]) in q


def _is_plausible_mercato_tip(raw: _RawMercatoTip) -> bool:
    quote = (raw.quote_text or "").strip()
    if len(quote) < 15:
        return False

    # If it screams match analysis and doesn't contain mercato signals -> drop.
    if _contains_any(quote, _NON_MERCATO_SIGNAL) and not _contains_any(quote, _MERCATO_SIGNAL):
        return False

    # Requires mercato language in the quote (otherwise it's usually generic chatter).
    if not _contains_any(quote, _MERCATO_SIGNAL):
        # allow explicit denied/confirmed phrasing even if short
        if raw.confidence in ("confirmed", "denied") and _contains_any(
            quote, (
                "ufficial", "è fatta", "fatta", "conferm", "smentit", "non si fa", "saltata",
                "non sta trattando", "non c'è stata", "nessuna trattativa", "nega", "non ci sono state",
                "non ci sono trattativ",
            )
        ):
            return True
        return False

    # Player name should appear in the quote to reduce hallucinations.
    player_in_quote = bool(raw.player_name) and _quote_mentions_entity(quote, raw.player_name)

    # At least one club must exist and must appear in the quote if provided.
    if not (raw.from_club or raw.to_club):
        return False
    from_in_quote = _club_in_quote(raw.from_club, quote) if raw.from_club else False
    to_in_quote = _club_in_quote(raw.to_club, quote) if raw.to_club else False

    # If the model produced clubs but none are actually present in the quote AND player isn't either, drop.
    # (This keeps recall for cases where the quote has "Juve" vs "Juventus", etc.)
    # Exception: denied tips may have the denial statement in a separate sentence that doesn't
    # repeat the entity name (e.g. "non ci sono state trattative [col Galatasaray]"). Accept them
    # if the quote has strong mercato signals, trusting the AI's broader context reading.
    if (raw.from_club or raw.to_club) and not (from_in_quote or to_in_quote or player_in_quote):
        if raw.confidence == "denied":
            pass  # trust the AI for denied tips with mercato signals in the quote
        else:
            return False

    # Drop "is at club" statements unless tied to renewal/transfer verbs.
    if _contains_any(quote, (" è al ", " sta al ", " gioca nel ", " milita nel ")) and not _contains_any(
        quote, ("rinn", "firma", "tratt", "offert", "contatt", "arriv", "ced", "va via", "prest")
    ):
        return False

    return True


def is_plausible_mercato_tip(tip: MercatoTip) -> bool:
    """Public helper to re-filter already-saved tips (index rebuild / cleanup)."""
    raw = _RawMercatoTip(
        player_name=tip.player_name or "",
        from_club=tip.from_club,
        to_club=tip.to_club,
        transfer_type=tip.transfer_type,
        confidence=tip.confidence,
        tip_text=tip.tip_text,
        quote_text=tip.quote_text,
        quote_start_sec=tip.quote_start_sec,
        quote_end_sec=tip.quote_end_sec,
    )
    return _is_plausible_mercato_tip(raw)


def _build_system_prompt(data_dir: Path | None) -> str:
    """Costruisce il system prompt, iniettando la lista giocatori se disponibile."""
    if data_dir is None:
        return MERCATO_SYSTEM
    try:
        player_list = get_player_list_for_prompt(data_dir)
    except Exception:
        return MERCATO_SYSTEM
    if not player_list:
        return MERCATO_SYSTEM
    return (
        MERCATO_SYSTEM
        + f"\n\nCALCIATORI NOTI (usa questi nomi canonici se riconosci il giocatore nel transcript):\n{player_list}"
    )


async def extract_mercato_tips(
    data: TranscriptResponse,
    video_id: str,
    channel_id: str,
    api_key: str,
    model: str = "gpt-4o-mini",
    context: dict[str, Any] | None = None,
    data_dir: Path | None = None,
) -> list[MercatoTip]:
    """Estrae indiscrezioni di mercato da un transcript.

    Args:
        data_dir: percorso alla directory mercato/ del progetto, usato per
            caricare il registry giocatori (alias + transfer confermati) e
            iniettarlo nel prompt. Se None, si usa solo normalize_entity().

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

    system_prompt = _build_system_prompt(data_dir)
    parsed = await _run_extraction(api_key, model, user_content, system_prompt=system_prompt)

    now = datetime.now(timezone.utc)
    mentioned_at = ctx.get("mentioned_at") or now

    tips: list[MercatoTip] = []
    for raw in parsed.tips:
        if not _is_plausible_mercato_tip(raw):
            continue
        _PLACEHOLDER_CLUBS = {"unknown", "null", "none", "n/a", "?", "-", ""}

        if data_dir is not None:
            player = normalize_player_name(raw.player_name, data_dir) or raw.player_name
        else:
            player = normalize_entity(raw.player_name) or raw.player_name
        _fc = raw.from_club if raw.from_club and raw.from_club.lower() not in _PLACEHOLDER_CLUBS else None
        _tc = raw.to_club if raw.to_club and raw.to_club.lower() not in _PLACEHOLDER_CLUBS else None
        from_club = normalize_entity(_fc) if _fc else None
        to_club = normalize_entity(_tc) if _tc else None

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
                confidence_note=raw.confidence_note,
                tip_text=raw.tip_text,
                quote_text=raw.quote_text,
                quote_start_sec=raw.quote_start_sec,
                quote_end_sec=raw.quote_end_sec,
            )
        )
    return tips


async def _run_extraction(
    api_key: str,
    model: str,
    user_content: str,
    system_prompt: str = MERCATO_SYSTEM,
) -> _ExtractMercatoResult:
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
            system_prompt=system_prompt,
        )
        try:
            from pydantic_ai.settings import ModelSettings  # type: ignore[import-untyped]
            result = await agent.run(user_content, model_settings=ModelSettings(temperature=1.0))
        except (ImportError, TypeError):
            result = await agent.run(user_content)
        return result.output
    except Exception:
        return await _openai_fallback(api_key, model, user_content, system_prompt=system_prompt)


async def _openai_fallback(
    api_key: str,
    model: str,
    user_content: str,
    system_prompt: str = MERCATO_SYSTEM,
) -> _ExtractMercatoResult:
    import json
    import openai  # type: ignore[import-untyped]

    client = openai.AsyncOpenAI(api_key=api_key)
    completion = await client.chat.completions.create(
        model=model,
        temperature=1.0,
        messages=[
            {"role": "system", "content": system_prompt},
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
