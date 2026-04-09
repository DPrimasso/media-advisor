"""Scraping per recuperare trasferimenti ufficiali.

Fonti dati (in ordine di priorità):
  1. Transfermarkt — ceapi/transferHistory/list/{tm_id}
  2. Sofascore     — api.sofascore.com/api/v1/player/{ss_id}/transfer-history

Se TM è irraggiungibile (Cloudflare block), usa automaticamente Sofascore.

Ricerca giocatori:
  1. Cache locale mercato/player-tm-ids.json (player_slug → {tm_id, ss_id})
  2. TM HTML search (cold fresh request)
  3. Sofascore search API (fallback)
"""

import json
import logging
import re
import time
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

_TM_BASE = "https://www.transfermarkt.it"
_SS_API = "https://api.sofascore.com/api/v1"

_TM_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "it-IT,it;q=0.9,en;q=0.8",
    "x-requested-with": "XMLHttpRequest",
    "Referer": _TM_BASE + "/",
}

_SS_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "*/*",
    "Accept-Language": "it-IT,it;q=0.9",
    "Referer": "https://www.sofascore.com/",
}

_PRESTITO_RE = re.compile(r"prestito|loan|spesa\s+prestito", re.IGNORECASE)
_FREE_RE = re.compile(r"svincol|free\s+agent|fine\s+prestito|svincolato", re.IGNORECASE)
_RINNOVO_RE = re.compile(r"rinnov|prolungamento|extension", re.IGNORECASE)

_PLAYER_LINK_RE = re.compile(
    r'href="/([^/"]+)/profil/spieler/(\d+)"[^>]*>\s*([^<\n]{2,60}?)\s*</a>'
)

# Sofascore transfer types (verificati empiricamente):
#   1 = rientro da prestito (loan return) → "loan"
#   2 = prestito (loan) → "loan"
#   3 = trasferimento con fee → inferisce dal fee: >0 → permanent, 0 → free_agent
_SS_LOAN_TYPES = {1, 2}


class ScraperError(Exception):
    pass


# ---------------------------------------------------------------------------
# TM session helpers
# ---------------------------------------------------------------------------

_session: object = None


def _make_session():
    try:
        from curl_cffi import requests as cffi_requests
        session = cffi_requests.Session()
        session.get(_TM_BASE + "/", headers={**_TM_HEADERS, "Accept": "text/html"}, impersonate="chrome124", timeout=15)
        return session
    except ImportError:
        raise ScraperError("curl_cffi non installato. Esegui: python -m pip install curl_cffi")


def _get_session():
    global _session
    if _session is None:
        _session = _make_session()
    return _session


def _reset_session():
    global _session
    _session = None


def _tm_available() -> bool:
    """Verifica se TM risponde (homepage non bloccata)."""
    try:
        from curl_cffi import requests as cffi_requests
        html_h = {k: v for k, v in _TM_HEADERS.items() if k.lower() != "x-requested-with"}
        html_h["Accept"] = "text/html"
        r = cffi_requests.get(_TM_BASE + "/", headers=html_h, impersonate="chrome124", timeout=10)
        return r.status_code == 200 and "Human Verification" not in r.text[:500]
    except Exception:
        return False


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------


def _get_json_tm(url: str, referer: str | None = None) -> dict:
    from curl_cffi import requests as cffi_requests
    headers = {**_TM_HEADERS}
    if referer:
        headers["Referer"] = referer
    session = _get_session()
    resp = session.get(url, headers=headers, impersonate="chrome124", timeout=15)
    if resp.status_code != 200:
        raise ScraperError(f"HTTP {resp.status_code} per {url}")
    return resp.json()


def _get_json_ss(path: str) -> dict:
    """GET su api.sofascore.com."""
    from curl_cffi import requests as cffi_requests
    url = f"{_SS_API}/{path.lstrip('/')}"
    resp = cffi_requests.get(url, headers=_SS_HEADERS, impersonate="chrome124", timeout=15)
    if resp.status_code != 200:
        raise ScraperError(f"Sofascore HTTP {resp.status_code} per {url}")
    return resp.json()


def _get_html_tm(url: str) -> str:
    """GET HTML da TM senza sessione (cold request)."""
    from curl_cffi import requests as cffi_requests
    headers = {k: v for k, v in _TM_HEADERS.items() if k.lower() != "x-requested-with"}
    headers["Accept"] = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
    resp = cffi_requests.get(url, headers=headers, impersonate="chrome124", timeout=15)
    if resp.status_code != 200:
        raise ScraperError(f"HTTP {resp.status_code} per {url}")
    if "Human Verification" in resp.text[:500]:
        raise ScraperError("Transfermarkt: IP bloccata da Cloudflare")
    return resp.text


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _slug_tm(name: str) -> str:
    import unicodedata
    # Normalizza accenti (é→e, ć→c, ecc.) prima di slugificare
    normalized = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "-", normalized.lower().strip()).strip("-")


# ---------------------------------------------------------------------------
# Alias mapping: nome estratto dall'AI → nome canonico cercabile
# ---------------------------------------------------------------------------

_aliases: dict[str, str | None] | None = None
_aliases_path: Path | None = None


def _load_aliases(root: Path) -> dict[str, str | None]:
    global _aliases, _aliases_path
    _aliases_path = root / "mercato" / "player-aliases.json"
    if _aliases is None:
        if _aliases_path.exists():
            try:
                raw = json.loads(_aliases_path.read_text(encoding="utf-8"))
                _aliases = {k: v for k, v in raw.items() if not k.startswith("_")}
            except Exception:
                _aliases = {}
        else:
            _aliases = {}
    return _aliases


def resolve_player_name(player_name: str, root: Path | None) -> str | None:
    """Risolve un nome estratto dall'AI nel nome canonico da cercare.

    Ritorna:
      - il nome canonico (stringa) se c'è un alias definito
      - il nome originale se non c'è alias
      - None se l'alias è esplicitamente null (giocatore da ignorare)
    """
    if root is None:
        return player_name
    aliases = _load_aliases(root)
    slug = _slug_tm(player_name)
    if slug not in aliases:
        return player_name
    canonical = aliases[slug]
    if canonical is None:
        return None  # segnale: skip questo giocatore
    return canonical


def _names_share_token(name_a: str, name_b: str) -> bool:
    """Verifica che i due nomi condividano almeno un token significativo (>= 3 chars)."""
    tokens_a = {t.lower() for t in re.split(r"[\s\-]+", name_a) if len(t) >= 3}
    tokens_b = {t.lower() for t in re.split(r"[\s\-]+", name_b) if len(t) >= 3}
    return bool(tokens_a & tokens_b)


def _parse_transfer_type_tm(fee: str) -> str:
    fee_clean = re.sub(r"<[^>]+>", "", fee or "").strip()
    if _PRESTITO_RE.search(fee_clean):
        return "loan"
    if _FREE_RE.search(fee_clean):
        return "free_agent"
    if _RINNOVO_RE.search(fee_clean):
        return "extension"
    if fee_clean and fee_clean not in ("?", "-", ""):
        return "permanent"
    return "unknown"


# ---------------------------------------------------------------------------
# Cache locale player_slug → {tm_id, ss_id}
# ---------------------------------------------------------------------------

_tm_id_cache: dict[str, dict] | None = None
_tm_id_cache_path: Path | None = None


def _load_cache(root: Path) -> dict[str, dict]:
    global _tm_id_cache, _tm_id_cache_path
    _tm_id_cache_path = root / "mercato" / "player-tm-ids.json"
    if _tm_id_cache is None:
        if _tm_id_cache_path.exists():
            try:
                raw = json.loads(_tm_id_cache_path.read_text(encoding="utf-8"))
                # Normalizza: valori possono essere str (vecchio) o dict (nuovo)
                _tm_id_cache = {}
                for k, v in raw.items():
                    if isinstance(v, str):
                        _tm_id_cache[k] = {"tm_id": v, "ss_id": None}
                    elif isinstance(v, dict):
                        _tm_id_cache[k] = v
            except Exception:
                _tm_id_cache = {}
        else:
            _tm_id_cache = {}
    return _tm_id_cache


def _save_cache() -> None:
    if _tm_id_cache is not None and _tm_id_cache_path is not None:
        _tm_id_cache_path.parent.mkdir(parents=True, exist_ok=True)
        _tm_id_cache_path.write_text(
            json.dumps(_tm_id_cache, ensure_ascii=False, indent=2), encoding="utf-8"
        )


def set_player_tm_id(root: Path, player_name: str, tm_id: str) -> None:
    cache = _load_cache(root)
    slug = _slug_tm(player_name)
    entry = cache.get(slug) or {}
    entry["tm_id"] = tm_id
    cache[slug] = entry
    _save_cache()


def get_player_ids(root: Path, player_name: str) -> dict:
    """Ritorna {'tm_id': ..., 'ss_id': ...} dalla cache locale."""
    cache = _load_cache(root)
    return cache.get(_slug_tm(player_name)) or {}


# ---------------------------------------------------------------------------
# Ricerca giocatori
# ---------------------------------------------------------------------------

_last_search_time: float = 0.0
_SEARCH_INTERVAL = 3.0


def _wait_search():
    global _last_search_time
    elapsed = time.monotonic() - _last_search_time
    if elapsed < _SEARCH_INTERVAL:
        time.sleep(_SEARCH_INTERVAL - elapsed)
    _last_search_time = time.monotonic()


def _search_tm_html(player_name: str) -> dict | None:
    """Cerca su TM via HTML (cold request, no x-requested-with)."""
    _wait_search()
    query = player_name.replace(" ", "+")
    url = f"{_TM_BASE}/schnellsuche/ergebnis/schnellsuche?query={query}"
    try:
        html = _get_html_tm(url)
    except ScraperError:
        return None

    for slug, tm_id, name in _PLAYER_LINK_RE.findall(html):
        name = name.strip()
        if not name or len(name) < 2:
            continue
        return {
            "name": name,
            "tm_id": tm_id,
            "tm_path": f"/{slug}/profil/spieler/{tm_id}",
            "ss_id": None,
        }
    return None


def _search_sofascore(player_name: str) -> dict | None:
    """Cerca su Sofascore. Ritorna {name, ss_id} o None.

    Verifica che il risultato condivida almeno un token col nome cercato
    per evitare falsi positivi (es. "Ivan" → Rakitić).
    """
    try:
        data = _get_json_ss(f"search/all?q={player_name.replace(' ', '+')}")
        results = data.get("results", [])
        for r in results:
            if r.get("type") == "player":
                ent = r.get("entity", {})
                found_name = ent.get("name", "")
                # Rifiuta se non condivide alcun token col nome cercato
                if not _names_share_token(player_name, found_name):
                    logger.debug(f"SS: scartato '{found_name}' per query '{player_name}' (nessun token comune)")
                    continue
                return {
                    "name": found_name,
                    "ss_id": str(ent.get("id", "")),
                    "tm_id": None,
                    "tm_path": "",
                }
    except ScraperError:
        pass
    return None


def search_player(player_name: str, root: Path | None = None) -> dict | None:
    """Trova i dati del giocatore (tm_id e/o ss_id).

    Strategia:
      1. Cache locale
      2. TM HTML search (se TM disponibile)
      3. Sofascore search (sempre disponibile)
    """
    ids = get_player_ids(root, player_name) if root else {}
    if ids.get("tm_id") or ids.get("ss_id"):
        return {
            "name": player_name,
            "tm_id": ids.get("tm_id"),
            "ss_id": ids.get("ss_id"),
            "tm_path": ids.get("tm_path", ""),
        }

    result = None

    # Prova TM HTML (solo se TM non è bloccata)
    if _tm_available():
        result = _search_tm_html(player_name)

    # Fallback Sofascore
    if not result or not result.get("tm_id"):
        ss_result = _search_sofascore(player_name)
        if ss_result:
            if result:
                result["ss_id"] = ss_result["ss_id"]
            else:
                result = ss_result

    if result and root:
        slug = _slug_tm(player_name)
        cache = _load_cache(root)
        entry = cache.get(slug) or {}
        if result.get("tm_id"):
            entry["tm_id"] = result["tm_id"]
            entry["tm_path"] = result.get("tm_path", "")
        if result.get("ss_id"):
            entry["ss_id"] = result["ss_id"]
        cache[slug] = entry
        _save_cache()

    return result


# ---------------------------------------------------------------------------
# Fetch trasferimenti da TM
# ---------------------------------------------------------------------------


def _fetch_from_tm(tm_id: str, tm_path: str, player_name: str, season: str | None) -> list[dict]:
    profile_url = f"{_TM_BASE}{tm_path}" if tm_path else f"{_TM_BASE}/{_slug_tm(player_name)}/profil/spieler/{tm_id}"
    source_url = f"{_TM_BASE}/ceapi/transferHistory/list/{tm_id}"

    try:
        _get_html_tm(profile_url)
    except ScraperError:
        pass

    data = _get_json_tm(source_url, referer=profile_url)
    raw_transfers = data.get("transfers", [])

    transfers = []
    for tr in raw_transfers:
        tr_season = tr.get("season", "")
        if season:
            season_short = season[-2:]
            if not (tr_season.startswith(season_short + "/") or tr_season.endswith("/" + season_short)):
                continue

        fee = tr.get("fee", "")
        transfer_type = _parse_transfer_type_tm(fee)

        date_iso = tr.get("dateUnformatted")
        confirmed_at: datetime = datetime.now(timezone.utc)
        if date_iso:
            try:
                confirmed_at = datetime.fromisoformat(date_iso).replace(tzinfo=timezone.utc)
            except ValueError:
                pass
        else:
            date_str = tr.get("date", "")
            for fmt in ("%d/%m/%Y", "%d.%m.%Y"):
                try:
                    confirmed_at = datetime.strptime(date_str, fmt).replace(tzinfo=timezone.utc)
                    break
                except ValueError:
                    continue

        from_club = (tr.get("from") or {}).get("clubName") or None
        to_club = (tr.get("to") or {}).get("clubName") or None
        if from_club == to_club:
            continue

        transfers.append({
            "player_name": player_name,
            "from_club": from_club,
            "to_club": to_club,
            "transfer_type": transfer_type,
            "confirmed_at": confirmed_at,
            "season": tr_season,
            "source_url": source_url,
            "source": "transfermarkt",
        })
    return transfers


# ---------------------------------------------------------------------------
# Fetch trasferimenti da Sofascore
# ---------------------------------------------------------------------------


def _sofascore_season(tr: dict) -> str:
    """Calcola la stringa stagione dal timestamp del trasferimento."""
    ts = tr.get("transferDateTimestamp")
    if not ts:
        return ""
    dt = datetime.fromtimestamp(ts, tz=timezone.utc)
    year = dt.year
    month = dt.month
    # Stagione: luglio-giugno. Es. luglio 2025 → 25/26
    if month >= 7:
        return f"{str(year)[2:]}/{str(year + 1)[2:]}"
    else:
        return f"{str(year - 1)[2:]}/{str(year)[2:]}"


def _fetch_from_sofascore(ss_id: str, player_name: str, season: str | None) -> list[dict]:
    data = _get_json_ss(f"player/{ss_id}/transfer-history")
    raw_transfers = data.get("transferHistory", [])

    transfers = []
    for tr in raw_transfers:
        tr_season = _sofascore_season(tr)
        if season:
            season_short = season[-2:]
            if not (tr_season.startswith(season_short + "/") or tr_season.endswith("/" + season_short)):
                continue

        ss_type = tr.get("type", 0)
        if ss_type in _SS_LOAN_TYPES:
            transfer_type = "loan"
        else:
            fee_val = (tr.get("transferFeeRaw") or {}).get("value") or 0
            transfer_type = "permanent" if fee_val > 0 else "free_agent"
        ts = tr.get("transferDateTimestamp")
        confirmed_at = datetime.fromtimestamp(ts, tz=timezone.utc) if ts else datetime.now(timezone.utc)

        from_club = (tr.get("transferFrom") or {}).get("name") or None
        to_club = (tr.get("transferTo") or {}).get("name") or None
        if not from_club and not to_club:
            from_club = tr.get("fromTeamName")
            to_club = tr.get("toTeamName")
        if from_club == to_club:
            continue

        transfers.append({
            "player_name": player_name,
            "from_club": from_club,
            "to_club": to_club,
            "transfer_type": transfer_type,
            "confirmed_at": confirmed_at,
            "season": tr_season,
            "source_url": f"https://www.sofascore.com/player/{ss_id}",
            "source": "sofascore",
        })
    return transfers


# ---------------------------------------------------------------------------
# API pubblica
# ---------------------------------------------------------------------------


def fetch_player_transfers(
    player_name: str,
    season: str | None = None,
    root: Path | None = None,
) -> list[dict]:
    """Scarica la cronologia trasferimenti di un giocatore.

    Prima risolve il nome tramite alias (player-aliases.json), poi prova
    TM e Sofascore come fallback automatico.
    """
    # Risolvi alias prima di cercare
    canonical = resolve_player_name(player_name, root)
    if canonical is None:
        raise ScraperError(f"'{player_name}' è in alias con valore null: skip esplicito")
    search_name = canonical  # può essere diverso da player_name

    player = search_player(search_name, root=root)
    if not player:
        raise ScraperError(f"Giocatore non trovato: '{search_name}' (estratto come '{player_name}')")

    tm_id = player.get("tm_id")
    ss_id = player.get("ss_id")

    # Prova TM
    if tm_id and _tm_available():
        try:
            transfers = _fetch_from_tm(tm_id, player.get("tm_path", ""), player.get("name", player_name), season)
            logger.info(f"TM: {len(transfers)} trasferimenti per '{player_name}'")
            return transfers
        except ScraperError as e:
            logger.warning(f"TM fallback a SS per '{player_name}': {e}")

    # Sofascore fallback — cerca ss_id se non ce l'abbiamo
    if not ss_id:
        ss_result = _search_sofascore(player_name)
        if ss_result:
            ss_id = ss_result["ss_id"]
            if root:
                slug = _slug_tm(player_name)
                cache = _load_cache(root)
                entry = cache.get(slug) or {}
                entry["ss_id"] = ss_id
                cache[slug] = entry
                _save_cache()

    if ss_id:
        transfers = _fetch_from_sofascore(ss_id, player.get("name", player_name), season)
        logger.info(f"Sofascore: {len(transfers)} trasferimenti per '{player_name}'")
        return transfers

    raise ScraperError(f"Nessuna fonte disponibile per '{player_name}' (tm_id={tm_id}, ss_id={ss_id})")
