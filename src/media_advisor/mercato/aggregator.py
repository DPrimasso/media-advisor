"""Aggregazione per-player e calcolo veracity score per canale."""

import re
from datetime import datetime, timezone
from pathlib import Path

from media_advisor.io.json_io import read_json_or_default
from media_advisor.io.paths import mercato_index_path
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
    data = read_json_or_default(mercato_index_path(root), default=None)
    if data is None:
        return MercatoIndex(updated_at=datetime.now(timezone.utc), tips=[])
    return MercatoIndex.model_validate(data)


def get_all_tips(root: Path) -> list[MercatoTip]:
    return load_index(root).tips


def get_tips_for_player(root: Path, player_slug: str) -> PlayerSummary | None:
    """Restituisce un PlayerSummary per il giocatore identificato dallo slug."""
    all_tips = get_all_tips(root)

    matched = [t for t in all_tips if _player_slug(t.player_name) == player_slug]
    if not matched:
        return None

    player_name = matched[0].player_name
    latest = max((t.mentioned_at for t in matched), default=None)

    return PlayerSummary(
        player_name=player_name,
        player_slug=player_slug,
        total_tips=len(matched),
        pending_tips=sum(1 for t in matched if t.outcome == "pending"),
        true_tips=sum(1 for t in matched if t.outcome == "true"),
        false_tips=sum(1 for t in matched if t.outcome == "false"),
        partial_tips=sum(1 for t in matched if t.outcome == "partial"),
        channels_mentioned=sorted({t.channel_id for t in matched}),
        latest_mention=latest,
        tips=sorted(matched, key=lambda t: t.mentioned_at, reverse=True),
    )


def get_all_players(root: Path) -> list[PlayerSummary]:
    """Restituisce un PlayerSummary per ogni giocatore distinto nell'index."""
    all_tips = get_all_tips(root)

    by_slug: dict[str, list[MercatoTip]] = {}
    for tip in all_tips:
        slug = _player_slug(tip.player_name)
        by_slug.setdefault(slug, []).append(tip)

    summaries: list[PlayerSummary] = []
    for slug, tips in by_slug.items():
        latest = max((t.mentioned_at for t in tips), default=None)
        summaries.append(
            PlayerSummary(
                player_name=tips[0].player_name,
                player_slug=slug,
                total_tips=len(tips),
                pending_tips=sum(1 for t in tips if t.outcome == "pending"),
                true_tips=sum(1 for t in tips if t.outcome == "true"),
                false_tips=sum(1 for t in tips if t.outcome == "false"),
                partial_tips=sum(1 for t in tips if t.outcome == "partial"),
                channels_mentioned=sorted({t.channel_id for t in tips}),
                latest_mention=latest,
                tips=sorted(tips, key=lambda t: t.mentioned_at, reverse=True),
            )
        )

    return sorted(summaries, key=lambda p: p.total_tips, reverse=True)


def get_channel_stats(root: Path) -> list[ChannelVeracityStats]:
    """Calcola veracity score per ogni canale."""
    all_tips = get_all_tips(root)

    by_channel: dict[str, list[MercatoTip]] = {}
    for tip in all_tips:
        by_channel.setdefault(tip.channel_id, []).append(tip)

    stats: list[ChannelVeracityStats] = []
    for channel_id, tips in by_channel.items():
        true_n = sum(1 for t in tips if t.outcome == "true")
        false_n = sum(1 for t in tips if t.outcome == "false")
        partial_n = sum(1 for t in tips if t.outcome == "partial")
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
