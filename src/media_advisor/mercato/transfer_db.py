"""Database locale dei trasferimenti ufficiali confermati (SQLite blob + legacy file)."""

import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from media_advisor.db.repository import MERCATO_BLOB_TRANSFERS, fetch_mercato_blob_raw, upsert_mercato_blob
from media_advisor.db.session import session_scope
from media_advisor.io.json_io import read_json_or_default
from media_advisor.io.paths import transfers_index_path
from media_advisor.mercato.models import TransferType


class TransferRecord(BaseModel):
    transfer_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    player_name: str
    player_slug: str
    from_club: str | None = None
    to_club: str | None
    transfer_type: TransferType = "unknown"
    season: str                           # es. "2025-26"
    confirmed_at: datetime                # data ufficialità trasferimento
    source: Literal["transfermarkt", "sofascore", "manual"] = "manual"
    source_url: str | None = None         # link pagina Transfermarkt
    notes: str | None = None
    added_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class TransferIndex(BaseModel):
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    transfers: list[TransferRecord] = Field(default_factory=list)


def player_slug(name: str) -> str:
    """Converte nome giocatore in slug URL-safe (es. 'Alessandro Bastoni' → 'alessandro-bastoni')."""
    return re.sub(r"[^a-z0-9]+", "-", name.lower().strip()).strip("-")


def load_transfers(root: Path) -> TransferIndex:
    with session_scope(root, read_only=True) as session:
        raw = fetch_mercato_blob_raw(session, MERCATO_BLOB_TRANSFERS)
    if raw:
        try:
            return TransferIndex.model_validate(json.loads(raw))
        except Exception:
            pass
    data = read_json_or_default(transfers_index_path(root), default=None)
    if data is None:
        return TransferIndex()
    idx = TransferIndex.model_validate(data)
    with session_scope(root) as session:
        upsert_mercato_blob(session, MERCATO_BLOB_TRANSFERS, idx.model_dump(mode="json"))
    return idx


def save_transfers(root: Path, index: TransferIndex) -> None:
    index.updated_at = datetime.now(timezone.utc)
    payload = index.model_dump(mode="json")
    with session_scope(root) as session:
        upsert_mercato_blob(session, MERCATO_BLOB_TRANSFERS, payload)
    try:
        from media_advisor.mercato.player_normalizer import load_player_registry

        load_player_registry.cache_clear()
    except Exception:
        pass


def add_transfer(root: Path, record: TransferRecord) -> TransferRecord:
    """Aggiunge un trasferimento al database e salva. Ritorna il record salvato."""
    if not record.player_slug:
        record.player_slug = player_slug(record.player_name)
    index = load_transfers(root)
    index.transfers.append(record)
    save_transfers(root, index)
    return record


def remove_transfer(root: Path, transfer_id: str) -> bool:
    """Rimuove un trasferimento per ID. Ritorna True se trovato e rimosso."""
    index = load_transfers(root)
    before = len(index.transfers)
    index.transfers = [t for t in index.transfers if t.transfer_id != transfer_id]
    if len(index.transfers) == before:
        return False
    save_transfers(root, index)
    return True


def get_transfers_for_player(root: Path, player_slug: str) -> list[TransferRecord]:
    """Restituisce tutti i trasferimenti per uno slug giocatore."""
    index = load_transfers(root)
    return [t for t in index.transfers if t.player_slug == player_slug]


def get_all_transfers(root: Path) -> list[TransferRecord]:
    return load_transfers(root).transfers
