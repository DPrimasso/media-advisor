"""Scraping di Transfermarkt per recuperare trasferimenti ufficiali.

Usa curl_cffi per bypassare la protezione Cloudflare di Transfermarkt
e BeautifulSoup per il parsing HTML.

Se il sito è irraggiungibile o blocca la richiesta, viene sollevata
ScraperError con un messaggio descrittivo — l'inserimento manuale copre il gap.
"""

import logging
import re
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

_TM_BASE = "https://www.transfermarkt.it"
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "it-IT,it;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


class ScraperError(Exception):
    pass


def _get(url: str) -> str:
    """Fetch con curl_cffi (TLS fingerprinting realistico)."""
    try:
        from curl_cffi import requests as cffi_requests
        resp = cffi_requests.get(url, headers=_HEADERS, impersonate="chrome124", timeout=15)
        if resp.status_code != 200:
            raise ScraperError(f"HTTP {resp.status_code} per {url}")
        return resp.text
    except ImportError:
        raise ScraperError(
            "curl_cffi non installato. Esegui: python -m pip install curl_cffi"
        )


def _slug_tm(name: str) -> str:
    """Slug-style per URL Transfermarkt (trattini, lowercase)."""
    return re.sub(r"[^a-z0-9]+", "-", name.lower().strip()).strip("-")


def search_player(player_name: str) -> list[dict]:
    """Cerca un giocatore su Transfermarkt. Ritorna lista di candidati.

    Ogni entry: {"name": str, "tm_id": str, "tm_path": str, "club": str}
    """
    from bs4 import BeautifulSoup

    url = f"{_TM_BASE}/schnellsuche/ergebnis/schnellsuche?query={player_name.replace(' ', '+')}"
    html = _get(url)
    soup = BeautifulSoup(html, "html.parser")

    results = []
    # La tabella giocatori ha class "items" nella sezione giocatori
    for table in soup.select("table.items"):
        header = table.find_previous("h2")
        if header and "giocator" not in header.get_text().lower() and "player" not in header.get_text().lower():
            continue
        for row in table.select("tbody tr"):
            link = row.select_one("td.hauptlink a")
            if not link:
                continue
            club_td = row.select_one("td.zentriert img")
            club = club_td.get("title", "") if club_td else ""
            href = link.get("href", "")
            tm_id_match = re.search(r"/(\d+)$", href)
            results.append({
                "name": link.get_text(strip=True),
                "tm_id": tm_id_match.group(1) if tm_id_match else "",
                "tm_path": href,
                "club": club,
            })
    return results


def fetch_player_transfers(player_name: str, season: str | None = None) -> list[dict]:
    """Scarica la cronologia trasferimenti di un giocatore da Transfermarkt.

    Args:
        player_name: nome del giocatore (es. "Romelu Lukaku")
        season: filtro stagione es. "2025" (anno di inizio, es. 2025 per 2025-26).
                Se None, restituisce tutti i trasferimenti.

    Returns:
        Lista di dict con: player_name, from_club, to_club, transfer_type,
        confirmed_at (datetime), season, source_url.

    Raises:
        ScraperError: se il sito non è raggiungibile o il player non viene trovato.
    """
    from bs4 import BeautifulSoup

    # 1. Cerca il giocatore
    candidates = search_player(player_name)
    if not candidates:
        raise ScraperError(f"Nessun giocatore trovato su Transfermarkt per '{player_name}'")

    # Prendi il primo risultato (il più rilevante)
    candidate = candidates[0]
    tm_path = candidate["tm_path"]

    # 2. Costruisci URL pagina trasferimenti
    # es. /romelu-lukaku/transfers/spieler/12345 → /romelu-lukaku/transfers/spieler/12345
    # La pagina profilo è /romelu-lukaku/profil/spieler/12345
    # La pagina trasferimenti è /romelu-lukaku/transfers/spieler/12345
    transfers_path = re.sub(r"/profil/", "/transfers/", tm_path)
    if "/transfers/" not in transfers_path:
        # fallback: prova a costruire l'URL corretto
        slug_match = re.search(r"^/([^/]+)/", tm_path)
        id_match = re.search(r"/(\d+)$", tm_path)
        if slug_match and id_match:
            transfers_path = f"/{slug_match.group(1)}/transfers/spieler/{id_match.group(1)}"

    source_url = f"{_TM_BASE}{transfers_path}"
    html = _get(source_url)
    soup = BeautifulSoup(html, "html.parser")

    transfers = []

    # 3. Parsing tabella trasferimenti
    for row in soup.select("table.transferHistory_table tbody tr, div.tm-player-transfer-history-grid > div"):
        # Prova layout griglia (versione moderna TM)
        cells = row.select("div.grid__cell, td")
        if len(cells) < 4:
            continue

        try:
            # Stagione
            season_text = cells[0].get_text(strip=True)  # es. "25/26"
            # Data
            date_text = cells[1].get_text(strip=True) if len(cells) > 1 else ""
            # Club provenienza
            from_club = cells[2].get_text(strip=True) if len(cells) > 2 else ""
            # Club destinazione
            to_club = cells[3].get_text(strip=True) if len(cells) > 3 else ""
            # Fee (per determinare tipo)
            fee_text = cells[-1].get_text(strip=True).lower() if cells else ""

            # Determina tipo trasferimento
            transfer_type = "unknown"
            if "prestit" in fee_text or "loan" in fee_text or "prest" in fee_text:
                transfer_type = "loan"
            elif "svincol" in fee_text or "free" in fee_text or fee_text == "-":
                transfer_type = "free_agent"
            elif "rinnov" in fee_text or "prolungamento" in fee_text:
                transfer_type = "extension"
            elif fee_text and fee_text != "?" and fee_text != "":
                transfer_type = "permanent"

            # Converti data
            confirmed_at: datetime = datetime.now(timezone.utc)
            for fmt in ("%d/%m/%Y", "%d.%m.%Y", "%b %d, %Y"):
                try:
                    confirmed_at = datetime.strptime(date_text, fmt).replace(tzinfo=timezone.utc)
                    break
                except ValueError:
                    continue

            # Filtro stagione (es. "2025" → cerca "25" in season_text)
            if season:
                season_short = season[-2:]  # ultimi 2 digit dell'anno
                if season_short not in season_text:
                    continue

            transfers.append({
                "player_name": candidate["name"],
                "from_club": from_club or None,
                "to_club": to_club or None,
                "transfer_type": transfer_type,
                "confirmed_at": confirmed_at,
                "season": season_text,
                "source_url": source_url,
            })
        except Exception as e:
            logger.debug(f"Riga trasferimento ignorata: {e}")
            continue

    if not transfers:
        logger.warning(f"Nessun trasferimento trovato per '{player_name}' (URL: {source_url})")

    return transfers
