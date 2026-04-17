"""Normalizzazione nomi giocatori via registry + fuzzy matching.

Flusso di normalizzazione per ogni nome estratto dal LLM:
  1. Exact match (case-insensitive) nel registry
  2. Surname-only match (ultimo token del nome)
  3. rapidfuzz token_sort_ratio contro tutti i nomi canonici (threshold 82)

Registry costruito da (in ordine di priorità):
  - mercato/player-aliases.json  → alias slug → canonical name
  - mercato/transfers.json       → player_name dei transfer confermati
"""

import json
import re
from functools import lru_cache
from pathlib import Path

from rapidfuzz import fuzz, process

# Soglia sotto cui il fuzzy match non viene accettato (0-100).
# 82 bilancia falsi positivi (nomi corti tipo "Musa", "Ivan") con recall.
_FUZZY_THRESHOLD = 82

# Nomi troppo corti o ambigui: rispecchia la sezione "noise" di player-aliases.json.
# Il fuzzy matching è disabilitato per questi anche se non entrano nel registry.
_SKIP_FUZZY: frozenset[str] = frozenset({"musa", "ivan", "kevin", "somo"})


def _slugify(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", "", s.lower().strip()))


def _flatten_aliases(data: dict[str, object]) -> dict[str, str | None]:
    """Appiattisce {sezione: {slug: canonical}} in {slug: canonical}.

    Prima occorrenza di uno slug vince; chiavi "_*" sono metadati ignorati.
    """
    result: dict[str, str | None] = {}
    for key, value in data.items():
        if key.startswith("_"):
            continue
        if isinstance(value, dict):
            for nested_slug, nested_canonical in _flatten_aliases(value).items():
                if nested_slug not in result:
                    result[nested_slug] = nested_canonical
        elif isinstance(value, str) or value is None:
            result[key] = value
    return result


@lru_cache(maxsize=2)
def load_player_registry(mercato_dir: Path) -> dict[str, str]:
    """Carica alias + transfer confermati. Priorità: player-aliases.json > transfers.json."""
    registry: dict[str, str] = {}

    # 1. player-aliases.json — sorgente curata, supporta formato piatto e annidato
    aliases_file = mercato_dir / "player-aliases.json"
    if aliases_file.exists():
        try:
            raw: dict[str, object] = json.loads(aliases_file.read_text(encoding="utf-8"))
            flat = _flatten_aliases(raw)
            for slug, canonical in flat.items():
                if not canonical:
                    continue
                key = _slugify(slug.replace("-", " "))
                if key and key not in registry:
                    registry[key] = canonical
                # Self-mapping: il LLM a volte restituisce il nome canonico direttamente
                ck = _slugify(canonical)
                if ck and ck not in registry:
                    registry[ck] = canonical
        except (json.JSONDecodeError, OSError):
            pass

    # 2. transfers.json — nomi canonici da transfer confermati
    transfers_file = mercato_dir / "transfers.json"
    if transfers_file.exists():
        try:
            tdata = json.loads(transfers_file.read_text(encoding="utf-8"))
            for t in tdata.get("transfers", []):
                name: str = (t.get("player_name") or "").strip()
                if not name:
                    continue
                key = _slugify(name)
                if key and key not in registry:
                    registry[key] = name
        except (json.JSONDecodeError, OSError):
            pass

    return registry


def _canonical_names(registry: dict[str, str]) -> list[str]:
    return sorted(set(registry.values()))


def normalize_player_name(raw: str, mercato_dir: Path) -> str:
    """Normalizza un nome giocatore estratto dal transcript/LLM.

    Prova in sequenza:
    1. Exact match nel registry (case-insensitive)
    2. Match sul cognome (ultimo token)
    3. Fuzzy match contro nomi canonici (threshold _FUZZY_THRESHOLD)

    Restituisce il nome originale se nessun match supera la soglia.
    """
    if not raw or not raw.strip():
        return raw

    name = raw.strip()
    registry = load_player_registry(mercato_dir)

    # 1. Exact match
    key = _slugify(name)
    if key in registry:
        return registry[key]

    # 2. Surname-only match (es. "Tomori" → "Fikayo Tomori")
    tokens = [t for t in name.split() if len(t) >= 3]
    if tokens:
        surname_key = _slugify(tokens[-1])
        if surname_key in registry:
            return registry[surname_key]

    # 3. Fuzzy match — salta nomi troppo corti o notoriamente ambigui
    if key in _SKIP_FUZZY or len(name) < 4:
        return name

    canonicals = _canonical_names(registry)
    if not canonicals:
        return name

    result = process.extractOne(
        name,
        canonicals,
        scorer=fuzz.token_sort_ratio,
        score_cutoff=_FUZZY_THRESHOLD,
    )
    if result is not None:
        matched_name: str = result[0]
        return matched_name

    return name


def get_player_list_for_prompt(mercato_dir: Path) -> str:
    """Lista compatta dei nomi canonici per il prompt LLM.

    Formato: "Alessandro Bastoni, Adrien Rabiot, Fikayo Tomori, ..."
    """
    registry = load_player_registry(mercato_dir)
    return ", ".join(_canonical_names(registry))
