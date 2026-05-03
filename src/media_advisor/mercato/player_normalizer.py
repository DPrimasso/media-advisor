"""Normalizzazione nomi giocatori via registry + fuzzy matching.

Registry (priorità): DB blobs player_aliases → transfers; poi file legacy mercato/*.json.
"""

import json
import re
from functools import lru_cache
from pathlib import Path

from rapidfuzz import fuzz, process

from media_advisor.db.repository import MERCATO_BLOB_ALIASES, MERCATO_BLOB_TRANSFERS, fetch_mercato_blob_raw
from media_advisor.db.session import session_scope

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


def _merge_aliases_dict(registry: dict[str, str], raw: dict[str, object]) -> None:
    flat = _flatten_aliases(raw)
    for slug, canonical in flat.items():
        if not canonical:
            continue
        key = _slugify(slug.replace("-", " "))
        if key and key not in registry:
            registry[key] = canonical
        ck = _slugify(canonical)
        if ck and ck not in registry:
            registry[ck] = canonical


def _merge_transfers_dict(registry: dict[str, str], tdata: dict) -> None:
    for t in tdata.get("transfers", []):
        if not isinstance(t, dict):
            continue
        name: str = (t.get("player_name") or "").strip()
        if not name:
            continue
        key = _slugify(name)
        if key and key not in registry:
            registry[key] = name


@lru_cache(maxsize=16)
def load_player_registry(root: Path) -> dict[str, str]:
    """Carica alias + transfer confermati da DB, poi da file legacy se serve."""
    registry: dict[str, str] = {}
    root = root.resolve()

    with session_scope(root, read_only=True) as session:
        aliases_raw = fetch_mercato_blob_raw(session, MERCATO_BLOB_ALIASES)
        transfers_raw = fetch_mercato_blob_raw(session, MERCATO_BLOB_TRANSFERS)
    if aliases_raw:
        try:
            data = json.loads(aliases_raw)
            if isinstance(data, dict):
                _merge_aliases_dict(registry, data)
        except json.JSONDecodeError:
            pass
    if transfers_raw:
        try:
            tdata = json.loads(transfers_raw)
            if isinstance(tdata, dict):
                _merge_transfers_dict(registry, tdata)
        except json.JSONDecodeError:
            pass

    mercato_dir = root / "mercato"
    aliases_file = mercato_dir / "player-aliases.json"
    if aliases_file.exists():
        try:
            raw: dict[str, object] = json.loads(aliases_file.read_text(encoding="utf-8"))
            _merge_aliases_dict(registry, raw)
        except (json.JSONDecodeError, OSError):
            pass

    transfers_file = mercato_dir / "transfers.json"
    if transfers_file.exists():
        try:
            tdata = json.loads(transfers_file.read_text(encoding="utf-8"))
            if isinstance(tdata, dict):
                _merge_transfers_dict(registry, tdata)
        except (json.JSONDecodeError, OSError):
            pass

    return registry


def _canonical_names(registry: dict[str, str]) -> list[str]:
    return sorted(set(registry.values()))


def normalize_player_name(raw: str, root: Path) -> str:
    """Normalizza un nome giocatore estratto dal transcript/LLM."""
    if not raw or not raw.strip():
        return raw

    name = raw.strip()
    registry = load_player_registry(root)

    key = _slugify(name)
    if key in registry:
        return registry[key]

    tokens = [t for t in name.split() if len(t) >= 3]
    if tokens:
        surname_key = _slugify(tokens[-1])
        if surname_key in registry:
            return registry[surname_key]

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


def get_player_list_for_prompt(root: Path) -> str:
    """Lista compatta dei nomi canonici per il prompt LLM."""
    registry = load_player_registry(root)
    return ", ".join(_canonical_names(registry))
