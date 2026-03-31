"""Merge pending.json items into channel video lists, then clear pending.

Porting of src/merge-pending.ts.
"""

import re
from pathlib import Path

from media_advisor.io.json_io import read_json, read_video_list, write_json, write_video_list
from media_advisor.io.paths import channels_config_path, channel_list_path, pending_path
from media_advisor.models.channels import ChannelsConfig
from media_advisor.models.pending import PendingResult

_VID_RE = re.compile(r"v=([a-zA-Z0-9_-]{11})")


def _extract_id(url: str) -> str | None:
    m = _VID_RE.search(url)
    return m.group(1) if m else None


def merge_pending_into_channels(root: Path) -> int:
    ppath = pending_path(root)
    if not ppath.exists():
        return 0

    raw_pending = read_json(ppath)
    pending = PendingResult.model_validate(raw_pending)
    if not pending.items:
        return 0

    config_raw = read_json(channels_config_path(root))
    config = ChannelsConfig.model_validate(config_raw)
    channel_map = {c.id: c.video_list for c in config.channels}

    # Group new URLs by list file
    to_append: dict[Path, list[str]] = {}
    for item in pending.items:
        list_file = channel_map.get(item.channel_id)
        if not list_file:
            continue
        list_path = channel_list_path(root, list_file)
        if not list_path.exists():
            continue
        to_append.setdefault(list_path, []).append(
            f"https://www.youtube.com/watch?v={item.video_id}"
        )

    added = 0
    for list_path, urls in to_append.items():
        existing = read_video_list(list_path)
        existing_ids = {_extract_id(u) for u in existing} - {None}
        combined = list(existing)
        for url in urls:
            vid = _extract_id(url)
            if vid and vid not in existing_ids:
                combined.append(url)
                existing_ids.add(vid)
                added += 1
        write_video_list(list_path, combined)

    # Clear pending
    write_json(ppath, {"fetched_at": None, "items": []})
    return added
