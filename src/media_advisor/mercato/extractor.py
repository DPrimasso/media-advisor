"""Estrazione indiscrezioni di mercato dal transcript via PydanticAI.

Lavora sul transcript intero (no segmentazione): il mercato è un tema
trasversale e non vale la pena suddividere per topic.
"""

import logging
import os
import re
import unicodedata
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_LOG = logging.getLogger(__name__)

from pydantic import BaseModel, Field

from media_advisor.costs import record_openai_chat_completion, record_pydantic_ai_run_usage
from media_advisor.mercato.models import ConfidenceLevel, MercatoTip, TransferType
from media_advisor.mercato.player_normalizer import (
    get_player_list_for_prompt,
    normalize_player_name,
)
from media_advisor.models.transcript import TranscriptResponse
from media_advisor.pipeline.entity_normalizer import normalize_entity

# gpt-4.1-mini has 128K context, but very long transcripts waste tokens and cost.
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
- quote_text: citazione VERBATIM dal transcript (sottostringa esatta del testo, senza prefisso [secondi]s)
- quote_start_sec: secondo di inizio della citazione (usa il numero tra [ e s] della riga dove inizia la quote)
- quote_end_sec: secondo di fine (della riga dove finisce la quote, o stesso di inizio se una sola riga)

REGOLE:
- ESAURISCI tutti i giocatori con notizie di mercato menzionati nel transcript: non fermarti al primo
- Estrai SOLO indiscrezioni che riguardano un calciatore specifico con almeno from_club O to_club
- ESTRAI ANCHE le partenze senza destinazione: se si dice "X lascerà il club", "addio pianificato", "in uscita" → from_club=club attuale, to_club=null, transfer_type="permanent" o "unknown"
- ESTRAI ANCHE l'interesse iniziale: "il club parla con l'entourage", "sondaggio per X", "X è una pista", "voci che accostano X a Y", "X è accostato a Y" → confidence "rumor", to_club=club interessato
- ESTRAI ANCHE valutazioni di mercato senza trattativa aperta: "è un pallino / obiettivo del club", "apprezzato dalla dirigenza", "serve una plusvalenza", "cessione solo a cifre importanti", scambi discussi (anche se poi negati o separati) → from_club / to_club se espliciti nel testo
- ESTRAI ANCHE le smentite/denied: se l'opinionista dice che una trattativa NON esiste, NON sta avvenendo, è smentita → confidence "denied", extracta come tip
- ESTRAI ANCHE i denied di richiesta di cessione: "non ha mai chiesto la cessione", "non ha mai chiesto di andare via", "rifiuta di lasciare il club" → confidence "denied", from_club=club attuale, to_club=null
- ESTRAI ANCHE operazioni separate per lo stesso giocatore: riscatto confermato + cessione pianificata = 2 tip distinte
- ATTENZIONE ai rinnovi vs trasferimenti: se un giocatore è accostato al club X ma sta RINNOVANDO con il club Y, estrai il RINNOVO come tip principale (extension, from_club=Y, to_club=Y) e opzionalmente il denied per X
- NON estrarre: commenti tattici, prestazioni in campo, infortuni, formazioni, episodi di partita, arbitri, classifiche
- NON estrarre: opinioni generiche ("serve un difensore", "dovrebbero comprare X") senza notizia/rumor concreto
- NON estrarre: semplici DATI BIOGRAFICI o di appartenenza ("X è al Y", "milita nel Y") se NON è parte di una notizia di mercato
- NON estrarre: notizie già ufficiali pubbliche ovvie dette come contesto narrativo (es. "Lukaku è al Napoli" come premessa)
- Se lo stesso calciatore è menzionato più volte per LA STESSA operazione, estrai UNA sola tip (la più dettagliata)
- confidence "confirmed" solo se l'opinionista dice esplicitamente "è fatta", "confermato", "ufficiale", "è scattato l'obbligo"
- confidence "denied" se dice esplicitamente "non sta trattando", "non c'è trattativa", "è smentita", "l'agente nega", "non ha mai chiesto la cessione"
- quote_text deve essere una substring esatta del transcript fornito (solo testo parole, mai la parte [12.3s])
- Il transcript ha una riga per segmento con prefisso [secondi.decimali]s: allinea quote_start_sec al valore [..]s della prima riga coperta dalla quote
- from_club / to_club: impostali SOLO se compaiono esplicitamente nel contesto della quote_text (niente inferenze)
- Per rinnovi/extension: from_club e to_club sono lo stesso club (es. Real Madrid→Real Madrid)
- Per tip "denied": from_club/to_club rappresentano il trasferimento VOCIFERATO che viene smentito (es. "non va al Besiktas" → to_club="Besiktas")
- Se non trovi segnali linguistici di MERCATO (trattativa/offerta/contatti/rinnovo/entourage/partenza/addio/visite/firma/prestito/clausola/riscatto/cessione/smentita ecc.), NON estrarre"""


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


def _transcript_to_timestamped_text(data: TranscriptResponse) -> str:
    """Una riga per segmento con [start_sec]s così il modello può indicare tempi reali."""
    if not isinstance(data.transcript, list):
        return _transcript_to_text(data)
    lines: list[str] = []
    for seg in data.transcript:
        if not seg.text:
            continue
        if seg.start is not None:
            lines.append(f"[{float(seg.start):.1f}s] {seg.text}")
        else:
            lines.append(seg.text)
    text = "\n".join(lines)
    return text[:_MAX_TRANSCRIPT_CHARS]


def _slug(s: str) -> str:
    return "".join(ch.lower() for ch in s.strip() if ch.isalnum())


def _slug_name(s: str) -> str:
    return "".join(ch for ch in _slug(s) if ch.isalnum())


def _ascii_slug(s: str) -> str:
    """Fold accents so Koné/Kone match transcript spelling variants."""
    norm = unicodedata.normalize("NFKD", s)
    return "".join(ch.lower() for ch in norm if ch.isalnum())


# Nicknames / colori in citazioni: "giallorossi" = Roma, "nerazzurri" = Inter, ecc.
_CLUB_SPOKEN_ALIASES: dict[str, tuple[str, ...]] = {
    "roma": ("giallorossi", "giallorosso", "giallorossa", "capitolini", "romana", "romano"),
    "inter": ("nerazzurri", "nerazzurro", "interista", "interisti"),
    "juventus": ("bianconeri", "bianconero", "bianconera", "juve"),
    "milan": ("rossoneri", "rossonero", "rossonera"),
    "napoli": ("partenopei", "partenopeo", "azzurri"),
    "lazio": ("biancocelesti", "laziale"),
    "atalanta": ("bergamaschi", "bergamasco", "dea"),
}


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

    for key, spoken in _CLUB_SPOKEN_ALIASES.items():
        if cslug == key or cslug.endswith(key) or (len(key) >= 4 and key in cslug):
            variants.update(spoken)

    for v in variants:
        if _clubs_match(v, q):
            return True
        if _slug_name(v) in _slug_name(q):
            return True
    return False


def _sanitize_clubs_against_quote(
    from_club: str | None,
    to_club: str | None,
    quote: str,
    tip_text: str = "",
) -> tuple[str | None, str | None]:
    """Keep only clubs grounded in the extracted quote or the tip_text summary.

    tip_text (AI-generated summary) is used as fallback: a club the LLM correctly
    identified may not be repeated verbatim in the chosen quote snippet.
    """
    context = f"{quote} {tip_text}".strip()
    return (
        from_club if _club_in_quote(from_club, context) else None,
        to_club if _club_in_quote(to_club, context) else None,
    )


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
    "entourage",
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
    "partenza",    # addio/partenza senza destinazione specifica
    "addio",
    "in uscita",
    "separazion",
    "lascer",      # lascerà / lascerà il club
    "sondagg",     # sondaggio / sondaggi
    "sondato",
    "interessa",   # interessa al / interessato
    "pista",       # sulla pista di
    "ingaggio",
    "svincol",     # svincolato / svincolarsi
    "parametro zero",
    "scadenza",
    "accostament", # accostato/accostamento a un club
    "voce",        # voci che girano / voci di mercato
    "apprezz",     # apprezzato dalla dirigenza / struttura
    "obiettiv",    # obiettivo di mercato / priorità
    "pallino",     # meta giornalistica (obiettivo acquisition)
    "plusval",     # plusvalenza / plusvalenze
    "dialogh",     # dialoghi tra club
    "scambio",     # ipotesi scambio
    "dirigenz",    # struttura dirigenziale e mercato
    "concurrenz",  # concorrenza tra club per un giocatore
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
    q = _ascii_slug(quote)
    e = _ascii_slug(entity)
    if not e:
        return False
    if e in q:
        return True
    # fallback: last token (surname-ish) match, but avoid short noise
    tokens = [t for t in entity.replace("-", " ").split() if len(t) >= 4]
    if not tokens:
        return False
    return _ascii_slug(tokens[-1]) in q


def _is_plausible_mercato_tip(raw: _RawMercatoTip) -> bool:
    quote = (raw.quote_text or "").strip()
    if len(quote) < 15:
        return False

    # Require at least one club — tips without entity context are noise.
    if not (raw.from_club or raw.to_club):
        return False

    has_mercato_signal = _contains_any(quote, _MERCATO_SIGNAL)

    # If the quote screams match analysis and contains no mercato signals → drop.
    if _contains_any(quote, _NON_MERCATO_SIGNAL) and not has_mercato_signal:
        return False

    player_in_quote = bool(raw.player_name) and _quote_mentions_entity(quote, raw.player_name)
    from_in_quote = _club_in_quote(raw.from_club, quote) if raw.from_club else False
    to_in_quote = _club_in_quote(raw.to_club, quote) if raw.to_club else False

    # Fast-pass: player + at least one club in quote → trust the AI's extraction.
    # The AI may pick an informative quote that doesn't contain trigger words but is
    # clearly about a transfer (the club/player context is sufficient evidence).
    if player_in_quote and (from_in_quote or to_in_quote):
        return True

    # Fast-pass: renewal/extension — from_club == to_club and club appears in quote.
    # Player often doesn't say their own name; club presence is sufficient context.
    if raw.from_club and raw.from_club == raw.to_club and from_in_quote:
        return True

    # Allow explicit confirmed/denied phrasing even if quote is short or lacks signals.
    if raw.confidence in ("confirmed", "denied") and _contains_any(
        quote, (
            "ufficial", "è fatta", "fatta", "conferm", "smentit", "non si fa", "saltata",
            "non sta trattando", "non c'è stata", "nessuna trattativa", "nega", "non ci sono state",
            "non ci sono trattativ",
        )
    ):
        return True

    # Denied tips: trust AI context even when no entity appears verbatim in the quote.
    if raw.confidence == "denied" and has_mercato_signal:
        return True

    # Drop "is at club" statements without transfer verbs.
    if _contains_any(quote, (" è al ", " sta al ", " gioca nel ", " milita nel ")) and not _contains_any(
        quote, ("rinn", "firma", "tratt", "offert", "contatt", "arriv", "ced", "va via", "prest")
    ):
        return False

    # Mercato language + almeno un club ancorato nella citazione (fix: prima era sempre False).
    if has_mercato_signal and (from_in_quote or to_in_quote):
        return True

    # Fallback: il LLM può scegliere una quote focalizzata sui dettagli (cifre, formula,
    # timing) senza ripetere giocatore/club già nominati nel contesto precedente.
    # Se tip_text (sintesi AI, sempre entity-dense) ancora il giocatore e almeno un club,
    # e la quote contiene segnali di mercato oppure la confidence è alta → la tip è valida.
    tip_text = (raw.tip_text or "").strip()
    if tip_text and (raw.from_club or raw.to_club):
        player_in_tip = _quote_mentions_entity(tip_text, raw.player_name)
        from_in_tip = _club_in_quote(raw.from_club, tip_text) if raw.from_club else False
        to_in_tip = _club_in_quote(raw.to_club, tip_text) if raw.to_club else False
        if player_in_tip and (from_in_tip or to_in_tip) and (
            has_mercato_signal or raw.confidence in ("confirmed", "likely")
        ):
            return True

    return False


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


def _build_system_prompt(project_root: Path | None) -> str:
    """Costruisce il system prompt, iniettando la lista giocatori se disponibile."""
    if project_root is None:
        return MERCATO_SYSTEM
    try:
        player_list = get_player_list_for_prompt(project_root)
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
    model: str = "gpt-4.1-mini",
    context: dict[str, Any] | None = None,
    project_root: Path | None = None,
    base_url: str | None = None,
) -> list[MercatoTip]:
    """Estrae indiscrezioni di mercato da un transcript.

    Args:
        project_root: root del progetto; usato per caricare il registry giocatori
            (alias + transfer confermati) dal DB e iniettarlo nel prompt.
            Se None, si usa solo normalize_entity().

    Returns lista di MercatoTip (può essere vuota se il video non è di mercato).
    """
    text = _transcript_to_timestamped_text(data)
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
    user_parts.append(
        "\nTranscript (ogni riga: [secondi]s testo — copia quote_text solo dal testo, senza [..]s):\n"
        f"{text}"
    )
    user_content = "\n".join(user_parts)

    system_prompt = _build_system_prompt(project_root)
    parsed = await _run_extraction(api_key, model, user_content, system_prompt=system_prompt, base_url=base_url)

    now = datetime.now(UTC)
    # Fallback to start-of-day UTC so mentioned_at != extracted_at when publication date is unknown
    mentioned_at = ctx.get("mentioned_at") or now.replace(hour=0, minute=0, second=0, microsecond=0)

    _LOG.info("[mercato] AI returned %d raw tips for video %s", len(parsed.tips), video_id)

    tips: list[MercatoTip] = []
    for raw in parsed.tips:
        if not _is_plausible_mercato_tip(raw):
            _LOG.debug(
                "[mercato] DROP plausibility: %s (%s→%s) | quote: %.60s",
                raw.player_name, raw.from_club, raw.to_club, raw.quote_text or "",
            )
            continue
        _PLACEHOLDER_CLUBS = {"unknown", "null", "none", "n/a", "?", "-", ""}

        if project_root is not None:
            player = normalize_player_name(raw.player_name, project_root) or raw.player_name
            # Se la normalizzazione standard non ha trovato match e il LLM ha estratto
            # un club, prova il club-context matching con soglia fuzzy abbassata (70).
            if player == raw.player_name and (raw.from_club or raw.to_club):
                from media_advisor.mercato.player_normalizer import normalize_player_name_with_club_hint
                hint = normalize_player_name_with_club_hint(
                    raw.player_name,
                    project_root,
                    [raw.from_club, raw.to_club],
                )
                if hint != raw.player_name:
                    player = hint
        else:
            player = normalize_entity(raw.player_name) or raw.player_name
        _fc = raw.from_club if raw.from_club and raw.from_club.lower() not in _PLACEHOLDER_CLUBS else None
        _tc = raw.to_club if raw.to_club and raw.to_club.lower() not in _PLACEHOLDER_CLUBS else None
        from_club = normalize_entity(_fc) if _fc else None
        to_club = normalize_entity(_tc) if _tc else None
        from_club, to_club = _sanitize_clubs_against_quote(
            from_club, to_club, raw.quote_text or "", raw.tip_text or ""
        )
        if not (from_club or to_club):
            _LOG.debug(
                "[mercato] DROP clubs nullified: %s (%s→%s) | quote: %.60s",
                raw.player_name, raw.from_club, raw.to_club, raw.quote_text or "",
            )
            continue

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
    _LOG.info("[mercato] %d tip finali estratte su %d raw (video %s)", len(tips), len(parsed.tips), video_id)
    return tips


async def _run_extraction(
    api_key: str,
    model: str,
    user_content: str,
    system_prompt: str = MERCATO_SYSTEM,
    base_url: str | None = None,
) -> _ExtractMercatoResult:
    """Lancia l'estrazione AI. Prova PydanticAI, fallback su OpenAI diretto."""
    try:
        from pydantic_ai import Agent  # type: ignore[import-untyped]
        from pydantic_ai.models.openai import OpenAIModel  # type: ignore[import-untyped]

        os.environ.setdefault("OPENAI_API_KEY", api_key)
        try:
            llm = OpenAIModel(model, api_key=api_key, base_url=base_url)
        except TypeError:
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
        record_pydantic_ai_run_usage(model, result.usage())
        return result.output
    except Exception:
        return await _openai_fallback(api_key, model, user_content, system_prompt=system_prompt, base_url=base_url)


async def _openai_fallback(
    api_key: str,
    model: str,
    user_content: str,
    system_prompt: str = MERCATO_SYSTEM,
    base_url: str | None = None,
) -> _ExtractMercatoResult:
    import json

    import openai  # type: ignore[import-untyped]

    client = openai.AsyncOpenAI(api_key=api_key, base_url=base_url)
    completion = await client.chat.completions.create(
        model=model,
        temperature=1.0,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        response_format={"type": "json_object"},
    )
    record_openai_chat_completion(model, completion)
    content = completion.choices[0].message.content
    if not content:
        return _ExtractMercatoResult()
    # Strip thinking blocks emitted by reasoning models (Qwen3, DeepSeek-R1, ecc.)
    # before parsing, otherwise json.loads fails on the <think>...</think> preamble.
    content = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL | re.IGNORECASE).strip()
    if not content:
        return _ExtractMercatoResult()
    try:
        data = json.loads(content)
        # Normalize "tip" (singular, emitted by some models) → "tips" (canonical field name).
        if isinstance(data, dict) and "tip" in data and "tips" not in data:
            data["tips"] = data.pop("tip")
        # Normalize bare list (e.g. Qwen2.5 returns [...] instead of {"tips": [...]}).
        if isinstance(data, list):
            data = {"tips": data}
        return _ExtractMercatoResult.model_validate(data)
    except Exception:
        return _ExtractMercatoResult()
