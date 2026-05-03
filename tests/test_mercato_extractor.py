from media_advisor.mercato.extractor import _sanitize_clubs_against_quote


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

