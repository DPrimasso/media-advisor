"""CLI entry point — Typer app.

Comandi:
  run-list       Transcript + analisi per tutti i video nelle liste canale
  auto-update    Fetch -> merge -> pipeline (tutto automatico)
  fetch-now      Scarica nuovi video da channels con fetch_rule -> pending.json
  confirm        Approva video da pending.json (append a lista canale + rimuove da pending)
  transcript     Scarica/mostra transcript di un singolo video
  analyze        Analizza un singolo video (già trascritto)

Richiede TRANSCRIPT_API_KEY e OPENAI_API_KEY in .env o env vars.
"""

import asyncio
from pathlib import Path
from typing import Optional

import typer

from media_advisor.config import Settings

app = typer.Typer(help="Media Advisor CLI (Python rewrite)")

_settings: Settings | None = None


def _get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


def _root() -> Path:
    return _get_settings().root_dir.resolve()


# ---------------------------------------------------------------------------
# run-list
# ---------------------------------------------------------------------------


@app.command("run-list")
def cmd_run_list(
    channel: Optional[str] = typer.Option(None, "--channel", help="Process only this channel id"),
    force_transcript: bool = typer.Option(False, "--force-transcript", help="Re-fetch transcripts"),
    force_analyze: bool = typer.Option(False, "--force-analyze", help="Re-analyze existing"),
    from_pending: bool = typer.Option(
        False, "--from-pending", help="Merge pending.json into lists before running"
    ),
    model: str = typer.Option("gpt-4o-mini", "--model", help="LLM model for extraction"),
) -> None:
    """Fetch transcripts + analyze all videos in channel video lists."""
    s = _get_settings()
    if not s.transcript_api_key:
        typer.echo("Error: TRANSCRIPT_API_KEY not set", err=True)
        raise typer.Exit(1)
    if not s.openai_api_key:
        typer.echo("Error: OPENAI_API_KEY not set", err=True)
        raise typer.Exit(1)

    root = _root()

    if from_pending:
        from media_advisor.merge import merge_pending_into_channels

        added = merge_pending_into_channels(root)
        typer.echo(f"[merge] Added {added} videos from pending")

    from media_advisor.run_pipeline import run_from_list

    result = asyncio.run(
        run_from_list(
            root=root,
            transcript_api_key=s.transcript_api_key,
            openai_api_key=s.openai_api_key,
            channel_id=channel,
            force_transcript=force_transcript,
            force_analyze=force_analyze,
            model=model,
        )
    )

    total_analyzed = sum(c.analyzed for c in result.channels)
    total_failed = sum(c.failed for c in result.channels)
    typer.echo(f"Done. analyzed={total_analyzed} failed={total_failed}")


# ---------------------------------------------------------------------------
# fetch-now
# ---------------------------------------------------------------------------


@app.command("fetch-now")
def cmd_fetch_now() -> None:
    """Fetch new videos from channels (fetch rules) -> write pending.json."""
    s = _get_settings()
    if not s.transcript_api_key:
        typer.echo("Error: TRANSCRIPT_API_KEY not set", err=True)
        raise typer.Exit(1)

    from media_advisor.fetch import run_fetch_new_videos

    result = asyncio.run(run_fetch_new_videos(_root(), s.transcript_api_key))
    typer.echo(f"Fetched {len(result.items)} new videos -> pending.json")


# ---------------------------------------------------------------------------
# auto-update
# ---------------------------------------------------------------------------


@app.command("auto-update")
def cmd_auto_update(
    channel: Optional[str] = typer.Option(None, "--channel", help="Limit to one channel"),
    model: str = typer.Option("gpt-4o-mini", "--model"),
) -> None:
    """Fetch -> merge -> pipeline (fully automated, no manual Inbox step)."""
    s = _get_settings()
    if not s.transcript_api_key:
        typer.echo("Error: TRANSCRIPT_API_KEY not set", err=True)
        raise typer.Exit(1)
    if not s.openai_api_key:
        typer.echo("Error: OPENAI_API_KEY not set", err=True)
        raise typer.Exit(1)

    root = _root()

    typer.echo("[auto-update] Step 1: Fetching new videos...")
    from media_advisor.fetch import run_fetch_new_videos

    pending = asyncio.run(run_fetch_new_videos(root, s.transcript_api_key))

    if not pending.items:
        typer.echo("[auto-update] No new videos. Nothing to do.")
        return

    typer.echo(f"[auto-update] Step 2: Merging {len(pending.items)} videos into lists...")
    from media_advisor.merge import merge_pending_into_channels

    added = merge_pending_into_channels(root)
    typer.echo(f"[auto-update] Added {added} videos")

    typer.echo("[auto-update] Step 3: Running pipeline...")
    from media_advisor.run_pipeline import run_from_list

    result = asyncio.run(
        run_from_list(
            root=root,
            transcript_api_key=s.transcript_api_key,
            openai_api_key=s.openai_api_key,
            channel_id=channel,
            model=model,
        )
    )

    for ch in result.channels:
        typer.echo(
            f"  [{ch.id}] transcripts={ch.transcripts_fetched} "
            f"analyzed={ch.analyzed} skipped={ch.skipped} failed={ch.failed}"
        )
    typer.echo("[auto-update] Done.")


# ---------------------------------------------------------------------------
# confirm
# ---------------------------------------------------------------------------


@app.command("confirm")
def cmd_confirm(
    video_id: str = typer.Argument(..., help="Video ID to confirm from pending"),
) -> None:
    """Confirm a video from pending.json: append to channel list and remove from pending."""
    root = _root()

    from media_advisor.io.json_io import read_json, write_json
    from media_advisor.io.paths import channels_config_path, channel_list_path, pending_path
    from media_advisor.models.channels import ChannelsConfig
    from media_advisor.models.pending import PendingResult

    ppath = pending_path(root)
    if not ppath.exists():
        typer.echo("pending.json not found", err=True)
        raise typer.Exit(1)

    pending = PendingResult.model_validate(read_json(ppath))
    item = next((v for v in pending.items if v.video_id == video_id), None)
    if not item:
        typer.echo(f"Video {video_id} not found in pending.json", err=True)
        raise typer.Exit(1)

    config = ChannelsConfig.model_validate(read_json(channels_config_path(root)))
    channel = next((c for c in config.channels if c.id == item.channel_id), None)
    if not channel:
        typer.echo(f"Channel {item.channel_id} not found in channels.json", err=True)
        raise typer.Exit(1)

    list_path = channel_list_path(root, channel.video_list)
    from media_advisor.io.json_io import read_video_list, write_video_list

    urls = read_video_list(list_path)
    url = f"https://www.youtube.com/watch?v={video_id}"
    if url not in urls:
        urls.append(url)
        write_video_list(list_path, urls)
        typer.echo(f"Added {video_id} to {channel.video_list}")

    pending.items = [v for v in pending.items if v.video_id != video_id]
    write_json(ppath, pending.model_dump(mode="json"))
    typer.echo(f"Removed {video_id} from pending.json")


# ---------------------------------------------------------------------------
# transcript
# ---------------------------------------------------------------------------


@app.command("transcript")
def cmd_transcript(
    video: str = typer.Argument(..., help="YouTube URL or video ID"),
    channel: Optional[str] = typer.Option(None, "--channel", help="Channel id for storage path"),
    output: Optional[Path] = typer.Option(None, "--output", "-o", help="Output JSON path"),
    show: bool = typer.Option(False, "--show", help="Print transcript text to stdout"),
) -> None:
    """Fetch and save transcript for a single video."""
    s = _get_settings()
    if not s.transcript_api_key:
        typer.echo("Error: TRANSCRIPT_API_KEY not set", err=True)
        raise typer.Exit(1)

    from media_advisor.transcript_api.client import TranscriptClient

    async def _run() -> None:
        client = TranscriptClient(s.transcript_api_key)
        transcript = await client.get_transcript(video, include_timestamp=True, send_metadata=True)

        dest = output
        if dest is None and channel:
            import re as _re

            m = _re.search(r"(?:v=)([a-zA-Z0-9_-]{11})", video)
            vid = m.group(1) if m else (video if len(video) == 11 else None)
            if vid:
                from media_advisor.io.paths import transcript_path

                dest = transcript_path(_root(), channel, vid)

        if dest:
            from media_advisor.io.json_io import write_json

            write_json(dest, transcript.model_dump(mode="json"))
            typer.echo(f"Saved transcript to {dest}")

        if show:
            if isinstance(transcript.transcript, list):
                typer.echo(" ".join(s.text for s in transcript.transcript))
            else:
                typer.echo(transcript.transcript)

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# analyze
# ---------------------------------------------------------------------------


@app.command("analyze")
def cmd_analyze(
    video_id: str = typer.Argument(..., help="Video ID"),
    channel: str = typer.Option(..., "--channel", help="Channel id"),
    model: str = typer.Option("gpt-4o-mini", "--model"),
    force: bool = typer.Option(False, "--force", help="Re-analyze even if analysis exists"),
) -> None:
    """Analyze a single video (transcript must already be saved)."""
    s = _get_settings()
    if not s.openai_api_key:
        typer.echo("Error: OPENAI_API_KEY not set", err=True)
        raise typer.Exit(1)

    root = _root()
    from media_advisor.io.json_io import read_json, write_json
    from media_advisor.io.paths import analysis_path, transcript_path
    from media_advisor.models.transcript import TranscriptResponse
    from media_advisor.pipeline.analyze_v2 import analyze_video_v2

    t_path = transcript_path(root, channel, video_id)
    a_path = analysis_path(root, channel, video_id)

    if not t_path.exists():
        typer.echo(f"Transcript not found: {t_path}", err=True)
        raise typer.Exit(1)

    if a_path.exists() and not force:
        typer.echo(f"Analysis already exists: {a_path} (use --force to re-analyze)")
        return

    async def _run() -> None:
        transcript = TranscriptResponse.model_validate(read_json(t_path))
        meta = {}
        if transcript.metadata:
            meta = {
                "title": transcript.metadata.title,
                "published_at": transcript.metadata.published_at,
            }
        analysis = await analyze_video_v2(
            data=transcript,
            video_id=video_id,
            channel_id=channel,
            api_key=s.openai_api_key,
            model=model,
            metadata=meta,
        )
        a_path.parent.mkdir(parents=True, exist_ok=True)
        write_json(a_path, analysis.model_dump(mode="json"))
        typer.echo(f"Analysis saved to {a_path}")
        typer.echo(f"Claims: {len(analysis.claims or [])}  Topics: {len(analysis.topics)}")

    asyncio.run(_run())


if __name__ == "__main__":
    app()
