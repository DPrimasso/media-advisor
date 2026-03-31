"""Fetch new videos from channels according to fetch_rule config.

Porting of src/fetch-new-videos.ts.
Outputs channels/pending.json with videos not yet in the video_list.
"""

import asyncio
import re
from datetime import datetime, timezone
from pathlib import Path

import httpx

from media_advisor.io.json_io import read_json, write_json
from media_advisor.io.paths import channels_config_path, channel_list_path, pending_path
from media_advisor.models.channels import (
    ChannelsConfig,
    FetchRuleTranscriptApi,
)
from media_advisor.models.pending import PendingResult, PendingVideo
from media_advisor.transcript_api.client import TranscriptAPIError, TranscriptClient

_VIDEO_ID_RE = re.compile(r"(?:v=)([a-zA-Z0-9_-]{11})")
_LIVE_RE = re.compile(r"\b(live|livestream|streaming|diretta)\b|🔴", re.IGNORECASE)


def _extract_video_id(url_or_id: str) -> str | None:
    m = _VIDEO_ID_RE.search(url_or_id)
    if m:
        return m.group(1)
    if len(url_or_id) == 11:
        return url_or_id
    return None


def _get_existing_ids(root: Path, video_list: str) -> set[str]:
    path = channel_list_path(root, video_list)
    if not path.exists():
        return set()
    try:
        urls = read_json(path)
        if not isinstance(urls, list):
            return set()
        ids: set[str] = set()
        for u in urls:
            vid = _extract_video_id(str(u))
            if vid:
                ids.add(vid)
        return ids
    except Exception:
        return set()


async def _fetch_from_transcript_api(
    channel_id: str,
    channel_name: str,
    rule: FetchRuleTranscriptApi,
    client: TranscriptClient,
) -> list[PendingVideo]:
    channel_input = rule.channel_url or rule.channel_id
    if not channel_input:
        print(f"[{channel_id}] transcript_api rule: missing channel_url/channel_id, skip")
        return []

    last_n = rule.last_n or 15
    videos: list[dict] = []

    # Collect enough pages to cover last_n
    continuation: str | None = None
    while len(videos) < last_n:
        page = await client.get_channel_videos(channel=channel_input if not continuation else None,
                                               continuation=continuation)
        results = page.get("results", [])
        videos.extend(results)
        continuation = page.get("continuation_token")
        if not continuation or not page.get("has_more"):
            break

    # Filter by title_contains
    if rule.title_contains:
        needle = rule.title_contains.lower()
        videos = [v for v in videos if needle in v.get("title", "").lower()]

    videos = videos[:last_n]

    pending: list[PendingVideo] = []
    for v in videos:
        vid = v.get("videoId") or _extract_video_id(v.get("url", ""))
        if not vid:
            continue
        pending.append(
            PendingVideo(
                video_id=vid,
                title=v.get("title", ""),
                channel_id=channel_id,
                channel_name=channel_name,
                url=f"https://www.youtube.com/watch?v={vid}",
                published_at=v.get("published") or v.get("published_at"),
            )
        )
    return pending


async def _fetch_from_rss(
    channel_id: str,
    channel_name: str,
    yt_channel_id: str,
    last_n: int = 15,
) -> list[PendingVideo]:
    """RSS fallback: parse YouTube channel RSS feed."""
    url = f"https://www.youtube.com/feeds/videos.xml?channel_id={yt_channel_id}"
    try:
        async with httpx.AsyncClient(timeout=15.0) as c:
            resp = await c.get(url)
            resp.raise_for_status()
    except Exception as e:
        print(f"[{channel_id}] RSS fetch failed: {e}")
        return []

    import xml.etree.ElementTree as ET

    ns = {"yt": "http://www.youtube.com/xml/schemas/2015", "media": "http://search.yahoo.com/mrss/"}
    try:
        root_el = ET.fromstring(resp.text)
    except ET.ParseError:
        return []

    entries = root_el.findall("{http://www.w3.org/2005/Atom}entry")[:last_n]
    pending: list[PendingVideo] = []
    for entry in entries:
        vid_el = entry.find("yt:videoId", ns)
        title_el = entry.find("{http://www.w3.org/2005/Atom}title")
        pub_el = entry.find("{http://www.w3.org/2005/Atom}published")
        if vid_el is None:
            continue
        vid = vid_el.text or ""
        title = title_el.text if title_el is not None else ""
        published = pub_el.text if pub_el is not None else None
        pending.append(
            PendingVideo(
                video_id=vid,
                title=title or "",
                channel_id=channel_id,
                channel_name=channel_name,
                url=f"https://www.youtube.com/watch?v={vid}",
                published_at=published,
            )
        )
    return pending


async def run_fetch_new_videos(root: Path, transcript_api_key: str) -> PendingResult:
    config_path = channels_config_path(root)
    raw = read_json(config_path)
    config = ChannelsConfig.model_validate(raw)

    channels = sorted(
        [c for c in config.channels if c.fetch_rule and c.fetch_rule.type != "manual"],
        key=lambda c: c.order,
    )

    client = TranscriptClient(transcript_api_key)
    all_new: list[PendingVideo] = []

    for channel in channels:
        rule = channel.fetch_rule
        if rule is None:
            continue
        existing = _get_existing_ids(root, channel.video_list)

        fetched: list[PendingVideo] = []

        if rule.type == "transcript_api":
            try:
                fetched = await _fetch_from_transcript_api(channel.id, channel.name, rule, client)
            except (TranscriptAPIError, Exception) as e:
                channel_url = getattr(rule, "channel_url", None)
                if channel_url:
                    print(f"[{channel.id}] TranscriptAPI failed ({e}), trying RSS fallback")
                    # resolve channel_id via oembed would require another call;
                    # for now skip RSS fallback (channel_id not available here)
                    print(f"[{channel.id}] RSS fallback requires UC channel_id, skip")
                else:
                    print(f"[{channel.id}] TranscriptAPI failed, skip: {e}")
                continue
        elif rule.type == "rss":
            yt_id = getattr(rule, "channel_id", None)
            if yt_id and yt_id.startswith("UC"):
                fetched = await _fetch_from_rss(channel.id, channel.name, yt_id,
                                                last_n=getattr(rule, "last_n", 15) or 15)
            else:
                print(f"[{channel.id}] RSS rule requires channel_id (UC...), skip")
                continue
        else:
            continue

        # Apply filters
        exclude = getattr(rule, "exclude_title_contains", None)
        if exclude:
            excl_lower = exclude.lower()
            fetched = [v for v in fetched if excl_lower not in v.title.lower()]

        if getattr(rule, "exclude_live", False):
            fetched = [v for v in fetched if not _LIVE_RE.search(v.title)]

        new_videos = [v for v in fetched if v.video_id not in existing]
        all_new.extend(new_videos)
        print(f"[{channel.id}] {len(fetched)} fetched, {len(new_videos)} new")

    result = PendingResult(
        fetched_at=datetime.now(timezone.utc),
        items=all_new,
    )

    write_json(
        pending_path(root),
        result.model_dump(mode="json"),
    )
    print(f"Wrote pending.json with {len(all_new)} pending videos")
    return result
