"""Orchestratore per l'analisi mercato di un singolo video.

Flusso:
  1. Legge il transcript (DB)
  2. Estrae le tip via AI
  3. Corrobora con l'index globale (opzionale, può essere batched)
  4. Salva risultato video e index in SQLite
"""

from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from media_advisor.db.repository import (
    fetch_mercato_video_result_payload,
    upsert_mercato_global_index,
    upsert_mercato_video_result,
)
from media_advisor.db.session import session_scope
from media_advisor.io.channel_store import load_video_dates_dict
from media_advisor.io.json_io import read_json
from media_advisor.io.paths import mercato_tips_path
from media_advisor.io.transcript_storage import load_transcript_dict
from media_advisor.mercato.aggregator import load_index
from media_advisor.mercato.corroborator import corroborate
from media_advisor.mercato.extractor import extract_mercato_tips
from media_advisor.mercato.models import MercatoIndex, MercatoTip, OutcomeValue, VideoMercatoResult
from media_advisor.mercato.quote_timing import try_align_mercato_tip
from media_advisor.models.transcript import TranscriptResponse


def _mentioned_at_from_string(value: object | None) -> datetime | None:
    if value is None:
        return None
    try:
        dt = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt


def _save_index(root: Path, index: MercatoIndex) -> None:
    index.updated_at = datetime.now(UTC)
    with session_scope(root) as session:
        upsert_mercato_global_index(session, index.model_dump(mode="json"))


def save_mercato_index(root: Path, index: MercatoIndex) -> None:
    """Persist MercatoIndex to SQLite (verifier / CLI)."""
    _save_index(root, index)


def update_index_with_new_tips(root: Path, all_tips: list[MercatoTip]) -> None:
    """Corrobora e salva l'index una sola volta per un batch di tip.

    Usare al posto di update_index=True quando si analizzano più video
    in sequenza (evita N letture+scritture del file index).
    """
    if not all_tips:
        return
    index = load_index(root)
    corroborate(index, all_tips)
    _save_index(root, index)


def update_tip_date(
    root: Path,
    tip_id: str,
    mentioned_at: datetime,
) -> MercatoTip:
    """Imposta la data di pubblicazione (mentioned_at) di una tip.

    Usato quando il video non aveva published_at al momento dell'estrazione.
    Solleva KeyError se non trovata.
    """
    index = load_index(root)
    tip = next((t for t in index.tips if t.tip_id == tip_id), None)
    if tip is None:
        raise KeyError(f"Tip {tip_id} non trovata nell'index")

    tip.mentioned_at = mentioned_at
    _save_index(root, index)
    return tip


def update_tip_outcome(
    root: Path,
    tip_id: str,
    outcome: OutcomeValue,
    notes: str | None = None,
    source: str = "manual",
) -> MercatoTip:
    """Aggiorna l'esito di una tip nell'index globale.

    Restituisce la tip aggiornata. Solleva KeyError se non trovata.
    """
    from media_advisor.mercato.models import OutcomeSource

    index = load_index(root)
    tip = next((t for t in index.tips if t.tip_id == tip_id), None)
    if tip is None:
        raise KeyError(f"Tip {tip_id} non trovata nell'index")

    tip.outcome = outcome
    tip.outcome_updated_at = datetime.now(UTC)
    tip.outcome_source = cast(OutcomeSource, source)
    if notes is not None:
        tip.outcome_notes = notes

    _save_index(root, index)
    return tip


async def analyze_video_mercato(
    root: Path,
    video_id: str,
    channel_id: str,
    api_key: str,
    model: str = "gpt-4.1-mini",
    force: bool = False,
    update_index: bool = True,
    dates_cache: dict | None = None,
    base_url: str | None = None,
) -> VideoMercatoResult:
    """Analizza un video per indiscrezioni di mercato.

    Il transcript deve essere nel DB. Se update_index=False, salva solo il risultato video
    e non tocca l'index globale (utile per batch: update_index_with_new_tips() alla fine).
    """
    if not force:
        with session_scope(root, read_only=True) as session:
            from_db = fetch_mercato_video_result_payload(session, channel_id, video_id)
        if from_db:
            return VideoMercatoResult.model_validate(from_db)
        legacy = mercato_tips_path(root, channel_id, video_id)
        if legacy.exists():
            data = read_json(legacy)
            with session_scope(root) as session:
                upsert_mercato_video_result(session, channel_id, video_id, data)
            return VideoMercatoResult.model_validate(data)

    raw_tr = load_transcript_dict(root, channel_id, video_id)
    if raw_tr is None:
        raise FileNotFoundError(f"Transcript non trovato in DB: {channel_id}/{video_id}")

    transcript = TranscriptResponse.model_validate(raw_tr)
    meta = transcript.metadata

    mentioned_at: datetime | None = None
    if meta and meta.published_at:
        mentioned_at = _mentioned_at_from_string(meta.published_at)

    if mentioned_at is None:
        if dates_cache is None:
            dates_cache = load_video_dates_dict(root)
        mentioned_at = _mentioned_at_from_string(dates_cache.get(video_id))

    context = {
        "title": meta.title if meta else None,
        "opinionist": channel_id,
        "published_at": meta.published_at if meta else None,
        "mentioned_at": mentioned_at,
    }

    tips: list[MercatoTip] = await extract_mercato_tips(
        data=transcript,
        video_id=video_id,
        channel_id=channel_id,
        api_key=api_key,
        model=model,
        context=context,
        project_root=root,
        base_url=base_url,
    )

    adjusted: list[MercatoTip] = []
    for tip in tips:
        st, en = try_align_mercato_tip(root, tip)
        upd: dict = {}
        if st is not None:
            upd["quote_start_sec"] = st
        if en is not None:
            upd["quote_end_sec"] = en
        adjusted.append(tip.model_copy(update=upd) if upd else tip)
    tips = adjusted

    result = VideoMercatoResult(
        video_id=video_id,
        channel_id=channel_id,
        extracted_at=datetime.now(UTC),
        video_title=meta.title if meta else None,
        video_published_at=mentioned_at,
        tips=tips,
    )

    payload = result.model_dump(mode="json")
    with session_scope(root) as session:
        upsert_mercato_video_result(session, channel_id, video_id, payload)

    if tips and update_index:
        index = load_index(root)
        corroborate(index, tips)
        _save_index(root, index)

    return result
