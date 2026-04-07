"""Verifica automatica delle tip di mercato contro i trasferimenti ufficiali.

Logica di matching:
- stesso player_slug
- to_club match + transfer_type match  → "confermata"
- to_club match + transfer_type diverso → "parziale"  (es. prestito vs permanente)
- giocatore trovato nei trasferimenti ma to_club diverso → "smentita"
- nessun trasferimento trovato per il giocatore → None (rimane non_verificata)
"""

import re
from datetime import datetime, timezone
from pathlib import Path

from media_advisor.mercato.models import MercatoTip, OutcomeValue
from media_advisor.mercato.transfer_db import TransferRecord, get_all_transfers, player_slug


def _slug_compact(name: str) -> str:
    """Slug compatto senza trattini, usato per fuzzy matching di nomi club."""
    return re.sub(r"[^a-z0-9]", "", name.lower())


def _clubs_match(a: str | None, b: str | None) -> bool:
    if not a or not b:
        return False
    sa, sb = _slug_compact(a), _slug_compact(b)
    return sa == sb or (len(sa) >= 3 and (sa in sb or sb in sa))


def verify_tip(
    tip: MercatoTip,
    transfers: list[TransferRecord],
) -> tuple[OutcomeValue | None, str | None]:
    """Confronta una tip con i trasferimenti ufficiali disponibili.

    Ritorna (outcome, notes) se c'è un match, altrimenti (None, None).
    """
    tip_slug = player_slug(tip.player_name)
    player_transfers = [t for t in transfers if t.player_slug == tip_slug]

    if not player_transfers:
        return None, None  # nessun dato ufficiale sul giocatore

    # Il giocatore ha almeno un trasferimento ufficiale → possiamo verificare
    for tr in player_transfers:
        if _clubs_match(tip.to_club, tr.to_club):
            # Stesso club di destinazione
            if tip.transfer_type == tr.transfer_type or tip.transfer_type == "unknown":
                return "confermata", f"Trasferimento ufficiale: {tr.player_name} → {tr.to_club} ({tr.transfer_type})"
            else:
                return "parziale", (
                    f"Trasferimento avvenuto ma tipo diverso: "
                    f"previsto {tip.transfer_type}, reale {tr.transfer_type} "
                    f"({tr.player_name} → {tr.to_club})"
                )

    # Il giocatore si è trasferito ma in un club diverso da quello della tip
    real_clubs = ", ".join(f"{t.to_club}" for t in player_transfers if t.to_club)
    return "smentita", f"Il giocatore si è trasferito a: {real_clubs}"


def verify_all_pending(root: Path) -> list[dict]:
    """Verifica tutte le tip non_verificata contro il database trasferimenti.

    Aggiorna l'index globale e ritorna la lista delle tip aggiornate
    con i campi modificati.
    """
    from media_advisor.io.json_io import write_json
    from media_advisor.io.paths import mercato_index_path
    from media_advisor.mercato.aggregator import load_index

    transfers = get_all_transfers(root)
    if not transfers:
        return []

    index = load_index(root)
    updated: list[dict] = []

    for tip in index.tips:
        if tip.outcome != "non_verificata":
            continue

        outcome, notes = verify_tip(tip, transfers)
        if outcome is None:
            continue

        tip.outcome = outcome
        tip.outcome_notes = notes
        tip.outcome_updated_at = datetime.now(timezone.utc)
        tip.outcome_source = "transfermarkt"

        updated.append({
            "tip_id": tip.tip_id,
            "player_name": tip.player_name,
            "to_club": tip.to_club,
            "outcome": outcome,
            "notes": notes,
        })

    if updated:
        index.updated_at = datetime.now(timezone.utc)
        write_json(mercato_index_path(root), index.model_dump(mode="json"))

    return updated


def verify_single_tip(root: Path, tip_id: str) -> dict | None:
    """Verifica una singola tip per tip_id. Ritorna il risultato o None se non trovata."""
    from media_advisor.io.json_io import write_json
    from media_advisor.io.paths import mercato_index_path
    from media_advisor.mercato.aggregator import load_index

    transfers = get_all_transfers(root)
    index = load_index(root)

    tip = next((t for t in index.tips if t.tip_id == tip_id), None)
    if tip is None:
        return None

    outcome, notes = verify_tip(tip, transfers)
    if outcome is None:
        return {"tip_id": tip_id, "outcome": tip.outcome, "changed": False, "notes": "Nessun trasferimento ufficiale trovato per questo giocatore"}

    tip.outcome = outcome
    tip.outcome_notes = notes
    tip.outcome_updated_at = datetime.now(timezone.utc)
    tip.outcome_source = "transfermarkt"

    index.updated_at = datetime.now(timezone.utc)
    write_json(mercato_index_path(root), index.model_dump(mode="json"))

    return {
        "tip_id": tip_id,
        "player_name": tip.player_name,
        "to_club": tip.to_club,
        "outcome": outcome,
        "notes": notes,
        "changed": True,
    }
