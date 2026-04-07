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


def _tips_match(existing: MercatoTip, new_tip: MercatoTip) -> bool:
    """True se due tip parlano dello stesso trasferimento."""
    if not _names_match(existing.player_name, new_tip.player_name):
        return False
    # Stesso video → non è corroborazione
    if existing.video_id == new_tip.video_id:
        return False
    # Almeno uno dei club deve coincidere (o entrambi None = generico)
    from_match = _names_match(existing.from_club, new_tip.from_club) or (
        existing.from_club is None and new_tip.from_club is None
    )
    to_match = _names_match(existing.to_club, new_tip.to_club) or (
        existing.to_club is None and new_tip.to_club is None
    )
    return from_match or to_match


def corroborate(index: MercatoIndex, new_tips: list[MercatoTip]) -> MercatoIndex:
    """Aggiorna l'index con le nuove tip, collegando quelle che si corroborano.

    Modifica l'index in-place e lo restituisce.
    """
    for new_tip in new_tips:
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

    # Aggiungi le nuove tip all'index
    index.tips.extend(new_tips)
    return index
