from datetime import date, datetime

from media_advisor.digest import (
    DigestItem,
    DigestItemSource,
    format_mercato_report_telegram,
    format_mercato_report_twitter,
)


def test_format_mercato_report_telegram_is_readable_plain_text() -> None:
    digest = """✅ Situazioni calde / scenari aperti
Alisson (Liverpool) - Movimento: acquisto; Stato: caldo; Motivo: intesa verbale avanzata; Fonte: Fabrizio Romano Italiano

🕐 Situazioni da monitorare
John Stones (Manchester City) - Movimento: possibile partenza; Stato: monitorare; Motivo: offerta italiana in valutazione; Fonte: Fabrizio Romano Italiano

🚫 Voci ridimensionate / smentite
Ederson (Atalanta) - Movimento: sondaggio; Stato: smentita; Motivo: nessun contatto concreto; Fonte: Nicolò Schira
"""
    rendered = format_mercato_report_telegram(
        date(2026, 4, 23),
        digest,
        generated_at=datetime(2026, 4, 23, 12, 59),
    )

    # Header e metadata
    assert "CALCIOMERCATO" in rendered
    assert "23 Aprile 2026" in rendered
    assert "3" in rendered  # total notizie
    assert "Aggiornato alle 12:59" in rendered

    # Sezioni presenti
    assert "CALDE" in rendered
    assert "DA MONITORARE" in rendered
    assert "RIDIMENSIONATE" in rendered

    # Contenuto tip
    assert "Alisson" in rendered
    assert "Liverpool" in rendered
    assert "acquisto" in rendered
    assert "intesa verbale avanzata" in rendered
    assert "Fabrizio Romano Italiano" in rendered
    assert "John Stones" in rendered
    assert "Ederson" in rendered

    # Formato HTML (non markdown)
    assert "<b>" in rendered
    assert "<i>" in rendered
    assert "**" not in rendered
    assert "`" not in rendered
    assert "→" in rendered  # freccia unicode, non ->


def test_format_mercato_report_twitter_is_readable_plain_text() -> None:
    digest = """✅ Situazioni calde / scenari aperti
Alisson (Liverpool) - Movimento: acquisto; Stato: caldo; Motivo: intesa verbale avanzata; Fonte: Fabrizio Romano Italiano

🕐 Situazioni da monitorare
John Stones (Manchester City) - Movimento: possibile partenza; Stato: monitorare; Motivo: offerta italiana in valutazione; Fonte: Fabrizio Romano Italiano

🚫 Voci ridimensionate / smentite
Ederson (Atalanta) - Movimento: sondaggio; Stato: smentita; Motivo: nessun contatto concreto; Fonte: Nicolò Schira
"""
    rendered = format_mercato_report_twitter(
        date(2026, 4, 23),
        digest,
        generated_at=datetime(2026, 4, 23, 12, 59),
    )

    assert "CALCIOMERCATO | 23 Aprile 2026" in rendered
    assert "3 notizie: 1 calde, 1 monitorare, 1 ridimensionate" in rendered
    assert "🔥 CALDE" in rendered
    assert "👀 MONITORARE" in rendered
    assert "🧊 RIDIMENSIONATE" in rendered
    assert "Alisson (Liverpool): acquisto." in rendered
    assert "John Stones (Manchester City): possibile partenza." in rendered
    assert "Ederson (Atalanta): sondaggio." in rendered
    assert "Aggiornato alle 12:59" in rendered
    assert "#Calciomercato #SerieA" in rendered
    assert "<b>" not in rendered
    assert "<i>" not in rendered


def test_format_mercato_report_telegram_includes_verifica_when_enriched() -> None:
    digest = """✅ Situazioni calde / scenari aperti
Alisson (Liverpool) - Movimento: acquisto; Stato: caldo; Motivo: intesa verbale avanzata; Fonte: Fabrizio Romano Italiano

🕐 Situazioni da monitorare

🚫 Voci ridimensionate / smentite
"""
    src = DigestItemSource(
        channel_id="fabrizio-romano-italiano",
        channel_label="Fabrizio Romano Italiano",
        video_id="abc123",
        video_title=None,
        start_sec=45.0,
        watch_url="https://www.youtube.com/watch?v=abc123&t=45",
    )
    item = DigestItem(
        player="Alisson",
        club="Liverpool",
        movimento="acquisto",
        stato="caldo",
        motivo="intesa verbale avanzata",
        fonte="Fabrizio Romano Italiano",
        sources=[src],
    )
    sections = {
        "✅ Situazioni calde / scenari aperti": [item],
        "🕐 Situazioni da monitorare": [],
        "🚫 Voci ridimensionate / smentite": [],
    }
    rendered = format_mercato_report_telegram(
        date(2026, 4, 23),
        digest,
        generated_at=datetime(2026, 4, 23, 12, 59),
        section_items_enriched=sections,
    )
    assert "<i>Verifica:</i>" in rendered
    assert "youtube.com/watch?v=abc123" in rendered
    assert "Fabrizio Romano Italiano (0:45)" in rendered


def test_format_mercato_report_twitter_includes_verifica_urls_when_enriched() -> None:
    digest = """✅ Situazioni calde / scenari aperti
Alisson (Liverpool) - Movimento: acquisto; Stato: caldo; Motivo: test; Fonte: Fabrizio Romano Italiano

🕐 Situazioni da monitorare

🚫 Voci ridimensionate / smentite
"""
    src = DigestItemSource(
        channel_id="fabrizio-romano-italiano",
        channel_label="Fabrizio Romano Italiano",
        video_id="xyz",
        video_title=None,
        start_sec=12.0,
        watch_url="https://www.youtube.com/watch?v=xyz&t=12s",
    )
    item = DigestItem(
        player="Alisson",
        club="Liverpool",
        movimento="acquisto",
        stato="caldo",
        motivo="test",
        fonte="Fabrizio Romano Italiano",
        sources=[src],
    )
    sections = {
        "✅ Situazioni calde / scenari aperti": [item],
        "🕐 Situazioni da monitorare": [],
        "🚫 Voci ridimensionate / smentite": [],
    }
    rendered = format_mercato_report_twitter(
        date(2026, 4, 23),
        digest,
        generated_at=datetime(2026, 4, 23, 12, 59),
        section_items_enriched=sections,
    )
    assert "Verifica:" in rendered
    assert "https://www.youtube.com/watch?v=xyz&t=12" in rendered
