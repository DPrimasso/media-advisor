"""run-from-list: fetch transcripts + analyze all videos in channel lists.

Porting of src/run-from-list.ts.
"""

import asyncio
import re
from dataclasses import dataclass, field
from pathlib import Path

from media_advisor.io.json_io import read_json, read_video_list, write_json
from media_advisor.io.paths import analysis_path, channels_config_path, transcript_path
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
    openai_api_key: str,
    channel_id: str | None = None,
    force_transcript: bool = False,
    force_analyze: bool = False,
    model: str = "gpt-4o-mini",
    transcript_only: bool = False,
) -> RunFromListResult:
    config_raw = read_json(channels_config_path(root))
    config = ChannelsConfig.model_validate(config_raw)

    channels = sorted(config.channels, key=lambda c: c.order)
    if channel_id:
        channels = [c for c in channels if c.id == channel_id]
        if not channels:
            raise ValueError(f"Channel '{channel_id}' not found")

    transcript_client = TranscriptClient(transcript_api_key)
    result = RunFromListResult()

    for channel in channels:
        ch_result = ChannelResult(id=channel.id)
        list_path = root / "channels" / channel.video_list
        urls = read_video_list(list_path)
        print(f"[{channel.id}] start: videos={len(urls)}", flush=True)

        for url in urls:
            vid = _extract_video_id(url)
            if not vid:
                continue

            t_path = transcript_path(root, channel.id, vid)
            a_path = analysis_path(root, channel.id, vid)

            # -- Transcript step --
            if t_path.exists() and not force_transcript:
                print(f"  [{channel.id}/{vid}] transcript: cached", flush=True)
                raw_transcript = read_json(t_path)
            else:
                try:
                    print(f"  [{channel.id}/{vid}] transcript: fetching...", flush=True)
                    transcript = await transcript_client.get_transcript(
                        url, format="json", include_timestamp=True, send_metadata=True
                    )
                    raw_transcript = transcript.model_dump(mode="json")
                    t_path.parent.mkdir(parents=True, exist_ok=True)
                    write_json(t_path, raw_transcript)
                    ch_result.transcripts_fetched += 1
                    print(f"  [{channel.id}/{vid}] transcript: saved -> {t_path}", flush=True)
                    await asyncio.sleep(RATE_LIMIT_SECONDS)
                except TranscriptAPIError as e:
                    print(f"  [{channel.id}/{vid}] Transcript failed: {e}")
                    ch_result.failed += 1
                    continue
                except Exception as e:
                    print(f"  [{channel.id}/{vid}] Transcript error: {e}")
                    ch_result.failed += 1
                    continue

            # -- Analysis step --
            if transcript_only:
                ch_result.skipped += 1
                continue
            if a_path.exists() and not force_analyze:
                print(f"  [{channel.id}/{vid}] analysis: cached (skip)", flush=True)
                ch_result.skipped += 1
                continue

            try:
                from media_advisor.models.transcript import TranscriptResponse

                transcript_obj = TranscriptResponse.model_validate(raw_transcript)
                meta = {}
                if transcript_obj.metadata:
                    meta = {
                        "title": transcript_obj.metadata.title,
                        "published_at": transcript_obj.metadata.published_at,
                    }

                print(f"  [{channel.id}/{vid}] analysis: running (model={model})...", flush=True)
                analysis = await analyze_video_v2(
                    data=transcript_obj,
                    video_id=vid,
                    channel_id=channel.id,
                    api_key=openai_api_key,
                    model=model,
                    metadata=meta,
                )
                a_path.parent.mkdir(parents=True, exist_ok=True)
                write_json(a_path, analysis.model_dump(mode="json"))
                ch_result.analyzed += 1
                print(f"  [{channel.id}/{vid}] analysis: saved -> {a_path}", flush=True)
                await asyncio.sleep(RATE_LIMIT_SECONDS)
            except Exception as e:
                print(f"  [{channel.id}/{vid}] Analysis failed: {e}")
                ch_result.failed += 1

        print(
            f"[{channel.id}] transcripts={ch_result.transcripts_fetched} "
            f"analyzed={ch_result.analyzed} skipped={ch_result.skipped} failed={ch_result.failed}"
        )
        result.channels.append(ch_result)

    return result
