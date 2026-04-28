from media_advisor.digest import (
    _is_valid_digest_output,
    _repair_smentita_section,
    _normalize_digest_output,
    _validate_digest_output,
)


VALID_DIGEST = """✅ Situazioni calde / scenari aperti
Lautaro Martinez (Inter) - Movimento: rinnovo vicino; Stato: caldo; Motivo: accordo economico avanzato; Fonte: Fabrizio Romano
Joshua Zirkzee (Bologna) - Movimento: contatti con big italiana; Stato: caldo; Motivo: priorita tecnica confermata; Fonte: Sky Sport

🕐 Situazioni da monitorare
Alessandro Buongiorno (Torino) - Movimento: sondaggio estero; Stato: monitorare; Motivo: trattativa in fase iniziale; Fonte: Gianluca Di Marzio

🚫 Voci ridimensionate / smentite
Victor Osimhen (Napoli) - Movimento: scambio con top club; Stato: smentita; Motivo: club nega apertura; Fonte: Corriere dello Sport
"""


def test_validate_digest_output_accepts_valid_digest() -> None:
    assert _validate_digest_output(VALID_DIGEST) == []
    assert _is_valid_digest_output(VALID_DIGEST) is True


def test_validate_digest_output_accepts_headers_without_emoji_prefix() -> None:
    digest = """Situazioni calde / scenari aperti
Lautaro Martinez (Inter) - Movimento: rinnovo vicino; Stato: caldo; Motivo: accordo economico avanzato; Fonte: Fabrizio Romano

Situazioni da monitorare
Alessandro Buongiorno (Torino) - Movimento: sondaggio estero; Stato: monitorare; Motivo: trattativa in fase iniziale; Fonte: Gianluca Di Marzio

Voci ridimensionate / smentite
Victor Osimhen (Napoli) - Movimento: scambio con top club; Stato: smentita; Motivo: club nega apertura; Fonte: Corriere dello Sport
"""
    assert _validate_digest_output(digest) == []
    assert _is_valid_digest_output(digest) is True


def test_validate_digest_output_rejects_wrong_section_order() -> None:
    digest = """🕐 Situazioni da monitorare
Alessandro Buongiorno (Torino) - Movimento: sondaggio estero; Stato: monitorare; Motivo: trattativa in fase iniziale; Fonte: Gianluca Di Marzio

✅ Situazioni calde / scenari aperti
Lautaro Martinez (Inter) - Movimento: rinnovo vicino; Stato: caldo; Motivo: accordo economico avanzato; Fonte: Fabrizio Romano

🚫 Voci ridimensionate / smentite
Victor Osimhen (Napoli) - Movimento: scambio con top club; Stato: smentita; Motivo: club nega apertura; Fonte: Corriere dello Sport
"""
    errors = _validate_digest_output(digest)
    assert any("Ordine sezioni non valido." in err for err in errors)


def test_validate_digest_output_rejects_text_outside_section() -> None:
    digest = """Intro non consentita
✅ Situazioni calde / scenari aperti
Lautaro Martinez (Inter) - Movimento: rinnovo vicino; Stato: caldo; Motivo: accordo economico avanzato; Fonte: Fabrizio Romano

🕐 Situazioni da monitorare
Alessandro Buongiorno (Torino) - Movimento: sondaggio estero; Stato: monitorare; Motivo: trattativa in fase iniziale; Fonte: Gianluca Di Marzio

🚫 Voci ridimensionate / smentite
Victor Osimhen (Napoli) - Movimento: scambio con top club; Stato: smentita; Motivo: club nega apertura; Fonte: Corriere dello Sport
"""
    errors = _validate_digest_output(digest)
    assert any("Testo fuori sezione" in err for err in errors)


def test_validate_digest_output_rejects_invalid_item_format() -> None:
    digest = """✅ Situazioni calde / scenari aperti
Lautaro Martinez Inter - Movimento: rinnovo vicino; Stato: caldo; Motivo: accordo economico avanzato; Fonte: Fabrizio Romano

🕐 Situazioni da monitorare
Alessandro Buongiorno (Torino) - Movimento: sondaggio estero; Stato: monitorare; Motivo: trattativa in fase iniziale; Fonte: Gianluca Di Marzio

🚫 Voci ridimensionate / smentite
Victor Osimhen (Napoli) - Movimento: scambio con top club; Stato: smentita; Motivo: club nega apertura; Fonte: Corriere dello Sport
"""
    errors = _validate_digest_output(digest)
    assert any("Formato riga non valido" in err for err in errors)


def test_validate_digest_output_rejects_state_section_mismatch() -> None:
    digest = """✅ Situazioni calde / scenari aperti
Lautaro Martinez (Inter) - Movimento: rinnovo vicino; Stato: monitorare; Motivo: accordo economico avanzato; Fonte: Fabrizio Romano

🕐 Situazioni da monitorare
Alessandro Buongiorno (Torino) - Movimento: sondaggio estero; Stato: monitorare; Motivo: trattativa in fase iniziale; Fonte: Gianluca Di Marzio

🚫 Voci ridimensionate / smentite
Victor Osimhen (Napoli) - Movimento: scambio con top club; Stato: smentita; Motivo: club nega apertura; Fonte: Corriere dello Sport
"""
    errors = _validate_digest_output(digest)
    assert any("non coerente con sezione" in err for err in errors)


def test_validate_digest_output_rejects_empty_section() -> None:
    digest = """✅ Situazioni calde / scenari aperti
Lautaro Martinez (Inter) - Movimento: rinnovo vicino; Stato: caldo; Motivo: accordo economico avanzato; Fonte: Fabrizio Romano

🕐 Situazioni da monitorare

🚫 Voci ridimensionate / smentite
Victor Osimhen (Napoli) - Movimento: scambio con top club; Stato: smentita; Motivo: club nega apertura; Fonte: Corriere dello Sport
"""
    errors = _validate_digest_output(digest)
    assert any("Sezione vuota" in err for err in errors)
    assert _is_valid_digest_output(digest) is False


def test_validate_digest_output_allows_empty_smentita_when_no_denied_tips() -> None:
    digest = """✅ Situazioni calde / scenari aperti
Lautaro Martinez (Inter) - Movimento: rinnovo vicino; Stato: caldo; Motivo: accordo economico avanzato; Fonte: Fabrizio Romano

🕐 Situazioni da monitorare
Alessandro Buongiorno (Torino) - Movimento: sondaggio estero; Stato: monitorare; Motivo: trattativa in fase iniziale; Fonte: Gianluca Di Marzio

🚫 Voci ridimensionate / smentite
"""
    assert _validate_digest_output(digest, allow_empty_smentita_section=True) == []
    assert _is_valid_digest_output(digest, allow_empty_smentita_section=True) is True
    assert any("Sezione vuota" in e for e in _validate_digest_output(digest))


def test_validate_digest_output_rejects_same_story_across_states() -> None:
    digest = """✅ Situazioni calde / scenari aperti
Alisson (Liverpool) - Movimento: possibile addio; Stato: caldo; Motivo: pista italiana aperta; Fonte: Fabrizio Romano

🕐 Situazioni da monitorare
Ederson (Atalanta) - Movimento: sondaggio; Stato: monitorare; Motivo: interesse non confermato; Fonte: Nicolò Schira

🚫 Voci ridimensionate / smentite
Ederson (Atalanta) - Movimento: sondaggio; Stato: smentita; Motivo: nessun contatto concreto; Fonte: Nicolò Schira
"""
    errors = _validate_digest_output(digest)
    assert any("Notizia duplicata in stati diversi" in err for err in errors)


def test_normalize_digest_output_merges_cross_state_duplicates() -> None:
    digest = """✅ Situazioni calde / scenari aperti
Alisson (Liverpool) - Movimento: possibile addio; Stato: caldo; Motivo: pista italiana aperta; Fonte: Fabrizio Romano

🕐 Situazioni da monitorare
Ederson (Atalanta) - Movimento: sondaggio; Stato: monitorare; Motivo: interesse non confermato; Fonte: Nicolò Schira

🚫 Voci ridimensionate / smentite
Ederson (Atalanta) - Movimento: sondaggio; Stato: smentita; Motivo: nessun contatto concreto; Fonte: Fabrizio Romano Italiano
"""
    normalized = _normalize_digest_output(digest)
    assert "Stato: monitorare; Motivo: interesse non confermato; Fonte: Nicolò Schira" not in normalized
    assert "Stato: smentita; Motivo: nessun contatto concreto; Fonte: Nicolò Schira, Fabrizio Romano Italiano" in normalized


def test_repair_smentita_section_replaces_placeholder_with_fallback() -> None:
    digest = """✅ Situazioni calde / scenari aperti
Lautaro Martinez (Inter) - Movimento: rinnovo vicino; Stato: caldo; Motivo: accordo economico avanzato; Fonte: Fabrizio Romano

🕐 Situazioni da monitorare
Alessandro Buongiorno (Torino) - Movimento: sondaggio estero; Stato: monitorare; Motivo: trattativa in fase iniziale; Fonte: Gianluca Di Marzio

🚫 Voci ridimensionate / smentite
Nessuna voce smentita nel report odierno.
"""
    fallback = [
        "Victor Osimhen (Napoli) - Movimento: permanenza probabile; Stato: smentita; Motivo: voce ridimensionata dalla fonte; Fonte: Corriere dello Sport"
    ]
    repaired = _repair_smentita_section(digest, fallback)
    assert "Nessuna voce smentita nel report odierno." not in repaired
    assert fallback[0] in repaired
    assert _validate_digest_output(repaired) == []
