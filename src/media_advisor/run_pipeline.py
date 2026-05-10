"""run-from-list: fetch transcripts + analyze all videos in channel lists.

Porting of src/run-from-list.ts.
"""

import asyncio
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from media_advisor.db.repository import analysis_existing_pair_keys, upsert_video_analysis
from media_advisor.db.session import session_scope
from media_advisor.io.channel_store import load_channels_config_dict, load_video_dates_dict, read_channel_video_urls
from media_advisor.io.transcript_storage import load_transcript_dict, save_transcript_to_store
from media_advisor.models.channels import ChannelsConfig
from media_advisor.pipeline.analyze_v2 import analyze_video_v2
from media_advisor.transcript_api.client import TranscriptAPIError, TranscriptClient

RATE_LIMIT_SECONDS = 0.5
_VID_RE = re.compile(r"(?:v=)([a-zA-Z0-9_-]{11})")


def _extract_video_id(url_or_id: str) -> str | None:
    m = _VID_RE.search(url_or_id)
    if m:
        return m.group(1)
    if len(url_or_id) == 11:
        return url_or_id
    return None


@dataclass
class ChannelResult:
    id: str
    transcripts_fetched: int = 0
    analyzed: int = 0
    skipped: int = 0
    failed: int = 0


@dataclass
class RunFromListResult:
    channels: list[ChannelResult] = field(default_factory=list)


async def run_from_list(
    root: Path,
    transcript_api_key: str,
    api_key: str,
    channel_id: str | None = None,
    force_transcript: bool = False,
    force_analyze: bool = False,
    model: str = "gpt-4.1-mini",
    transcript_only: bool = False,
    only_video_ids: set[str] | None = None,
    progress_callback: Callable[[str, str], None] | None = None,
    base_url: str | None = None,
    # backward compat alias — callers that still pass openai_api_key= by keyword are redirected
    openai_api_key: str | None = None,
) -> RunFromListResult:
    if openai_api_key is not None and not api_key:
        api_key = openai_api_key
    config_raw = load_channels_config_dict(root)
    config = ChannelsConfig.model_validate(config_raw)

    channels = sorted(config.channels, key=lambda c: c.order)
    if channel_id:
        channels = [c for c in channels if c.id == channel_id]
        if not channels:
            raise ValueError(f"Channel '{channel_id}' not found")

    transcript_client = TranscriptClient(transcript_api_key)
    result = RunFromListResult()
    _progress = progress_callback or (lambda *_: None)
    dates_cache: dict[str, str] = load_video_dates_dict(root)

    for channel in channels:
        ch_result = ChannelResult(id=channel.id)
        urls = read_channel_video_urls(root, channel.video_list)
        print(f"[{channel.id}] start: videos={len(urls)}", flush=True)

        work: list[tuple[str, str]] = []
        for url in urls:
            vid = _extract_video_id(url)
            if not vid:
                continue
            if only_video_ids is not None and vid not in only_video_ids:
                continue
            work.append((url, vid))

        with session_scope(root, read_only=True) as session:
            have_analysis = analysis_existing_pair_keys(session, [(vid, channel.id) for _, vid in work])

        for url, vid in work:
            # -- Transcript step --
            raw_transcript: dict | None = None
            if not force_transcript:
                raw_transcript = load_transcript_dict(root, channel.id, vid)
                if raw_transcript is not None:
                    print(f"  [{channel.id}/{vid}] transcript: cached", flush=True)

            if raw_transcript is None or force_transcript:
                try:
                    print(f"  [{channel.id}/{vid}] transcript: fetching...", flush=True)
                    transcript = await transcript_client.get_transcript(
                        url, format="json", include_timestamp=True, send_metadata=True
                    )
                    raw_transcript = transcript.model_dump(mode="json")
                    save_transcript_to_store(root, channel.id, vid, raw_transcript)
                    ch_result.transcripts_fetched += 1
                    print(f"  [{channel.id}/{vid}] transcript: saved (db)", flush=True)
                    await asyncio.sleep(RATE_LIMIT_SECONDS)
                except TranscriptAPIError as e:
                    print(f"  [{channel.id}/{vid}] Transcript failed: {e}")
                    ch_result.failed += 1
                    _progress(channel.id, vid)
                    continue
                except Exception as e:
                    print(f"  [{channel.id}/{vid}] Transcript error: {e}")
                    ch_result.failed += 1
                    _progress(channel.id, vid)
                    continue

            # -- Analysis step --
            if transcript_only:
                ch_result.skipped += 1
                _progress(channel.id, vid)
                continue
            if (channel.id, vid) in have_analysis and not force_analyze:
                print(f"  [{channel.id}/{vid}] analysis: cached (skip)", flush=True)
                ch_result.skipped += 1
                _progress(channel.id, vid)
                continue

            try:
                from media_advisor.models.transcript import TranscriptResponse

                transcript_obj = TranscriptResponse.model_validate(raw_transcript)
                meta = {}
                if transcript_obj.metadata:
                    pub = transcript_obj.metadata.published_at or dates_cache.get(vid)
                    meta = {
                        "title": transcript_obj.metadata.title,
                        "published_at": pub,
                    }

                print(f"  [{channel.id}/{vid}] analysis: running (model={model})...", flush=True)
                analysis = await analyze_video_v2(
                    data=transcript_obj,
                    video_id=vid,
                    channel_id=channel.id,
                    api_key=api_key,
                    model=model,
                    metadata=meta,
                    base_url=base_url,
                )
                with session_scope(root) as session:
                    upsert_video_analysis(session, channel.id, vid, analysis.model_dump(mode="json"))
                ch_result.analyzed += 1
                print(f"  [{channel.id}/{vid}] analysis: saved (db)", flush=True)
                _progress(channel.id, vid)
                await asyncio.sleep(RATE_LIMIT_SECONDS)
            except Exception as e:
                print(f"  [{channel.id}/{vid}] Analysis failed: {e}")
                ch_result.failed += 1
                _progress(channel.id, vid)

        print(
            f"[{channel.id}] transcripts={ch_result.transcripts_fetched} "
            f"analyzed={ch_result.analyzed} skipped={ch_result.skipped} failed={ch_result.failed}"
        )
        result.channels.append(ch_result)

    return result
