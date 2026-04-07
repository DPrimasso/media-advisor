"""Database locale dei trasferimenti ufficiali confermati.

I trasferimenti vengono salvati in mercato/transfers.json e usati
dal verifier per aggiornare automaticamente l'outcome delle tip.
"""

import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from media_advisor.io.json_io import read_json_or_default, write_json
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
    source: Literal["transfermarkt", "manual"] = "manual"
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
    data = read_json_or_default(transfers_index_path(root), default=None)
    if data is None:
        return TransferIndex()
    return TransferIndex.model_validate(data)


def save_transfers(root: Path, index: TransferIndex) -> None:
    index.updated_at = datetime.now(timezone.utc)
    write_json(transfers_index_path(root), index.model_dump(mode="json"))


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
