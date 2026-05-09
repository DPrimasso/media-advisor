from datetime import UTC, datetime

from media_advisor.mercato.extractor import (
    _quote_mentions_entity,
    _sanitize_clubs_against_quote,
    is_plausible_mercato_tip,
)
from media_advisor.mercato.models import MercatoTip


def test_sanitize_clubs_against_quote_drops_hallucinated_from_club() -> None:
    quote = (
        "L'Arsenal si è interessato, ma l'Arsenal sta studiando tanti centrocampisti. "
        "Il sogno di Andrea Berta si chiama Sandro Tonali, per il quale Newcastle chiede 100 milioni."
    )
    from_club, to_club = _sanitize_clubs_against_quote("Milan", "Arsenal", quote)
    assert from_club is None
    assert to_club == "Arsenal"


def test_sanitize_clubs_against_quote_keeps_both_when_grounded() -> None:
    quote = "La Juve valuta Alisson del Liverpool: trattativa aperta tra i club."
    from_club, to_club = _sanitize_clubs_against_quote("Liverpool", "Juventus", quote)
    assert from_club == "Liverpool"
    assert to_club == "Juventus"


def _tip(
    *,
    player: str,
    from_club: str | None,
    to_club: str | None,
    quote: str,
    confidence: str = "rumor",
) -> MercatoTip:
    now = datetime.now(UTC)
    return MercatoTip(
        tip_id="t1",
        video_id="v1",
        channel_id="c1",
        mentioned_at=now,
        extracted_at=now,
        player_name=player,
        from_club=from_club,
        to_club=to_club,
        transfer_type="unknown",
        confidence=confidence,  # type: ignore[arg-type]
        tip_text="sintesi",
        quote_text=quote,
    )


def test_sanitize_keeps_roma_when_quote_says_giallorossi() -> None:
    q = "Frattesi resta un pallino dei giallorossi, senza trattative con l'Inter per uno scambio."
    fc, tc = _sanitize_clubs_against_quote("Roma", "Inter", q)
    assert fc == "Roma"
    assert tc == "Inter"


def test_plausible_apprezzato_plusvalenza_without_player_in_quote() -> None:
    """Regression: prima l'ultimo branch era `return False` e scartava tutto."""
    tip = _tip(
        player="Manu Koné",
        from_club="Roma",
        to_club="Inter",
        quote=(
            "Serve una plusvalenza a Roma; il centrocampista è molto apprezzato "
            "dalla struttura dell'Inter ma non ci sono trattative."
        ),
    )
    assert is_plausible_mercato_tip(tip) is True


def test_quote_mentions_entity_accent_fold() -> None:
    assert _quote_mentions_entity("parliamo di Manu Kone e della Roma", "Manu Koné") is True


def test_plausible_giallorossi_pallino() -> None:
    tip = _tip(
        player="Frattesi",
        from_club="Inter",
        to_club="Roma",
        quote="È da tempo un pallino dei giallorossi, ma non ci sono dialoghi con l'Inter per lo scambio.",
    )
    assert is_plausible_mercato_tip(tip) is True

