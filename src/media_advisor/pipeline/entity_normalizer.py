"""Step 4 — Entity normalization.

Alias → canonical_name.
Porting of src/pipeline/entity-normalizer.ts.
"""

import re

ALIASES: dict[str, str] = {
    "inter": "Inter",
    "internazionale": "Inter",
    "nerazzurri": "Inter",
    "inter milan": "Inter",
    "napoli": "Napoli",
    "azzurri": "Napoli",
    "ssc napoli": "Napoli",
    "juve": "Juventus",
    "juventus": "Juventus",
    "la juve": "Juventus",
    "bianconeri": "Juventus",
    "milan": "Milan",
    "ac milan": "Milan",
    "rossoneri": "Milan",
    "lazio": "Lazio",
    "roma": "Roma",
    "as roma": "Roma",
    "giallorossi": "Roma",
    "atalanta": "Atalanta",
    "adl": "De Laurentiis",
    "de laurentiis": "De Laurentiis",
    "aurelio": "De Laurentiis",
    "conte": "Conte",
    "antonio conte": "Conte",
    "kvara": "Kvaratskhelia",
    "kvaratskhelia": "Kvaratskhelia",
    "lautaro": "Lautaro Martinez",
    "lautaro martinez": "Lautaro Martinez",
    "mctominay": "McTominay",
    "mctomini": "McTominay",
    "scott mctominay": "McTominay",
    "neres": "Neres",
    "var": "VAR",
    "arbitri": "Arbitri",
    "giovanile napoli": "Napoli",
}

_NON_WORD = re.compile(r"[^\w\s]")


def _normalize_key(s: str) -> str:
    return _NON_WORD.sub("", s.lower().strip())


def normalize_entity(raw: str) -> str:
    if not raw or not raw.strip():
        return ""
    key = _normalize_key(raw)
    return ALIASES.get(key, raw.strip())
