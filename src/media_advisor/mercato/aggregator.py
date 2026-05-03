"""Aggregazione per-player e calcolo veracity score per canale."""

import logging
import re
import unicodedata
from datetime import date, timedelta
from datetime import datetime, timezone
from pathlib import Path

import json

from pydantic import ValidationError

from media_advisor.db.repository import fetch_mercato_global_index_json, upsert_mercato_global_index
from media_advisor.db.session import session_scope
from media_advisor.io.paths import mercato_index_path
from media_advisor.mercato.corroborator import _is_renewal_tip, _same_session
from media_advisor.mercato.models import (
    ChannelVeracityStats,
    MercatoIndex,
    MercatoTip,
    PlayerSummary,
)


def _player_slug(name: str) -> str:
    """Converti nome giocatore in slug URL-safe."""
    return re.sub(r"[^a-z0-9]+", "-", name.lower().strip()).strip("-")


def load_index(root: Path) -> MercatoIndex:
    log = logging.getLogger(__name__)
    with session_scope(root) as session:
        raw = fetch_mercato_global_index_json(session)
        if raw:
            try:
                return MercatoIndex.model_validate(json.loads(raw))
            except (json.JSONDecodeError, ValidationError) as exc:
                log.warning("Mercato index blob non valido: %s", exc)
        p = mercato_index_path(root)
        if p.exists():
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    upsert_mercato_global_index(session, data)
                    return MercatoIndex.model_validate(data)
            except (json.JSONDecodeError, OSError, ValidationError) as exc:
                log.warning("Mercato index file non valido (%s): %s", p, exc)
    return MercatoIndex(updated_at=datetime.now(timezone.utc), tips=[])


def _is_pending_outcome(outcome: str) -> bool:
    return outcome in {"non_verificata", "non_conclusa"}


def _normalize_player_names_inplace(tips: list[MercatoTip], root: Path) -> list[MercatoTip]:
    from media_advisor.mercato.player_normalizer import normalize_player_name

    for tip in tips:
        tip.player_name = normalize_player_name(tip.player_name, root)
    return tips


def get_all_tips(root: Path) -> list[MercatoTip]:
    return _normalize_player_names_inplace(load_index(root).tips, root)


def get_tips_for_date(root: Path, target_date: date) -> list[MercatoTip]:
    next_day = target_date + timedelta(days=1)
    tips = [
        tip for tip in load_index(root).tips
        if tip.mentioned_at and (
            tip.mentioned_at.date() == target_date
            # Tip estratte il giorno dopo con mentioned_at = mezzanotte esatta UTC:
            # firma del fallback in extractor.py quando il video non aveva data disponibile.
            # Quei video erano quasi certamente pubblicati il giorno target.
            or (
                tip.mentioned_at.date() == next_day
                and tip.mentioned_at.hour == 0
                and tip.mentioned_at.minute == 0
                and tip.mentioned_at.second == 0
                and tip.extracted_at is not None
                and tip.extracted_at.date() == next_day
            )
        )
    ]
    return _normalize_player_names_inplace(tips, root)


def get_tips_for_player(root: Path, player_slug: str) -> PlayerSummary | None:
    """Restituisce un PlayerSummary per il giocatore identificato dallo slug."""
    all_tips = get_all_tips(root)

    matched = [t for t in all_tips if _player_slug(t.player_name) == player_slug]
    if not matched:
        return None

    player_name = matched[0].player_name
    dated = [t.mentioned_at for t in matched if t.mentioned_at is not None]
    latest = max(dated, default=None)
    _epoch = datetime.min.replace(tzinfo=timezone.utc)

    return PlayerSummary(
        player_name=player_name,
        player_slug=player_slug,
        total_tips=len(matched),
        pending_tips=sum(1 for t in matched if _is_pending_outcome(t.outcome)),
        true_tips=sum(1 for t in matched if t.outcome == "confermata"),
        false_tips=sum(1 for t in matched if t.outcome == "smentita"),
        partial_tips=sum(1 for t in matched if t.outcome == "parziale"),
        channels_mentioned=sorted({t.channel_id for t in matched}),
        latest_mention=latest,
        tips=sorted(matched, key=lambda t: t.mentioned_at or _epoch, reverse=True),
    )


def get_all_players(root: Path) -> list[PlayerSummary]:
    """Restituisce un PlayerSummary per ogni giocatore distinto nell'index."""
    all_tips = get_all_tips(root)

    by_slug: dict[str, list[MercatoTip]] = {}
    for tip in all_tips:
        slug = _player_slug(tip.player_name)
        by_slug.setdefault(slug, []).append(tip)

    summaries: list[PlayerSummary] = []
    _epoch = datetime.min.replace(tzinfo=timezone.utc)
    for slug, tips in by_slug.items():
        dated = [t.mentioned_at for t in tips if t.mentioned_at is not None]
        latest = max(dated, default=None)
        summaries.append(
            PlayerSummary(
                player_name=tips[0].player_name,
                player_slug=slug,
                total_tips=len(tips),
                pending_tips=sum(1 for t in tips if _is_pending_outcome(t.outcome)),
                true_tips=sum(1 for t in tips if t.outcome == "confermata"),
                false_tips=sum(1 for t in tips if t.outcome == "smentita"),
                partial_tips=sum(1 for t in tips if t.outcome == "parziale"),
                channels_mentioned=sorted({t.channel_id for t in tips}),
                latest_mention=latest,
                tips=sorted(tips, key=lambda t: t.mentioned_at or _epoch, reverse=True),
            )
        )

    return sorted(summaries, key=lambda p: p.total_tips, reverse=True)


def _slug_name(name: str) -> str:
    # Normalize accents and odd unicode to improve matching (e.g. "Atlético" vs "Atletico").
    norm = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]", "", norm.lower())


def _clubs_match(a: str | None, b: str | None) -> bool:
    if not a or not b:
        return False
    sa, sb = _slug_name(a), _slug_name(b)
    if not sa or not sb:
        return False
    if sa == sb:
        return True
    if len(sa) >= 3 and (sa in sb or sb in sa):
        return True

    # Fuzzy fallback for minor corruption / missing chars (e.g. "atltico" vs "atletico").
    # Avoids false contradictions in UI.
    if min(len(sa), len(sb)) >= 6:
        from difflib import SequenceMatcher

        if SequenceMatcher(a=sa, b=sb).ratio() >= 0.9:
            return True
    return False


def build_tip_context(all_tips: list[MercatoTip]) -> dict[str, dict]:
    """Per ogni tip, calcola le tip correlate divise per canale e coerenza.

    Stesso canale, video diverso:
      - stesso to_club (o entrambi None) → "same_channel_consistent"
      - to_club diversi → "same_channel_inconsistent"

    Canale diverso:
      - stesso to_club (o entrambi None) → "other_channel_confirming"
      - to_club diversi → "other_channel_contradicting"

    Coppie ignorate: sessioni diverse (>7 mesi) o rinnovo vs cessione.
    """
    from collections import defaultdict

    by_player: dict[str, list[MercatoTip]] = defaultdict(list)
    for tip in all_tips:
        by_player[_player_slug(tip.player_name)].append(tip)

    is_renewal: dict[str, bool] = {t.tip_id: _is_renewal_tip(t) for t in all_tips}

    context: dict[str, dict] = {}

    for tip in all_tips:
        slug = _player_slug(tip.player_name)
        player_tips = by_player[slug]

        same_consistent: list[dict] = []
        same_inconsistent: list[dict] = []
        other_confirming: list[dict] = []
        other_contradicting: list[dict] = []

        tip_is_renewal = is_renewal[tip.tip_id]

        for other in player_tips:
            if other.tip_id == tip.tip_id:
                continue
            if other.video_id == tip.video_id:
                continue  # stesso video, skip
            if not _same_session(tip, other):
                continue
            if tip_is_renewal != is_renewal[other.tip_id]:
                continue

            preview = {
                "tip_id": other.tip_id,
                "channel_id": other.channel_id,
                "tip_text": other.tip_text,
                "to_club": other.to_club,
                "from_club": other.from_club,
                "mentioned_at": other.mentioned_at.isoformat() if other.mentioned_at else None,
                "outcome": other.outcome,
                "confidence": other.confidence,
            }

            clubs_agree = _clubs_match(tip.to_club, other.to_club) or (not tip.to_club and not other.to_club)
            clubs_conflict = tip.to_club and other.to_club and not _clubs_match(tip.to_club, other.to_club)

            same_channel = other.channel_id == tip.channel_id

            if same_channel:
                if clubs_conflict:
                    same_inconsistent.append(preview)
                elif clubs_agree:
                    same_consistent.append(preview)
            else:
                if clubs_conflict:
                    other_contradicting.append(preview)
                elif clubs_agree:
                    other_confirming.append(preview)

        context[tip.tip_id] = {
            "same_channel_consistent": same_consistent,
            "same_channel_inconsistent": same_inconsistent,
            "other_channel_confirming": other_confirming,
            "other_channel_contradicting": other_contradicting,
        }

    return context


def get_channel_stats(root: Path) -> list[ChannelVeracityStats]:
    """Calcola veracity score per ogni canale."""
    all_tips = get_all_tips(root)

    by_channel: dict[str, list[MercatoTip]] = {}
    for tip in all_tips:
        by_channel.setdefault(tip.channel_id, []).append(tip)

    stats: list[ChannelVeracityStats] = []
    for channel_id, tips in by_channel.items():
        true_n = sum(1 for t in tips if t.outcome == "confermata")
        false_n = sum(1 for t in tips if t.outcome == "smentita")
        partial_n = sum(1 for t in tips if t.outcome == "parziale")
        resolved = true_n + false_n + partial_n

        # partial conta 0.5
        score: float | None = None
        if resolved > 0:
            score = round((true_n + partial_n * 0.5) / resolved, 3)

        stats.append(
            ChannelVeracityStats(
                channel_id=channel_id,
                total_tips=len(tips),
                resolved_tips=resolved,
                true_tips=true_n,
                false_tips=false_n,
                partial_tips=partial_n,
                veracity_score=score,
            )
        )

    return sorted(stats, key=lambda s: s.total_tips, reverse=True)


def rebuild_index(root: Path) -> None:
    """Ricalcola l'index globale da tutti i VideoMercatoResult nel DB."""
    import json
    from datetime import datetime, timezone

    from media_advisor.db.repository import list_mercato_video_result_rows
    from media_advisor.db.session import session_scope
    from media_advisor.mercato.analyzer import save_mercato_index
    from media_advisor.mercato.corroborator import corroborate
    from media_advisor.mercato.models import MercatoIndex, VideoMercatoResult

    all_tips: list[MercatoTip] = []
    with session_scope(root, read_only=True) as session:
        for row in list_mercato_video_result_rows(session, None):
            try:
                vr = VideoMercatoResult.model_validate(json.loads(row.payload_json))
                all_tips.extend(vr.tips or [])
            except Exception:
                continue
    index = MercatoIndex(updated_at=datetime.now(timezone.utc), tips=[])
    for tip in all_tips:
        corroborate(index, [tip])
    save_mercato_index(root, index)
