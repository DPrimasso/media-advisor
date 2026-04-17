"""TranscriptAPI.com async client — porting of src/transcript-client.ts.

Uses httpx with exponential backoff on retryable status codes (408, 429, 503).
Falls back to youtube-transcript-api (free) when the paid plan is unavailable.
"""

import asyncio
import re
from typing import Any

import httpx

from media_advisor.models.transcript import TranscriptResponse, TranscriptSegment, VideoMetadata

BASE_URL = "https://transcriptapi.com/api/v2"
RETRYABLE_CODES = {408, 429, 503}

# Error substrings that indicate the paid plan is inactive (not a transient error).
_PLAN_ERROR_SIGNALS = ("paid plan", "active plan", "subscription", "quota", "credits")


def _extract_video_id(video_url_or_id: str) -> str:
    """Extract YouTube video ID from a URL or return as-is if already an ID."""
    # Match ?v=ID or youtu.be/ID patterns
    m = re.search(r"(?:v=|youtu\.be/)([A-Za-z0-9_-]{11})", video_url_or_id)
    if m:
        return m.group(1)
    # Assume it's already an ID if it looks like one
    if re.fullmatch(r"[A-Za-z0-9_-]{11}", video_url_or_id.strip()):
        return video_url_or_id.strip()
    return video_url_or_id


async def _fetch_via_yt_transcript_api(video_id: str) -> TranscriptResponse:
    """Fallback: fetch transcript using the free youtube-transcript-api library."""
    loop = asyncio.get_event_loop()

    def _sync_fetch() -> list[dict]:
        from youtube_transcript_api import YouTubeTranscriptApi  # type: ignore[import-untyped]
        api = YouTubeTranscriptApi()
        fetched = api.fetch(video_id, languages=["it", "en"])
        return [{"text": s.text, "start": s.start, "duration": s.duration} for s in fetched.snippets]

    snippets = await loop.run_in_executor(None, _sync_fetch)
    segments = [TranscriptSegment(**s) for s in snippets]
    return TranscriptResponse(
        video_id=video_id,
        language="it",
        transcript=segments,
        metadata=None,
    )


class TranscriptAPIError(Exception):
    def __init__(
        self,
        message: str,
        status_code: int | None = None,
        code: str | None = None,
        action_url: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.action_url = action_url


def _extract_error(body: Any, fallback: str) -> tuple[str, str | None]:
    """Return (message, action_url) from an error response body."""
    detail = body.get("detail") if isinstance(body, dict) else None
    if isinstance(detail, dict):
        return detail.get("message") or str(detail), detail.get("action_url")
    if isinstance(detail, str):
        return detail, None
    return fallback, None


class TranscriptClient:
    """Async wrapper around TranscriptAPI.com REST endpoints."""

    def __init__(
        self,
        api_key: str,
        base_url: str = BASE_URL,
        max_retries: int = 3,
        timeout: float = 60.0,
    ) -> None:
        self._headers = {"Authorization": f"Bearer {api_key}"}
        self._base_url = base_url.rstrip("/")
        self._max_retries = max_retries
        self._timeout = timeout

    async def _get(self, path: str, params: dict[str, str]) -> Any:
        url = f"{self._base_url}{path}"
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            for attempt in range(self._max_retries):
                resp = await client.get(url, params=params, headers=self._headers)
                if resp.status_code not in RETRYABLE_CODES:
                    return resp
                if attempt == self._max_retries - 1:
                    return resp
                retry_after_header = resp.headers.get("Retry-After")
                wait = float(retry_after_header) if retry_after_header else 2**attempt
                await asyncio.sleep(wait)
        raise TranscriptAPIError("Max retries exceeded")

    async def get_transcript(
        self,
        video_url_or_id: str,
        format: str = "json",
        include_timestamp: bool = True,
        send_metadata: bool = True,
    ) -> TranscriptResponse:
        params = {
            "video_url": video_url_or_id,
            "format": format,
            "include_timestamp": str(include_timestamp).lower(),
            "send_metadata": str(send_metadata).lower(),
        }
        resp = await self._get("/youtube/transcript", params)
        if not resp.is_success:
            body = resp.json() if resp.content else {}
            msg, action_url = _extract_error(body, resp.reason_phrase or str(resp.status_code))
            code = body.get("code") if isinstance(body, dict) else None
            # If the paid plan is not active, fall back to the free youtube-transcript-api.
            if any(sig in msg.lower() for sig in _PLAN_ERROR_SIGNALS):
                try:
                    vid = _extract_video_id(video_url_or_id)
                    return await _fetch_via_yt_transcript_api(vid)
                except Exception as fb_err:
                    raise TranscriptAPIError(
                        f"{msg} (fallback also failed: {fb_err})", resp.status_code, code, action_url
                    ) from fb_err
            raise TranscriptAPIError(msg, resp.status_code, code, action_url)
        return TranscriptResponse.model_validate(resp.json())

    async def get_channel_videos(
        self,
        channel: str | None = None,
        continuation: str | None = None,
    ) -> dict[str, Any]:
        if not channel and not continuation:
            raise TranscriptAPIError("Provide channel or continuation")
        params: dict[str, str] = {}
        if channel:
            params["channel"] = channel
        else:
            params["continuation"] = continuation  # type: ignore[assignment]
        resp = await self._get("/youtube/channel/videos", params)
        if not resp.is_success:
            body = resp.json() if resp.content else {}
            msg, _ = _extract_error(body, resp.reason_phrase or str(resp.status_code))
            raise TranscriptAPIError(msg, resp.status_code)
        return resp.json()  # type: ignore[no-any-return]

    async def get_channel_search(
        self,
        channel: str,
        query: str,
        limit: int = 50,
    ) -> dict[str, Any]:
        params = {"channel": channel, "q": query, "limit": str(min(50, limit))}
        resp = await self._get("/youtube/channel/search", params)
        if not resp.is_success:
            body = resp.json() if resp.content else {}
            msg, _ = _extract_error(body, resp.reason_phrase or str(resp.status_code))
            raise TranscriptAPIError(msg, resp.status_code)
        return resp.json()  # type: ignore[no-any-return]

    async def get_channel_latest(self, channel: str) -> dict[str, Any]:
        """Get latest ~15 videos from a channel (FREE, no credits). Returns published dates."""
        resp = await self._get("/youtube/channel/latest", {"channel": channel})
        if not resp.is_success:
            body = resp.json() if resp.content else {}
            msg, _ = _extract_error(body, resp.reason_phrase or str(resp.status_code))
            raise TranscriptAPIError(msg, resp.status_code)
        return resp.json()  # type: ignore[no-any-return]

    async def enrich_published_at(
        self,
        transcript: TranscriptResponse,
        channel_input: str,
    ) -> TranscriptResponse:
        """Attempt to fill transcript.metadata.published_at via channel/latest."""
        try:
            data = await self.get_channel_latest(channel_input)
            results = data.get("results", [])
            for item in results:
                if item.get("videoId") == transcript.video_id:
                    published = item.get("published")
                    if published and transcript.metadata:
                        return transcript.model_copy(
                            update={
                                "metadata": transcript.metadata.model_copy(
                                    update={"published_at": published}
                                )
                            }
                        )
                    break
        except Exception:
            pass
        return transcript
