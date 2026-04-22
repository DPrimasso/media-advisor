"""Orchestratore per l'analisi mercato di un singolo video.

Flusso:
  1. Legge il transcript salvato
  2. Estrae le tip via AI
  3. Corrobora con l'index globale (opzionale, può essere batched)
  4. Salva mercato/tips/{channel_id}/{video_id}.json
  5. Aggiorna mercato/index.json
"""

from datetime import datetime, timezone
from pathlib import Path
from typing import cast

from media_advisor.io.json_io import read_json, read_json_or_default, write_json
from media_advisor.io.paths import mercato_index_path, mercato_tips_path, transcript_path
from media_advisor.mercato.aggregator import load_index
from media_advisor.mercato.corroborator import corroborate
from media_advisor.mercato.extractor import extract_mercato_tips
from media_advisor.mercato.models import MercatoIndex, MercatoTip, OutcomeValue, VideoMercatoResult
from media_advisor.models.transcript import TranscriptResponse


def _save_index(root: Path, index: MercatoIndex) -> None:
    index.updated_at = datetime.now(timezone.utc)
    write_json(mercato_index_path(root), index.model_dump(mode="json"))


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
    idx_path = mercato_index_path(root)
    data = read_json_or_default(idx_path)
    if data is None:
        raise FileNotFoundError("Index mercato non trovato")

    index = MercatoIndex.model_validate(data)
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
    from typing import cast
    from media_advisor.mercato.models import OutcomeSource

    idx_path = mercato_index_path(root)
    data = read_json_or_default(idx_path)
    if data is None:
        raise FileNotFoundError("Index mercato non trovato")

    index = MercatoIndex.model_validate(data)
    tip = next((t for t in index.tips if t.tip_id == tip_id), None)
    if tip is None:
        raise KeyError(f"Tip {tip_id} non trovata nell'index")

    tip.outcome = outcome
    tip.outcome_updated_at = datetime.now(timezone.utc)
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
) -> VideoMercatoResult:
    """Analizza un video per indiscrezioni di mercato.

    Il transcript deve già essere in data/transcripts/{channel_id}/{video_id}.json.
    Se update_index=False, salva solo il file video e non tocca l'index globale
    (utile per batch: chiamare update_index_with_new_tips() alla fine).
    """
    out_path = mercato_tips_path(root, channel_id, video_id)

    if out_path.exists() and not force:
        data = read_json(out_path)
        return VideoMercatoResult.model_validate(data)

    t_path = transcript_path(root, channel_id, video_id)
    if not t_path.exists():
        raise FileNotFoundError(f"Transcript non trovato: {t_path}")

    transcript = TranscriptResponse.model_validate(read_json(t_path))
    meta = transcript.metadata

    mentioned_at: datetime | None = None
    if meta and meta.published_at:
        dt = datetime.fromisoformat(str(meta.published_at))
        # Ensure timezone-aware
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        mentioned_at = dt

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
        data_dir=root / "mercato",
    )

    result = VideoMercatoResult(
        video_id=video_id,
        channel_id=channel_id,
        extracted_at=datetime.now(timezone.utc),
        video_title=meta.title if meta else None,
        video_published_at=mentioned_at,
        tips=tips,
    )

    write_json(out_path, result.model_dump(mode="json"))

    if tips and update_index:
        index = load_index(root)
        corroborate(index, tips)
        _save_index(root, index)

    return result
