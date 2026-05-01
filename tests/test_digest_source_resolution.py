"""Matching digest righe ↔ MercatoTip per link Verifica."""

from datetime import datetime, timezone
from pathlib import Path

import pytest

from media_advisor.digest import (
    DigestItem,
    _ordered_channel_ids_from_fonte,
    _resolve_digest_sources_for_row,
    build_enriched_digest_sections,
    flatten_digest_items_for_api,
    sections_from_flat_digest_items,
)
from media_advisor.mercato.models import MercatoTip
from media_advisor.models.channels import ChannelConfig, ChannelsConfig

_UTC = timezone.utc
_EX = datetime(2026, 4, 1, 12, 0, tzinfo=_UTC)


def _tip(
    *,
    channel_id: str,
    player: str,
    video_id: str,
    from_club: str | None = "Inter",
    to_club: str | None = None,
    quote_start: float | None = 120.0,
) -> MercatoTip:
    return MercatoTip(
        tip_id="00000000-0000-4000-8000-000000000001",
        video_id=video_id,
        channel_id=channel_id,
        extracted_at=_EX,
        player_name=player,
        from_club=from_club,
        to_club=to_club,
        tip_text="sintesi breve",
        quote_text="quote",
        quote_start_sec=quote_start,
    )


@pytest.fixture
def sample_cfg() -> ChannelsConfig:
    return ChannelsConfig(
        channels=[
            ChannelConfig(
                id="fabrizio-romano-italiano",
                name="Fabrizio Romano Italiano",
                order=1,
                video_list="x.json",
                mercato_channel=True,
            ),
            ChannelConfig(
                id="tuttomercatoweb",
                name="TuttoMercatoWeb.com",
                order=2,
                video_list="y.json",
                mercato_channel=True,
            ),
        ]
    )


def test_ordered_channel_ids_from_comma_separated_fonte(sample_cfg: ChannelsConfig) -> None:
    fonte = "Fabrizio Romano Italiano, TuttoMercatoWeb.com"
    ids = _ordered_channel_ids_from_fonte(fonte, sample_cfg)
    assert ids == ["fabrizio-romano-italiano", "tuttomercatoweb"]


def test_resolve_digest_picks_earliest_timestamp_per_channel(sample_cfg: ChannelsConfig) -> None:
    id_to_name = {c.id: c.name for c in sample_cfg.channels}
    tips = [
        _tip(
            channel_id="fabrizio-romano-italiano",
            player="Lautaro Martinez",
            video_id="early",
            quote_start=300.0,
        ),
        _tip(
            channel_id="fabrizio-romano-italiano",
            player="Lautaro Martinez",
            video_id="late",
            quote_start=10.0,
        ),
    ]
    row = {
        "player": "Lautaro Martinez",
        "club": "Inter",
        "movimento": "rinnovo",
        "stato": "caldo",
        "motivo": "test",
        "fonte": "Fabrizio Romano Italiano",
    }
    sources = _resolve_digest_sources_for_row(row, tips, sample_cfg, id_to_name, Path("."))
    assert len(sources) == 1
    assert sources[0].video_id == "late"
    assert sources[0].watch_url.endswith("&t=10")


def test_club_tie_break_prefers_matching_club(sample_cfg: ChannelsConfig) -> None:
    id_to_name = {c.id: c.name for c in sample_cfg.channels}
    tips = [
        _tip(
            channel_id="fabrizio-romano-italiano",
            player="Test Player",
            video_id="wrong",
            from_club="Milan",
            to_club=None,
            quote_start=5.0,
        ),
        _tip(
            channel_id="fabrizio-romano-italiano",
            player="Test Player",
            video_id="right",
            from_club="Inter",
            to_club=None,
            quote_start=99.0,
        ),
    ]
    row = {
        "player": "Test Player",
        "club": "Inter",
        "movimento": "cessione",
        "stato": "caldo",
        "motivo": "x",
        "fonte": "Fabrizio Romano Italiano",
    }
    sources = _resolve_digest_sources_for_row(row, tips, sample_cfg, id_to_name, Path("."))
    assert len(sources) == 1
    assert sources[0].video_id == "right"


def test_flatten_and_roundtrip_digest_items() -> None:
    sections = {
        "✅ Situazioni calde / scenari aperti": [
            DigestItem(
                player="A",
                club="B",
                movimento="m",
                stato="caldo",
                motivo="mot",
                fonte="F",
                sources=[],
            )
        ],
        "🕐 Situazioni da monitorare": [],
        "🚫 Voci ridimensionate / smentite": [],
    }
    flat = flatten_digest_items_for_api(sections)
    assert flat[0]["section"] == "✅ Situazioni calde / scenari aperti"
    assert flat[0]["player"] == "A"
    back = sections_from_flat_digest_items(flat)
    assert back["✅ Situazioni calde / scenari aperti"][0].player == "A"


def test_build_enriched_digest_sections_uses_disk(tmp_path) -> None:
    """Smoke: con channels.json + index vuoto non crasha."""
    import json

    (tmp_path / "channels").mkdir()
    (tmp_path / "channels" / "channels.json").write_text(
        json.dumps(
            {
                "channels": [
                    {
                        "id": "fabrizio-romano-italiano",
                        "name": "Fabrizio Romano Italiano",
                        "order": 1,
                        "video_list": "x.json",
                        "mercato_channel": True,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "mercato").mkdir()
    (tmp_path / "mercato" / "index.json").write_text(
        json.dumps({"updated_at": _EX.isoformat(), "tips": []}),
        encoding="utf-8",
    )

    from datetime import date as date_cls

    digest = """✅ Situazioni calde / scenari aperti
X (Inter) - Movimento: test; Stato: caldo; Motivo: motivo breve; Fonte: Fabrizio Romano Italiano

🕐 Situazioni da monitorare
Y (Milan) - Movimento: test2; Stato: monitorare; Motivo: motivo2; Fonte: Fabrizio Romano Italiano

🚫 Voci ridimensionate / smentite
Z (Roma) - Movimento: test3; Stato: smentita; Motivo: motivo3; Fonte: Fabrizio Romano Italiano
"""
    enriched, _ = build_enriched_digest_sections(tmp_path, date_cls(2026, 5, 1), digest, tips=[])
    assert len(enriched["✅ Situazioni calde / scenari aperti"]) == 1
    assert enriched["✅ Situazioni calde / scenari aperti"][0].sources == []
