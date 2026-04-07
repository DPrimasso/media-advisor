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
