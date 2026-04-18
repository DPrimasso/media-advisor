"""Fetch new videos from channels according to fetch_rule config.

Porting of src/fetch-new-videos.ts.
Outputs channels/pending.json with videos not yet in the video_list.
"""

import asyncio
import re
from datetime import datetime, timezone
from pathlib import Path

import httpx

from media_advisor.io.json_io import read_json, read_json_or_default, write_json
from media_advisor.io.paths import channels_config_path, channel_list_path, pending_path, video_dates_cache_path
from media_advisor.models.channels import (
    ChannelsConfig,
    FetchRuleTranscriptApi,
)
from media_advisor.models.pending import PendingResult, PendingVideo
from media_advisor.transcript_api.client import TranscriptAPIError, TranscriptClient

_VIDEO_ID_RE = re.compile(r"(?:v=)([a-zA-Z0-9_-]{11})")
_LIVE_RE = re.compile(r"\b(live|livestream|streaming|diretta)\b|🔴", re.IGNORECASE)


def fetch_channel_dates_ytdlp(channel_url: str, max_videos: int = 600) -> dict[str, str]:
    """Usa yt-dlp per ottenere le date di pubblicazione di tutti i video del canale.

    Ritorna un dict {video_id: published_at (ISO date string)} senza scaricare nulla.
    Richiede yt-dlp installato ('python -m pip install yt-dlp').
    """
    import subprocess
    import sys

    cmd = [
        sys.executable, "-m", "yt_dlp",
        "--skip-download",
        "--quiet",
        "--no-warnings",
        "--print", "%(id)s %(upload_date)s",
        "--playlist-end", str(max_videos),
        channel_url + "/videos",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
    if result.returncode != 0 and not result.stdout:
        raise RuntimeError(f"yt-dlp error: {result.stderr[:300]}")

    dates: dict[str, str] = {}
    for line in result.stdout.splitlines():
        parts = line.strip().split()
        if len(parts) == 2:
            vid, upload_date = parts
            if upload_date != "NA" and len(upload_date) == 8:
                dates[vid] = f"{upload_date[:4]}-{upload_date[4:6]}-{upload_date[6:8]}"
    return dates


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
                yt_id = getattr(rule, "channel_id", None)
                if yt_id and yt_id.startswith("UC"):
                    print(f"[{channel.id}] TranscriptAPI failed ({e}), trying RSS fallback")
                    fetched = await _fetch_from_rss(
                        channel.id,
                        channel.name,
                        yt_id,
                        last_n=getattr(rule, "last_n", 15) or 15,
                    )
                else:
                    print(f"[{channel.id}] TranscriptAPI failed, RSS fallback unavailable (missing channel_id): {e}")
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

        # Aggiorna dates cache con le date di TUTTI i video fetchati (non solo i nuovi)
        dates_path = video_dates_cache_path(root)
        dates_cache: dict[str, str] = read_json_or_default(dates_path, default={}) or {}
        for v in fetched:
            if v.published_at:
                dates_cache[v.video_id] = v.published_at
        write_json(dates_path, dates_cache)

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


def _normalize_date(value: str | None) -> str | None:
    """Returns first 10 chars (YYYY-MM-DD) of a date string, or None if unparseable."""
    if not value:
        return None
    s = str(value).strip()
    # Must start with 4-digit year to be a real ISO date
    if len(s) >= 10 and s[4] == "-" and s[7] == "-":
        return s[:10]
    return None


async def _fetch_since_cutoff(
    rule: "FetchRuleTranscriptApi",
    client: TranscriptClient,
    cutoff_date: str | None,
) -> list[dict]:
    """Fetch raw API video dicts published strictly AFTER cutoff_date.

    Paginates until a page returns only videos on/before the cutoff, or runs out of pages.
    If cutoff_date is None, falls back to fetching last_n videos (same as before).
    Returns raw dicts (unfiltered, without existing-check) so the caller can apply filters.
    """
    channel_input = rule.channel_url or rule.channel_id
    if not channel_input:
        return []

    if cutoff_date is None:
        # No cutoff info: just collect last_n as usual
        last_n = rule.last_n or 15
        videos: list[dict] = []
        continuation: str | None = None
        while len(videos) < last_n:
            page = await client.get_channel_videos(
                channel=channel_input if not continuation else None,
                continuation=continuation,
            )
            videos.extend(page.get("results", []))
            continuation = page.get("continuation_token")
            if not continuation or not page.get("has_more"):
                break
        return videos[:last_n]

    # Date-based fetch: go page by page until we hit the cutoff
    cutoff_str = cutoff_date[:10]
    videos_since: list[dict] = []
    continuation = None
    MAX_PAGES = 30  # safety cap (~600 videos)

    for _ in range(MAX_PAGES):
        page = await client.get_channel_videos(
            channel=channel_input if not continuation else None,
            continuation=continuation,
        )
        results = page.get("results", [])
        if not results:
            break

        found_older = False
        for v in results:
            published = v.get("published") or v.get("published_at")
            pub_date = _normalize_date(published)

            if pub_date is not None:
                if pub_date <= cutoff_str:
                    # This video is as old as (or older than) the last known
                    found_older = True
                    continue  # skip, but keep scanning this page for any newer ones
            # Include: either newer than cutoff, or date unparseable (conservative)
            videos_since.append(v)

        if found_older:
            # This page had old videos → we've gone back far enough; don't fetch more pages
            break

        continuation = page.get("continuation_token")
        if not continuation or not page.get("has_more"):
            break

    return videos_since


async def run_fetch_since_last_video(root: Path, transcript_api_key: str) -> PendingResult:
    """Fetch videos published AFTER the most recent video already in each channel's list.

    Uses date-based pagination — unlike run_fetch_new_videos (which caps at last_n),
    this will fetch as many pages as needed to capture every video since the last sync.
    """
    config_path = channels_config_path(root)
    raw = read_json(config_path)
    config = ChannelsConfig.model_validate(raw)

    channels = sorted(
        [c for c in config.channels if c.fetch_rule and c.fetch_rule.type != "manual"],
        key=lambda c: c.order,
    )

    dates_path = video_dates_cache_path(root)
    dates_cache: dict[str, str] = read_json_or_default(dates_path, default={}) or {}

    client = TranscriptClient(transcript_api_key)
    all_new: list[PendingVideo] = []

    for channel in channels:
        rule = channel.fetch_rule
        if rule is None:
            continue
        existing = _get_existing_ids(root, channel.video_list)

        # Cutoff = most recent YYYY-MM-DD date among videos already in the channel list
        channel_dates = [
            nd
            for vid in existing
            if vid in dates_cache and (nd := _normalize_date(dates_cache[vid]))
        ]
        cutoff_date: str | None = max(channel_dates) if channel_dates else None
        print(f"[{channel.id}] since_last: cutoff={cutoff_date}, existing={len(existing)}")

        fetched_raw: list[dict] = []

        if rule.type == "transcript_api":
            try:
                fetched_raw = await _fetch_since_cutoff(rule, client, cutoff_date)
            except (TranscriptAPIError, Exception) as e:
                print(f"[{channel.id}] fetch_since_cutoff failed ({e}), skip")
                continue
        elif rule.type == "rss":
            yt_id = getattr(rule, "channel_id", None)
            if yt_id and yt_id.startswith("UC"):
                all_rss = await _fetch_from_rss(
                    channel.id, channel.name, yt_id,
                    last_n=getattr(rule, "last_n", 50) or 50,
                )
                # Filter by date if we have a cutoff
                if cutoff_date:
                    cut_str = cutoff_date[:10]
                    all_rss = [
                        v for v in all_rss
                        if (_normalize_date(v.published_at) or "") > cut_str
                    ]
                fetched_raw = []  # already PendingVideo objects; handle below
                # Re-use existing filter + new logic
                new_rss = [v for v in all_rss if v.video_id not in existing]
                all_new.extend(new_rss)
                for v in all_rss:
                    if v.published_at:
                        dates_cache[v.video_id] = v.published_at
                print(f"[{channel.id}] rss: {len(all_rss)} since cutoff, {len(new_rss)} new")
                continue
            else:
                print(f"[{channel.id}] RSS rule requires channel_id (UC...), skip")
                continue
        else:
            continue

        # Build PendingVideo list from raw dicts
        pending: list[PendingVideo] = []
        for v in fetched_raw:
            vid = v.get("videoId") or _extract_video_id(v.get("url", ""))
            if not vid:
                continue
            pending.append(PendingVideo(
                video_id=vid,
                title=v.get("title", ""),
                channel_id=channel.id,
                channel_name=channel.name,
                url=f"https://www.youtube.com/watch?v={vid}",
                published_at=v.get("published") or v.get("published_at"),
            ))

        # Apply rule filters
        if hasattr(rule, "title_contains") and rule.title_contains:
            needle = rule.title_contains.lower()
            pending = [v for v in pending if needle in v.title.lower()]

        exclude = getattr(rule, "exclude_title_contains", None)
        if exclude:
            excl_lower = exclude.lower()
            pending = [v for v in pending if excl_lower not in v.title.lower()]

        if getattr(rule, "exclude_live", False):
            pending = [v for v in pending if not _LIVE_RE.search(v.title)]

        # Keep only videos not already in the channel list
        new_videos = [v for v in pending if v.video_id not in existing]
        all_new.extend(new_videos)
        print(f"[{channel.id}] {len(pending)} since cutoff, {len(new_videos)} new")

        # Update dates cache
        for v in pending:
            if v.published_at:
                dates_cache[v.video_id] = v.published_at

    write_json(dates_path, dates_cache)

    result = PendingResult(
        fetched_at=datetime.now(timezone.utc),
        items=all_new,
    )
    write_json(pending_path(root), result.model_dump(mode="json"))
    print(f"Wrote pending.json with {len(all_new)} recent new videos")
    return result
