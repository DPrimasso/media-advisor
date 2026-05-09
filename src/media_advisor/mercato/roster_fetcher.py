"""Scarica i roster dalle leghe su Transfermarkt per popolare il registry dei nomi giocatori.

Fonte: Transfermarkt (pagine HTML delle rose squadre).
Output: mercato/player-roster.json + SQLite blob "player_roster".
"""

import json
import logging
import re
import time
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from pydantic import BaseModel

logger = logging.getLogger(__name__)

_TM_BASE = "https://www.transfermarkt.it"

# league_id → (url_slug, competition_id_tm)
LEAGUE_INFO: dict[str, tuple[str, str]] = {
    "IT1": ("serie-a", "IT1"),
    "GB1": ("premier-league", "GB1"),
    "ES1": ("laliga", "ES1"),
    "L1": ("1-bundesliga", "L1"),
    "FR1": ("ligue-1", "FR1"),
}

LEAGUE_NAMES: dict[str, str] = {
    "IT1": "Serie A",
    "GB1": "Premier League",
    "ES1": "La Liga",
    "L1": "Bundesliga",
    "FR1": "Ligue 1",
}

MERCATO_BLOB_ROSTER = "player_roster"

# Cattura /slug/profil/spieler/ID">Nome</a>
_PLAYER_LINK_RE = re.compile(
    r'href="/([^/"]+)/profil/spieler/(\d+)"[^>]*>\s*([^<\n]{2,60}?)\s*</a>'
)

# Cattura /slug/startseite/verein/ID
_TEAM_LINK_RE = re.compile(
    r'href="/([^/"]+)/startseite/verein/(\d+)[^"]*"[^>]*>\s*([^<\n]{2,60}?)\s*</a>'
)


# ---------------------------------------------------------------------------
# Modelli
# ---------------------------------------------------------------------------


class PlayerEntry(BaseModel):
    canonical_name: str
    last_name: str
    first_name: str
    club: str
    league: str
    tm_id: str | None = None
    aliases: list[str]


class PlayerRoster(BaseModel):
    updated_at: datetime
    leagues: list[str]
    players: list[PlayerEntry]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ascii_name(name: str) -> str:
    """Converte accenti/diacritici in ASCII (Dušan → Dusan)."""
    normalized = unicodedata.normalize("NFKD", name)
    return normalized.encode("ascii", "ignore").decode("ascii").strip()


def _slug_to_canonical(slug: str) -> str:
    """Converte slug TM in nome proprio ('dusan-vlahovic' → 'Dusan Vlahovic')."""
    return " ".join(part.capitalize() for part in slug.split("-") if part)


def _generate_aliases(canonical_name: str, display_name: str | None = None) -> list[str]:
    """Genera alias automatici (conservativi) per un nome giocatore.

    Auto-generati:
      - versione ASCII del nome completo (se contiene diacritici)
      - cognome solo (ultimo token)
      - cognome composto (ultimi 2 token) per nomi con 3+ token (es. "Di Lorenzo", "Van Dijk")
      - ASCII del cognome
      - forma breve "F. Cognome"

    Non vengono generati soprannomi (es. 'Kvara') — restano in player-aliases.json.
    """
    aliases: list[str] = []

    ascii_full = _ascii_name(canonical_name)
    if ascii_full and ascii_full != canonical_name:
        aliases.append(ascii_full)

    parts = canonical_name.split()
    if len(parts) >= 2:
        last = parts[-1]
        first_initial = parts[0][0] if parts[0] else ""

        aliases.append(last)
        ascii_last = _ascii_name(last)
        if ascii_last and ascii_last != last:
            aliases.append(ascii_last)

        if first_initial:
            aliases.append(f"{first_initial}. {last}")
            ascii_short = f"{first_initial}. {ascii_last if ascii_last else last}"
            if ascii_short not in aliases:
                aliases.append(ascii_short)

        # Per nomi 3+ token, aggiungi anche gli ultimi 2 token come cognome composto
        # Cattura "Di Lorenzo" da "Giovanni Di Lorenzo", "Van Dijk" da "Virgil Van Dijk"
        if len(parts) >= 3:
            compound = " ".join(parts[-2:])
            if compound not in aliases:
                aliases.append(compound)
            ascii_compound = _ascii_name(compound)
            if ascii_compound and ascii_compound != compound and ascii_compound not in aliases:
                aliases.append(ascii_compound)
            if first_initial:
                short_compound = f"{first_initial}. {compound}"
                if short_compound not in aliases:
                    aliases.append(short_compound)

    # Aggiungi display name (testo visibile sul link TM) se diverso
    if display_name and display_name != canonical_name and display_name not in aliases:
        aliases.append(display_name)
        ascii_disp = _ascii_name(display_name)
        if ascii_disp and ascii_disp != display_name and ascii_disp not in aliases:
            aliases.append(ascii_disp)

    # Dedup mantenendo ordine, filtra nomi troppo corti
    seen: set[str] = set()
    result: list[str] = []
    for a in aliases:
        a = a.strip()
        if a and len(a) >= 3 and a not in seen:
            seen.add(a)
            result.append(a)

    return result


# ---------------------------------------------------------------------------
# Fetch TM HTML
# ---------------------------------------------------------------------------


def _get_html(url: str) -> str:
    """GET HTML da Transfermarkt con Chrome impersonation."""
    from media_advisor.mercato.scraper import ScraperError, _TM_HEADERS

    try:
        from curl_cffi import requests as cffi_requests
    except ImportError as exc:
        raise ScraperError("curl_cffi non installato") from exc

    headers = {k: v for k, v in _TM_HEADERS.items() if k.lower() != "x-requested-with"}
    headers["Accept"] = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
    resp = cffi_requests.get(url, headers=headers, impersonate="chrome124", timeout=15)
    if resp.status_code != 200:
        from media_advisor.mercato.scraper import ScraperError
        raise ScraperError(f"HTTP {resp.status_code} per {url}")
    if "Human Verification" in resp.text[:500]:
        from media_advisor.mercato.scraper import ScraperError
        raise ScraperError("Transfermarkt: IP bloccata da Cloudflare (Human Verification)")
    return resp.text


# ---------------------------------------------------------------------------
# Fetch squadre per lega
# ---------------------------------------------------------------------------


def _fetch_team_slugs(league_id: str) -> list[tuple[str, str, str]]:
    """Ritorna [(team_slug, team_tm_id, team_name), ...] per la lega data."""
    from media_advisor.mercato.scraper import ScraperError

    if league_id not in LEAGUE_INFO:
        raise ValueError(f"Lega sconosciuta: {league_id}. Valori: {list(LEAGUE_INFO)}")

    league_slug, comp_id = LEAGUE_INFO[league_id]
    url = f"{_TM_BASE}/{league_slug}/startseite/wettbewerb/{comp_id}"

    try:
        html = _get_html(url)
    except ScraperError as e:
        raise ScraperError(f"Pagina lega {league_id} non raggiungibile: {e}") from e

    seen: set[str] = set()
    teams: list[tuple[str, str, str]] = []

    for slug, tm_id, name in _TEAM_LINK_RE.findall(html):
        name = name.strip()
        if not name or tm_id in seen:
            continue
        seen.add(tm_id)
        teams.append((slug, tm_id, name))

    return teams


# ---------------------------------------------------------------------------
# Fetch rosa squadra
# ---------------------------------------------------------------------------


def _fetch_squad(
    team_slug: str,
    team_tm_id: str,
    team_name: str,
    league_id: str,
) -> list[PlayerEntry]:
    """Scarica la rosa di una squadra TM e ritorna i PlayerEntry."""
    from media_advisor.mercato.scraper import ScraperError

    url = f"{_TM_BASE}/{team_slug}/kader/verein/{team_tm_id}/plus/1"

    try:
        html = _get_html(url)
    except ScraperError as exc:
        logger.warning("Impossibile scaricare rosa %s (%s): %s", team_name, team_tm_id, exc)
        return []

    seen: set[str] = set()
    players: list[PlayerEntry] = []

    for player_slug, tm_id, display_name in _PLAYER_LINK_RE.findall(html):
        display_name = display_name.strip()
        if not display_name or len(display_name) < 2 or tm_id in seen:
            continue
        seen.add(tm_id)

        # Ricostruisce nome canonico dallo slug TM (es. "dusan-vlahovic" → "Dusan Vlahovic")
        canonical = _slug_to_canonical(player_slug)

        parts = canonical.split()
        first_name = " ".join(parts[:-1]) if len(parts) >= 2 else ""
        last_name = parts[-1] if parts else canonical

        aliases = _generate_aliases(canonical, display_name)

        players.append(
            PlayerEntry(
                canonical_name=canonical,
                last_name=last_name,
                first_name=first_name,
                club=team_name,
                league=league_id,
                tm_id=tm_id,
                aliases=aliases,
            )
        )

    return players


# ---------------------------------------------------------------------------
# Fetch completo leghe
# ---------------------------------------------------------------------------


def fetch_league_rosters(
    leagues: list[str],
    root: Path,
    progress_callback: Callable[[str], None] | None = None,
) -> PlayerRoster:
    """Scarica i roster TM per le leghe indicate e salva in JSON + DB.

    Args:
        leagues: Lista di league ID (es. ["IT1", "GB1"]).
        root: Root del progetto (per salvare i file).
        progress_callback: Chiamata con messaggi di progresso.
    """
    all_players: list[PlayerEntry] = []

    for i, league_id in enumerate(leagues):
        if league_id not in LEAGUE_INFO:
            logger.warning("Lega sconosciuta ignorata: %s", league_id)
            if progress_callback:
                progress_callback(f"SKIP: lega sconosciuta '{league_id}'")
            continue

        league_name = LEAGUE_NAMES.get(league_id, league_id)
        if progress_callback:
            progress_callback(f"[{i + 1}/{len(leagues)}] {league_id} - {league_name}: recupero squadre...")

        try:
            teams = _fetch_team_slugs(league_id)
        except Exception as exc:
            logger.error("Errore fetch teams per %s: %s", league_id, exc)
            if progress_callback:
                progress_callback(f"  ERRORE: {exc}")
            continue

        time.sleep(0.5)

        if progress_callback:
            progress_callback(f"  {len(teams)} squadre trovate")

        for j, (team_slug, team_tm_id, team_name) in enumerate(teams):
            time.sleep(0.5)
            players = _fetch_squad(team_slug, team_tm_id, team_name, league_id)
            all_players.extend(players)
            if progress_callback:
                progress_callback(f"  [{j + 1}/{len(teams)}] {team_name}: {len(players)} giocatori")

    roster = PlayerRoster(
        updated_at=datetime.now(timezone.utc),
        leagues=leagues,
        players=all_players,
    )

    _save_roster(root, roster)
    return roster


# ---------------------------------------------------------------------------
# Persistenza
# ---------------------------------------------------------------------------


def _save_roster(root: Path, roster: PlayerRoster) -> None:
    """Salva il roster in mercato/player-roster.json e nel blob SQLite."""
    from media_advisor.db.repository import upsert_mercato_blob
    from media_advisor.db.session import session_scope

    mercato_dir = root / "mercato"
    mercato_dir.mkdir(exist_ok=True)

    data = roster.model_dump(mode="json")

    roster_file = mercato_dir / "player-roster.json"
    roster_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    with session_scope(root) as session:
        upsert_mercato_blob(session, MERCATO_BLOB_ROSTER, data)


def load_player_roster(root: Path) -> PlayerRoster | None:
    """Carica il roster dal blob SQLite o dal file JSON."""
    from media_advisor.db.repository import fetch_mercato_blob_raw
    from media_advisor.db.session import session_scope

    try:
        with session_scope(root, read_only=True) as session:
            raw = fetch_mercato_blob_raw(session, MERCATO_BLOB_ROSTER)
        if raw:
            return PlayerRoster.model_validate(json.loads(raw))
    except Exception:
        pass

    roster_file = root / "mercato" / "player-roster.json"
    if roster_file.exists():
        try:
            return PlayerRoster.model_validate(
                json.loads(roster_file.read_text(encoding="utf-8"))
            )
        except Exception:
            pass

    return None
