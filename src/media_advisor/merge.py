"""Merge pending.json items into channel video lists, then clear pending.

Porting of src/merge-pending.ts.
"""

import re
from pathlib import Path

from media_advisor.io.channel_store import (
    load_channels_config_dict,
    load_pending_dict,
    read_channel_video_urls,
    save_pending_dict,
    write_channel_video_urls,
)
from media_advisor.models.channels import ChannelsConfig
from media_advisor.models.pending import PendingResult

_VID_RE = re.compile(r"v=([a-zA-Z0-9_-]{11})")


def _extract_id(url: str) -> str | None:
    m = _VID_RE.search(url)
    return m.group(1) if m else None


def merge_pending_into_channels(root: Path) -> int:
    raw_pending = load_pending_dict(root)
    pending = PendingResult.model_validate(raw_pending)
    if not pending.items:
        return 0

    config_raw = load_channels_config_dict(root)
    config = ChannelsConfig.model_validate(config_raw)
    channel_map = {c.id: c.video_list for c in config.channels}

    # Group new URLs by list file
    to_append: dict[str, list[str]] = {}
    for item in pending.items:
        list_file = channel_map.get(item.channel_id)
        if not list_file:
            continue
        to_append.setdefault(list_file, []).append(
            f"https://www.youtube.com/watch?v={item.video_id}"
        )

    added = 0
    for list_key, urls in to_append.items():
        existing = read_channel_video_urls(root, list_key)
        existing_ids = {_extract_id(u) for u in existing} - {None}
        # Prepend: le liste canale sono tenute newest-first; append rompeva sync recenti / ordine UI.
        new_front: list[str] = []
        for url in urls:
            vid = _extract_id(url)
            if vid and vid not in existing_ids:
                new_front.append(url)
                existing_ids.add(vid)
                added += 1
        combined = new_front + list(existing)
        write_channel_video_urls(root, list_key, combined)

    # Clear pending
    save_pending_dict(root, {"fetched_at": None, "items": []})
    return added
