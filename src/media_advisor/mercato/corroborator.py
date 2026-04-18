"""Corroborazione semi-automatica delle tip di mercato.

Dopo ogni estrazione, cerca tip esistenti che parlano dello stesso giocatore
verso lo stesso club. Se trova match, aggiorna corroborated_by e
corroboration_score nell'index globale.
"""

import re

from media_advisor.mercato.models import MercatoIndex, MercatoTip

# Minimum substring length for fuzzy name matching.
# Avoids false positives from very short common tokens ("de", "da", "el").
_MIN_OVERLAP = 3

# Numero massimo di giorni tra due tip per considerarle della stessa sessione.
_MAX_SESSION_GAP_DAYS = 210  # ~7 mesi


def _slug(name: str) -> str:
    """Normalizza stringa per confronto: lowercase, no spazi/punteggiatura."""
    return re.sub(r"[^a-z0-9]", "", name.lower().strip())


def _names_match(a: str | None, b: str | None) -> bool:
    """True se i due nomi sono abbastanza simili da riferirsi alla stessa entità."""
    if not a or not b:
        return False
    sa, sb = _slug(a), _slug(b)
    if sa == sb:
        return True
    # Substring match per nomi parziali (es. "Lukaku" vs "Romelu Lukaku")
    if len(sa) >= _MIN_OVERLAP and (sa in sb or sb in sa):
        return True
    return False


def _is_renewal_tip(tip: MercatoTip) -> bool:
    """True se la tip indica una permanenza/rinnovo (il giocatore rimane al club attuale)."""
    if tip.transfer_type in {"extension", "renewal"}:
        return True
    # to_club == from_club = il giocatore "si trasferisce" allo stesso club → rinnovo
    if tip.to_club and tip.from_club and _slug(tip.to_club) == _slug(tip.from_club):
        return True
    return False


def _same_session(a: MercatoTip, b: MercatoTip) -> bool:
    """True se le due tip sono nella stessa finestra di mercato (o una delle due non ha data)."""
    if a.mentioned_at is None or b.mentioned_at is None:
        return True  # senza data non possiamo escluderle
    delta = abs((a.mentioned_at - b.mentioned_at).days)
    return delta <= _MAX_SESSION_GAP_DAYS


def _tips_match(existing: MercatoTip, new_tip: MercatoTip) -> bool:
    """True se due tip parlano dello stesso trasferimento e possono corroborarsi."""
    if not _names_match(existing.player_name, new_tip.player_name):
        return False
    # Stesso video → non è corroborazione
    if existing.video_id == new_tip.video_id:
        return False
    # Sessioni di mercato diverse: non confrontabili
    if not _same_session(existing, new_tip):
        return False
    # Rinnovo vs trasferimento: non si corroborano
    if _is_renewal_tip(existing) != _is_renewal_tip(new_tip):
        return False
    # Se entrambe le tip hanno un to_club, devono coincidere
    if existing.to_club and new_tip.to_club:
        return _names_match(existing.to_club, new_tip.to_club)
    # Almeno una tip senza to_club: confronto sul from_club come fallback
    return _names_match(existing.from_club, new_tip.from_club)


def corroborate(index: MercatoIndex, new_tips: list[MercatoTip]) -> MercatoIndex:
    """Aggiorna l'index con le nuove tip, collegando quelle che si corroborano.

    Modifica l'index in-place e lo restituisce.
    """
    existing_ids = {t.tip_id for t in index.tips}
    truly_new = [t for t in new_tips if t.tip_id not in existing_ids]

    for new_tip in truly_new:
        for existing in index.tips:
            if _tips_match(existing, new_tip):
                # Aggiungi nuovo video a corroborated_by dell'esistente
                if new_tip.video_id not in existing.corroborated_by:
                    existing.corroborated_by.append(new_tip.video_id)
                    existing.corroboration_score = min(
                        1.0, len(existing.corroborated_by) / 5
                    )
                # Collega anche la nuova tip all'esistente
                if existing.video_id not in new_tip.corroborated_by:
                    new_tip.corroborated_by.append(existing.video_id)
                    new_tip.corroboration_score = min(
                        1.0, len(new_tip.corroborated_by) / 5
                    )

    # Aggiungi le nuove tip all'index (solo quelle non già presenti)
    index.tips.extend(truly_new)
    return index
