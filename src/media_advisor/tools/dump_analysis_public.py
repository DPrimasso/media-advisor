"""Write web/public/analysis from SQLite video_analysis (Vue static dashboard)."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from media_advisor.config import Settings
from media_advisor.db.repository import iter_all_video_analysis_rows
from media_advisor.db.session import session_scope
from media_advisor.io.channel_store import load_channels_config_dict
from media_advisor.models.channels import ChannelsConfig


def _clear_analysis_public(public_dir: Path) -> None:
    if not public_dir.exists():
        public_dir.mkdir(parents=True, exist_ok=True)
        return
    for p in public_dir.iterdir():
        if p.name == ".gitkeep":
            continue
        try:
            if p.is_dir():
                shutil.rmtree(p, ignore_errors=True)
            else:
                p.unlink(missing_ok=True)
        except OSError:
            pass


def main() -> None:
    settings = Settings()
    root = settings.root_dir.resolve()
    public_dir = root / "web" / "public" / "analysis"
    _clear_analysis_public(public_dir)

    rows_flat: list[tuple[str, str, str]] = []
    with session_scope(root, read_only=True) as session:
        for row in iter_all_video_analysis_rows(session):
            rows_flat.append((row.channel_id, row.video_id, row.payload_json))

    by_channel: dict[str, list[tuple[str, str, str]]] = {}
    for channel_id, video_id, payload_json in rows_flat:
        by_channel.setdefault(channel_id, []).append((channel_id, video_id, payload_json))

    raw_cfg = load_channels_config_dict(root)
    cfg = ChannelsConfig.model_validate(raw_cfg)
    channels_sorted = sorted(cfg.channels, key=lambda c: c.order)

    index: list[dict] = []
    for ch in channels_sorted:
        ch_rows = by_channel.get(ch.id, [])
        if not ch_rows:
            continue
        dest = public_dir / ch.id
        dest.mkdir(parents=True, exist_ok=True)
        videos: list[str] = []
        for _cid, vid, payload_json in ch_rows:
            fname = f"{vid}.json"
            (dest / fname).write_text(payload_json, encoding="utf-8")
            videos.append(fname)
        entry: dict = {
            "id": ch.id,
            "name": ch.name,
            "order": ch.order,
            "videos": sorted(videos),
        }
        index.append(entry)

    (public_dir / "index.json").write_text(
        json.dumps(index, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"wrote {public_dir} ({len(index)} channels, {sum(len(by_channel.get(c.id, [])) for c in channels_sorted)} files)")


if __name__ == "__main__":
    main()
