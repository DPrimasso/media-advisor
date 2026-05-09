"""Normalizzazione nomi giocatori via registry + fuzzy matching.

Registry (priorità):
  1. DB blobs player_aliases → transfers  (alias manuali, alta confidenza)
  2. DB blob player_roster / file player-roster.json  (roster TM, bassa priorità)
  3. File legacy mercato/*.json
"""

import json
import re
import unicodedata
from functools import lru_cache
from pathlib import Path

from rapidfuzz import fuzz, process

from media_advisor.db.repository import MERCATO_BLOB_ALIASES, MERCATO_BLOB_TRANSFERS, fetch_mercato_blob_raw
from media_advisor.db.session import session_scope

# Soglia sotto cui il fuzzy match non viene accettato (0-100).
# 82 bilancia falsi positivi (nomi corti tipo "Musa", "Ivan") con recall.
_FUZZY_THRESHOLD = 82
# Soglia per il club-context matching: pool ristretto (~25 giocatori) rende 70 affidabile.
_CLUB_FUZZY_THRESHOLD = 70

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


def _merge_roster_dict(registry: dict[str, str], roster_data: dict) -> None:
    """Aggiunge i giocatori del roster TM al registry (bassa priorità).

    Gli alias manuali già presenti non vengono sovrascritti.
    Le surname ambigue (più giocatori con stesso cognome) vengono escluse
    dall'aggiunta come chiave isolata per evitare falsi positivi.
    """
    players = roster_data.get("players", [])
    if not players:
        return

    # Conta quante volte appare ogni cognome-slug per rilevare ambiguità
    surname_counts: dict[str, int] = {}
    for p in players:
        if not isinstance(p, dict):
            continue
        last = (p.get("last_name") or "").strip()
        if last:
            slug = _slugify(last)
            surname_counts[slug] = surname_counts.get(slug, 0) + 1

    ambiguous_surnames: frozenset[str] = frozenset(
        slug for slug, count in surname_counts.items() if count > 1
    )

    for p in players:
        if not isinstance(p, dict):
            continue
        canonical: str = (p.get("canonical_name") or "").strip()
        if not canonical:
            continue

        # Nome completo (priorità massima dentro il roster)
        full_slug = _slugify(canonical)
        if full_slug and full_slug not in registry:
            registry[full_slug] = canonical

        # Alias generati automaticamente
        for alias in p.get("aliases", []):
            alias = (alias or "").strip()
            if not alias:
                continue
            alias_slug = _slugify(alias)
            if not alias_slug or alias_slug in registry:
                continue
            # Salta cognomi ambigui come chiave isolata
            last = (p.get("last_name") or "").strip()
            if last and _slugify(last) == alias_slug and alias_slug in ambiguous_surnames:
                continue
            registry[alias_slug] = canonical


@lru_cache(maxsize=16)
def load_player_registry(root: Path) -> dict[str, str]:
    """Carica alias + transfer confermati da DB, poi roster TM, poi file legacy se serve."""
    registry: dict[str, str] = {}
    root = root.resolve()

    with session_scope(root, read_only=True) as session:
        aliases_raw = fetch_mercato_blob_raw(session, MERCATO_BLOB_ALIASES)
        transfers_raw = fetch_mercato_blob_raw(session, MERCATO_BLOB_TRANSFERS)
        from media_advisor.mercato.roster_fetcher import MERCATO_BLOB_ROSTER
        roster_raw = fetch_mercato_blob_raw(session, MERCATO_BLOB_ROSTER)

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

    # Roster TM (bassa priorità: aggiunge solo slug non ancora presenti)
    roster_loaded = False
    if roster_raw:
        try:
            rdata = json.loads(roster_raw)
            if isinstance(rdata, dict):
                _merge_roster_dict(registry, rdata)
                roster_loaded = True
        except json.JSONDecodeError:
            pass

    if not roster_loaded:
        roster_file = mercato_dir / "player-roster.json"
        if roster_file.exists():
            try:
                rdata = json.loads(roster_file.read_text(encoding="utf-8"))
                if isinstance(rdata, dict):
                    _merge_roster_dict(registry, rdata)
            except (json.JSONDecodeError, OSError):
                pass

    return registry


def _canonical_names(registry: dict[str, str]) -> list[str]:
    return sorted(set(registry.values()))


def _ascii_slug(s: str) -> str:
    """Slug ASCII senza diacritici, per confronto nomi di club."""
    normalized = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", "", normalized.lower().strip()))


@lru_cache(maxsize=4)
def _club_roster_index(root: Path) -> dict[str, list[str]]:
    """Indice {club_slug → [canonical_name, alias, ...]} per il club-context matching.

    Caricato una volta sola e cachato per performance.
    """
    from media_advisor.mercato.roster_fetcher import load_player_roster

    roster = load_player_roster(root)
    if not roster:
        return {}

    index: dict[str, list[str]] = {}
    for player in roster.players:
        club_slug = _ascii_slug(player.club)
        names = [player.canonical_name] + player.aliases
        index.setdefault(club_slug, []).extend(names)
    return index


def normalize_player_name_with_club_hint(
    raw: str,
    root: Path,
    hint_clubs: list[str | None],
) -> str:
    """Normalizzazione con contesto squadra: soglia fuzzy abbassata a 70.

    Usata solo quando la normalizzazione standard fallisce e il LLM ha già
    estratto from_club/to_club. Con 20-30 candidati per club la soglia 70
    è affidabile quanto 82 sul pool globale.
    """
    if not raw or not raw.strip():
        return raw

    club_index = _club_roster_index(root)
    if not club_index:
        return raw

    for hint in hint_clubs:
        if not hint:
            continue
        hint_slug = _ascii_slug(hint)
        # Cerca il cluster di club più simile (gestisce varianti "Man United" vs "Manchester United")
        candidates_names: list[str] = []
        for cslug, names in club_index.items():
            if hint_slug in cslug or cslug in hint_slug:
                candidates_names.extend(names)

        if not candidates_names:
            continue

        result = process.extractOne(
            raw,
            candidates_names,
            scorer=fuzz.token_sort_ratio,
            score_cutoff=_CLUB_FUZZY_THRESHOLD,
        )
        if result is not None:
            return result[0]

    return raw


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
    """Lista compatta dei nomi canonici per il prompt LLM.

    Cap a 500 nomi per non gonfiare il context del modello.
    Priorità: alias manuali + Serie A + altre leghe.
    """
    _MAX_NAMES = 500

    # Nomi dal registry manuale (alias + transfers) — sempre inclusi
    manual_registry: dict[str, str] = {}
    root_resolved = root.resolve()
    mercato_dir = root_resolved / "mercato"

    with session_scope(root_resolved, read_only=True) as session:
        aliases_raw = fetch_mercato_blob_raw(session, MERCATO_BLOB_ALIASES)
        transfers_raw = fetch_mercato_blob_raw(session, MERCATO_BLOB_TRANSFERS)
    if aliases_raw:
        try:
            data = json.loads(aliases_raw)
            if isinstance(data, dict):
                _merge_aliases_dict(manual_registry, data)
        except json.JSONDecodeError:
            pass
    if transfers_raw:
        try:
            tdata = json.loads(transfers_raw)
            if isinstance(tdata, dict):
                _merge_transfers_dict(manual_registry, tdata)
        except json.JSONDecodeError:
            pass
    for fpath, merge_fn in [
        (mercato_dir / "player-aliases.json", _merge_aliases_dict),
        (mercato_dir / "transfers.json", _merge_transfers_dict),
    ]:
        if fpath.exists():
            try:
                d = json.loads(fpath.read_text(encoding="utf-8"))
                if isinstance(d, dict):
                    merge_fn(manual_registry, d)  # type: ignore[arg-type]
            except (json.JSONDecodeError, OSError):
                pass

    seen: set[str] = set()
    result: list[str] = []

    for name in sorted(set(manual_registry.values())):
        if name not in seen:
            seen.add(name)
            result.append(name)

    # Aggiungi giocatori dal roster TM se presente, priorità IT1
    try:
        from media_advisor.mercato.roster_fetcher import load_player_roster

        roster = load_player_roster(root_resolved)
        if roster:
            it1 = [p.canonical_name for p in roster.players if p.league == "IT1"]
            others = [p.canonical_name for p in roster.players if p.league != "IT1"]
            for name in it1 + others:
                if name not in seen:
                    seen.add(name)
                    result.append(name)
                    if len(result) >= _MAX_NAMES:
                        break
    except Exception:
        pass

    return ", ".join(sorted(result[:_MAX_NAMES]))
