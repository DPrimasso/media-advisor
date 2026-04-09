"""Path helpers — porting of src/paths.ts."""

from pathlib import Path


def transcript_path(root: Path, channel_id: str, video_id: str) -> Path:
    """transcripts/<channel_id>/<video_id>.json"""
    return root / "transcripts" / channel_id / f"{video_id}.json"


def analysis_path(root: Path, channel_id: str, video_id: str) -> Path:
    """analysis/<channel_id>/<video_id>.json"""
    return root / "analysis" / channel_id / f"{video_id}.json"


def misc_transcript_path(root: Path, video_id: str) -> Path:
    """transcripts/_misc/<video_id>.json"""
    return root / "transcripts" / "_misc" / f"{video_id}.json"


def channels_config_path(root: Path) -> Path:
    return root / "channels" / "channels.json"


def pending_path(root: Path) -> Path:
    return root / "channels" / "pending.json"


def channel_list_path(root: Path, video_list_filename: str) -> Path:
    return root / "channels" / video_list_filename


def mercato_tips_path(root: Path, channel_id: str, video_id: str) -> Path:
    """mercato/tips/<channel_id>/<video_id>.json"""
    return root / "mercato" / "tips" / channel_id / f"{video_id}.json"


def mercato_index_path(root: Path) -> Path:
    """mercato/index.json"""
    return root / "mercato" / "index.json"


def transfers_index_path(root: Path) -> Path:
    """mercato/transfers.json"""
    return root / "mercato" / "transfers.json"


def video_dates_cache_path(root: Path) -> Path:
    """channels/video-dates.json — mappa video_id → published_at per tutti i canali."""
    return root / "channels" / "video-dates.json"


def player_tm_ids_path(root: Path) -> Path:
    """mercato/player-tm-ids.json — mappa player_slug → {tm_id, ss_id} persistente."""
    return root / "mercato" / "player-tm-ids.json"


def player_aliases_path(root: Path) -> Path:
    """mercato/player-aliases.json — mappa alias_slug → nome canonico per la ricerca."""
    return root / "mercato" / "player-aliases.json"
