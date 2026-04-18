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
import sys
from pathlib import Path
from typing import Optional

import typer

# Force UTF-8 output on Windows consoles to avoid cp1252 encoding errors
# when printing player names with special characters.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

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
    transcript_only: bool = typer.Option(False, "--transcript-only", help="Scarica solo i transcript, senza analisi GPT"),
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
            transcript_only=transcript_only,
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
    all_unanalyzed: bool = typer.Option(False, "--all", help="Analyze all unanalyzed videos, not just newly fetched ones"),
) -> None:
    """Fetch -> merge -> pipeline (fully automated, no manual Inbox step).

    By default analyzes only newly fetched videos. Use --all to catch up on
    all historically unanalyzed videos in every channel list.
    """
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

    new_ids = None if all_unanalyzed else {v.video_id for v in pending.items}
    if new_ids:
        typer.echo(f"[auto-update] Analyzing {len(new_ids)} newly fetched videos (use --all for full catch-up)")

    result = asyncio.run(
        run_from_list(
            root=root,
            transcript_api_key=s.transcript_api_key,
            openai_api_key=s.openai_api_key,
            channel_id=channel,
            model=model,
            only_video_ids=new_ids,
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


# ---------------------------------------------------------------------------
# Shared helpers for mercato commands
# ---------------------------------------------------------------------------


def _collect_tip_files(tips_root: Path, channel: Optional[str]) -> list[Path]:
    """Raccoglie tutti i file .json in mercato/tips/, opzionalmente filtrati per canale."""
    if channel:
        ch_dir = tips_root / channel
        return sorted(ch_dir.glob("*.json")) if ch_dir.exists() else []
    files: list[Path] = []
    for ch_dir in sorted(p for p in tips_root.iterdir() if p.is_dir()):
        files.extend(sorted(ch_dir.glob("*.json")))
    return files


# ---------------------------------------------------------------------------
# mercato-analyze
# ---------------------------------------------------------------------------


@app.command("mercato-analyze")
def cmd_mercato_analyze(
    video_id: str = typer.Argument(..., help="Video ID"),
    channel: str = typer.Option(..., "--channel", help="Channel id"),
    model: str = typer.Option("gpt-4o-mini", "--model"),
    force: bool = typer.Option(False, "--force", help="Re-analizza anche se già presente"),
) -> None:
    """Analizza un singolo video per indiscrezioni di mercato (transcript già salvato)."""
    s = _get_settings()
    if not s.transcript_api_key:
        typer.echo("Error: TRANSCRIPT_API_KEY not set", err=True)
        raise typer.Exit(1)
    if not s.openai_api_key:
        typer.echo("Error: OPENAI_API_KEY not set", err=True)
        raise typer.Exit(1)

    from media_advisor.mercato.analyzer import analyze_video_mercato
    from media_advisor.transcript_api.client import TranscriptClient
    from media_advisor.io.json_io import read_json, write_json
    from media_advisor.io.paths import transcript_path
    from media_advisor.models.transcript import TranscriptResponse, VideoMetadata
    from media_advisor.models.channels import ChannelsConfig

    def _get_channel_url(root) -> str | None:
        try:
            cfg = ChannelsConfig.model_validate(read_json(root / "channels" / "channels.json"))
            ch = next((c for c in cfg.channels if c.id == channel), None)
            return (ch.fetch_rule.channel_url if ch and ch.fetch_rule else None)  # type: ignore[attr-defined]
        except Exception:
            return None

    async def _ensure_transcript_metadata(root) -> None:
        t_path = transcript_path(root, channel, video_id)
        if not t_path.exists():
            return
        raw = read_json(t_path)
        tr = TranscriptResponse.model_validate(raw)
        if tr.metadata and tr.metadata.published_at:
            return

        channel_url = _get_channel_url(root)
        if not channel_url:
            return

        client = TranscriptClient(s.transcript_api_key)
        try:
            latest = await client.get_channel_latest(channel_url)
            results = latest.get("results", []) if isinstance(latest, dict) else []
            match = next((it for it in results if it.get("videoId") == tr.video_id), None)
            if not match:
                return
            published = match.get("published") or match.get("published_at")
            title = match.get("title")
            if not published and not title:
                return
            meta = tr.metadata or VideoMetadata()
            meta = meta.model_copy(
                update={
                    "published_at": published or meta.published_at,
                    "title": title or meta.title,
                }
            )
            tr2 = tr.model_copy(update={"metadata": meta})
            write_json(t_path, tr2.model_dump(mode="json"))
        except Exception:
            return

    async def _run() -> None:
        await _ensure_transcript_metadata(_root())
        result = await analyze_video_mercato(
            root=_root(),
            video_id=video_id,
            channel_id=channel,
            api_key=s.openai_api_key,
            model=model,
            force=force,
        )
        typer.echo(f"Tip trovate: {len(result.tips)}")
        for tip in result.tips:
            # Keep CLI output ASCII-safe on Windows consoles (cp1252).
            clubs = f"{tip.from_club or '?'} -> {tip.to_club or '?'}"
            typer.echo(f"  [{tip.confidence}] {tip.player_name} ({clubs}): {tip.tip_text}")

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# mercato-scan
# ---------------------------------------------------------------------------


@app.command("mercato-scan")
def cmd_mercato_scan(
    channel: Optional[str] = typer.Option(None, "--channel", help="Limita a un canale"),
    model: str = typer.Option("gpt-4o-mini", "--model"),
    force: bool = typer.Option(False, "--force", help="Re-analizza anche se già presente"),
    all_videos: bool = typer.Option(False, "--all-videos", help="Analizza tutti i video senza filtrare per keyword nel titolo"),
    from_date: Optional[str] = typer.Option(None, "--from-date", help="Filtra video pubblicati da questa data (YYYY-MM-DD)"),
    to_date: Optional[str] = typer.Option(None, "--to-date", help="Filtra video pubblicati fino a questa data (YYYY-MM-DD)"),
) -> None:
    """Scansiona i transcript già scaricati e analizza quelli con titolo mercato."""
    import re as _re
    from datetime import date as _date

    date_from: _date | None = _date.fromisoformat(from_date) if from_date else None
    date_to: _date | None = _date.fromisoformat(to_date) if to_date else None

    s = _get_settings()
    if not s.transcript_api_key:
        typer.echo("Error: TRANSCRIPT_API_KEY not set", err=True)
        raise typer.Exit(1)
    if not s.openai_api_key:
        typer.echo("Error: OPENAI_API_KEY not set", err=True)
        raise typer.Exit(1)

    root = _root()
    _MERCATO_KW = _re.compile(
        r"\b(mercato|trattativa|acquisto|cessione|rinnovo|accordo|trasferimento|prestito)\b",
        _re.IGNORECASE,
    )

    from media_advisor.io.json_io import read_json
    from media_advisor.mercato.analyzer import analyze_video_mercato
    from media_advisor.transcript_api.client import TranscriptClient
    from media_advisor.io.json_io import write_json
    from media_advisor.io.paths import transcript_path
    from media_advisor.models.transcript import TranscriptResponse, VideoMetadata
    from media_advisor.models.channels import ChannelsConfig

    transcripts_root = root / "data" / "transcripts"
    if not transcripts_root.exists():
        typer.echo("Nessun transcript trovato.")
        return

    channel_dirs = (
        [transcripts_root / channel] if channel else list(transcripts_root.iterdir())
    )

    async def _run() -> None:
        from media_advisor.io.json_io import read_json_or_default
        from media_advisor.io.paths import mercato_tips_path, video_dates_cache_path
        from media_advisor.mercato.analyzer import update_index_with_new_tips
        from media_advisor.mercato.models import MercatoTip

        # Cache latest results per channel (one API call per channel).
        latest_cache: dict[str, list[dict]] = {}
        # Dates cache persistente salvata da fetch-now
        _dates_cache: dict[str, str] = read_json_or_default(video_dates_cache_path(root), default={}) or {}

        _channels_cfg = ChannelsConfig.model_validate(read_json(root / "channels" / "channels.json"))
        _channels_map = {c.id: c for c in _channels_cfg.channels}

        def _get_channel_url(ch_id: str) -> str | None:
            try:
                ch = _channels_map.get(ch_id)
                return (ch.fetch_rule.channel_url if ch and ch.fetch_rule else None)  # type: ignore[attr-defined]
            except Exception:
                return None

        def _is_mercato_channel(ch_id: str) -> bool:
            ch = _channels_map.get(ch_id)
            return ch.mercato_channel if ch else False

        async def _ensure_metadata(ch_id: str, vid: str) -> None:
            t_path = transcript_path(root, ch_id, vid)
            if not t_path.exists():
                return
            raw = read_json(t_path)
            tr = TranscriptResponse.model_validate(raw)
            if tr.metadata and tr.metadata.published_at:
                return

            # 1. Prova la dates cache persistente (salvata da fetch-now)
            cached_date = _dates_cache.get(vid)
            if cached_date:
                meta = tr.metadata or VideoMetadata()
                meta = meta.model_copy(update={"published_at": cached_date})
                tr2 = tr.model_copy(update={"metadata": meta})
                write_json(t_path, tr2.model_dump(mode="json"))
                return

            # 2. Fallback: prova get_channel_latest (solo ~15 video recenti)
            channel_url = _get_channel_url(ch_id)
            if not channel_url:
                return
            if ch_id not in latest_cache:
                try:
                    client = TranscriptClient(s.transcript_api_key)
                    data = await client.get_channel_latest(channel_url)
                    latest_cache[ch_id] = data.get("results", []) if isinstance(data, dict) else []
                except Exception:
                    latest_cache[ch_id] = []  # non bloccare l'analisi per mancanza di metadata
            match = next((it for it in latest_cache[ch_id] if it.get("videoId") == tr.video_id), None)
            if not match:
                return
            published = match.get("published") or match.get("published_at")
            title = match.get("title")
            if not published and not title:
                return
            meta = tr.metadata or VideoMetadata()
            meta = meta.model_copy(
                update={
                    "published_at": published or meta.published_at,
                    "title": title or meta.title,
                }
            )
            tr2 = tr.model_copy(update={"metadata": meta})
            write_json(t_path, tr2.model_dump(mode="json"))

        total, analyzed, skipped = 0, 0, 0
        all_new_tips: list[MercatoTip] = []
        for ch_dir in channel_dirs:
            if not ch_dir.is_dir():
                continue
            ch_id = ch_dir.name
            is_mercato_ch = _is_mercato_channel(ch_id)
            # Canali non-mercato: salta sempre (no costo GPT su analisi partite)
            if not all_videos and not is_mercato_ch:
                n = sum(1 for _ in ch_dir.glob("*.json"))
                total += n
                skipped += n
                continue
            for t_file in sorted(ch_dir.glob("*.json")):
                vid = t_file.stem
                total += 1
                try:
                    data = read_json(t_file)
                    title = (data.get("metadata") or {}).get("title") or ""
                    # Canali mercato: analizza tutto; altri: filtra per keyword titolo
                    if not all_videos and not is_mercato_ch and not _MERCATO_KW.search(title):
                        skipped += 1
                        continue
                    await _ensure_metadata(ch_id, vid)
                    # Applica filtro data se specificato
                    if date_from or date_to:
                        data = read_json(t_file)  # rilegge per published_at aggiornata
                        pub_str = (data.get("metadata") or {}).get("published_at")
                        if not pub_str:
                            skipped += 1
                            continue  # data sconosciuta: salta quando filtro attivo
                        pub_d = _date.fromisoformat(pub_str[:10])
                        if date_from and pub_d < date_from:
                            skipped += 1
                            continue
                        if date_to and pub_d > date_to:
                            skipped += 1
                            continue
                    _tip_file_existed = mercato_tips_path(root, ch_id, vid).exists() and not force
                    result = await analyze_video_mercato(
                        root=root,
                        video_id=vid,
                        channel_id=ch_id,
                        api_key=s.openai_api_key,
                        model=model,
                        force=force,
                        update_index=False,  # batch: aggiorna index una sola volta alla fine
                    )
                    if not _tip_file_existed:
                        all_new_tips.extend(result.tips)
                    analyzed += 1
                    typer.echo(f"  [{ch_id}] {vid} — {len(result.tips)} tip ({title[:60]})")
                except Exception as exc:
                    typer.echo(f"  [ERR] {ch_id}/{vid}: {exc}", err=True)

        update_index_with_new_tips(root, all_new_tips)
        typer.echo(f"\nDone. totale={total} analizzati={analyzed} saltati(no-mercato)={skipped}")

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# mercato-outcome
# ---------------------------------------------------------------------------


@app.command("mercato-outcome")
def cmd_mercato_outcome(
    tip_id: str = typer.Argument(..., help="tip_id della tip da aggiornare"),
    outcome: str = typer.Argument(..., help="non_verificata | confermata | parziale | smentita | non_conclusa"),
    notes: Optional[str] = typer.Option(None, "--notes", help="Note sull'esito"),
) -> None:
    """Marca manualmente l'esito di un'indiscrezione di mercato."""
    from typing import cast

    from media_advisor.mercato.analyzer import update_tip_outcome
    from media_advisor.mercato.models import OutcomeValue

    valid: set[str] = {"non_verificata", "confermata", "parziale", "smentita", "non_conclusa"}
    if outcome not in valid:
        typer.echo(f"Outcome non valido: {outcome}. Usa: {' | '.join(sorted(valid))}", err=True)
        raise typer.Exit(1)

    try:
        update_tip_outcome(_root(), tip_id, cast(OutcomeValue, outcome), notes, source="manual")
        typer.echo(f"Tip {tip_id} aggiornata: outcome={outcome}")
    except FileNotFoundError as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(1)
    except KeyError as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(1)


# ---------------------------------------------------------------------------
# mercato-add-transfer
# ---------------------------------------------------------------------------


@app.command("mercato-add-transfer")
def cmd_mercato_add_transfer(
    player: str = typer.Option(..., "--player", help="Nome del giocatore"),
    to_club: str = typer.Option(..., "--to", help="Club di destinazione"),
    from_club: Optional[str] = typer.Option(None, "--from", help="Club di provenienza"),
    transfer_type: str = typer.Option("unknown", "--type", help="loan | permanent | free_agent | extension | unknown"),
    season: str = typer.Option(..., "--season", help="Stagione, es. 2025-26"),
    date: str = typer.Option(..., "--date", help="Data ufficialità (YYYY-MM-DD)"),
    url: Optional[str] = typer.Option(None, "--url", help="Link Transfermarkt"),
    notes: Optional[str] = typer.Option(None, "--notes", help="Note aggiuntive"),
) -> None:
    """Aggiunge un trasferimento ufficiale al database (inserimento manuale)."""
    from datetime import datetime, timezone

    from media_advisor.mercato.transfer_db import TransferRecord, add_transfer, player_slug as make_slug

    try:
        confirmed_at = datetime.strptime(date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        typer.echo("Formato data non valido. Usa YYYY-MM-DD (es. 2026-07-01)", err=True)
        raise typer.Exit(1)

    record = TransferRecord(
        player_name=player,
        player_slug=make_slug(player),
        from_club=from_club,
        to_club=to_club,
        transfer_type=transfer_type,  # type: ignore[arg-type]
        season=season,
        confirmed_at=confirmed_at,
        source="manual",
        source_url=url,
        notes=notes,
    )
    saved = add_transfer(_root(), record)
    typer.echo(f"OK Trasferimento aggiunto: {saved.player_name} -> {saved.to_club} ({saved.transfer_type})")

    # Verifica automatica
    from media_advisor.mercato.verifier import verify_all_pending
    updated = verify_all_pending(_root())
    if updated:
        typer.echo(f"  -> {len(updated)} tip aggiornate automaticamente:")
        for u in updated:
            typer.echo(f"    {u['player_name']} -> {u['to_club']}: {u['outcome']}")


# ---------------------------------------------------------------------------
# mercato-fetch-transfers
# ---------------------------------------------------------------------------


@app.command("mercato-fetch-transfers")
def cmd_mercato_fetch_transfers(
    player: str = typer.Option(..., "--player", help="Nome del giocatore da cercare su Transfermarkt"),
    season: Optional[str] = typer.Option(None, "--season", help="Filtro stagione es. 2025"),
) -> None:
    """Scarica i trasferimenti di un giocatore da Transfermarkt e li salva nel database."""
    from media_advisor.mercato.scraper import ScraperError, fetch_player_transfers
    from media_advisor.mercato.transfer_db import TransferRecord, add_transfer, get_all_transfers, player_slug as make_slug

    typer.echo(f"Cerco trasferimenti per '{player}' su Transfermarkt...")
    try:
        raw = fetch_player_transfers(player, season, root=_root())
    except ScraperError as e:
        typer.echo(f"Errore scraping: {e}", err=True)
        raise typer.Exit(1)

    if not raw:
        typer.echo("Nessun trasferimento trovato.")
        return

    existing = get_all_transfers(_root())
    existing_keys = {(t.player_slug, t.to_club or "", t.season) for t in existing}
    added_count = 0

    for item in raw:
        slug = make_slug(item["player_name"])
        key = (slug, item.get("to_club") or "", item.get("season", ""))
        if key in existing_keys:
            continue
        record = TransferRecord(
            player_name=item["player_name"],
            player_slug=slug,
            from_club=item.get("from_club"),
            to_club=item.get("to_club"),
            transfer_type=item.get("transfer_type", "unknown"),  # type: ignore[arg-type]
            season=item.get("season", ""),
            confirmed_at=item["confirmed_at"],
            source="transfermarkt",
            source_url=item.get("source_url"),
        )
        add_transfer(_root(), record)
        existing_keys.add(key)
        added_count += 1
        typer.echo(f"  + {record.player_name} -> {record.to_club} ({record.transfer_type}, {record.season})")

    typer.echo(f"\n{added_count} trasferimento/i aggiunto/i.")

    from media_advisor.mercato.verifier import verify_all_pending
    updated = verify_all_pending(_root())
    if updated:
        typer.echo(f"{len(updated)} tip aggiornate:")
        for u in updated:
            typer.echo(f"  {u['player_name']} -> {u['to_club']}: {u['outcome']}")


# ---------------------------------------------------------------------------
# mercato-import-season
# ---------------------------------------------------------------------------


@app.command("mercato-import-season")
def cmd_mercato_import_season(
    season: str = typer.Option(..., "--season", help="Anno di inizio stagione (es. 2025 per estate 2025 / 2025-26)"),
    from_date: Optional[str] = typer.Option(None, "--from-date", help="Considera solo tip pubblicate da questa data (YYYY-MM-DD)"),
    to_date: Optional[str] = typer.Option(None, "--to-date", help="Considera solo tip pubblicate fino a questa data (YYYY-MM-DD)"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Mostra cosa verrebbe importato senza salvare"),
) -> None:
    """Importa i trasferimenti ufficiali della stagione da Transfermarkt per tutti i giocatori nelle tip.

    Legge l'index globale, estrae i giocatori unici (opzionalmente filtrati per data),
    cerca i trasferimenti su Transfermarkt e popola mercato/transfers.json.
    Per i giocatori non trovati stampa un riepilogo da inserire manualmente via UI.
    """
    from datetime import date as _date

    from media_advisor.mercato.aggregator import load_index
    from media_advisor.mercato.scraper import ScraperError, fetch_player_transfers
    from media_advisor.mercato.transfer_db import TransferRecord, add_transfer, get_all_transfers, player_slug as make_slug

    date_from: _date | None = _date.fromisoformat(from_date) if from_date else None
    date_to: _date | None = _date.fromisoformat(to_date) if to_date else None

    root = _root()
    index = load_index(root)

    # Raccoglie giocatori unici dalle tip, con filtro opzionale per data
    player_names: dict[str, str] = {}  # player_slug -> player_name (canonico)
    for tip in index.tips:
        if date_from or date_to:
            if not tip.mentioned_at:
                continue
            pub_d = tip.mentioned_at.date()
            if date_from and pub_d < date_from:
                continue
            if date_to and pub_d > date_to:
                continue
        slug = make_slug(tip.player_name)
        if slug not in player_names:
            player_names[slug] = tip.player_name

    if not player_names:
        typer.echo("Nessun giocatore trovato nelle tip con i filtri applicati.")
        return

    typer.echo(f"Giocatori unici nelle tip: {len(player_names)}")
    if dry_run:
        for slug, name in sorted(player_names.items()):
            typer.echo(f"  {name}")
        typer.echo("\n[dry-run] Nessun dato salvato.")
        return

    existing = get_all_transfers(root)
    existing_keys = {(t.player_slug, t.to_club or "", t.season) for t in existing}

    found: list[str] = []
    not_found: list[str] = []
    total_added = 0

    for _slug, player_name in sorted(player_names.items()):
        typer.echo(f"\nCerco: {player_name} ...")
        try:
            raw = fetch_player_transfers(player_name, season, root=root)
        except ScraperError as e:
            typer.echo(f"  ERRORE scraping: {e}")
            not_found.append(player_name)
            continue

        if not raw:
            typer.echo("  Nessun trasferimento trovato")
            not_found.append(player_name)
            continue

        added = 0
        for item in raw:
            slug_rec = make_slug(item["player_name"])
            key = (slug_rec, item.get("to_club") or "", item.get("season", ""))
            if key in existing_keys:
                continue
            record = TransferRecord(
                player_name=item["player_name"],
                player_slug=slug_rec,
                from_club=item.get("from_club"),
                to_club=item.get("to_club"),
                transfer_type=item.get("transfer_type", "unknown"),  # type: ignore[arg-type]
                season=item.get("season", ""),
                confirmed_at=item["confirmed_at"],
                source="transfermarkt",
                source_url=item.get("source_url"),
            )
            add_transfer(root, record)
            existing_keys.add(key)
            added += 1
            total_added += 1
            typer.echo(f"  + {record.player_name} -> {record.to_club} ({record.transfer_type}, {record.season})")

        if added > 0:
            found.append(f"{player_name} ({added})")
        else:
            typer.echo("  (già presenti nel DB, nessuna aggiunta)")
            found.append(f"{player_name} (già nel DB)")

    typer.echo(f"\n{'='*60}")
    typer.echo(f"Totale trasferimenti aggiunti: {total_added}")
    typer.echo(f"Giocatori trovati: {len(found)}")
    if not_found:
        typer.echo(f"\n⚠ Giocatori NON trovati su Transfermarkt ({len(not_found)}) — inserire manualmente via UI:")
        for name in not_found:
            typer.echo(f"  - {name}")

    # Verifica automatica tip
    from media_advisor.mercato.verifier import verify_all_pending
    updated = verify_all_pending(root)
    if updated:
        typer.echo(f"\n{len(updated)} tip aggiornate automaticamente:")
        for u in updated:
            typer.echo(f"  {u['player_name']} -> {u['to_club']}: {u['outcome']}")


# ---------------------------------------------------------------------------
# mercato-verify
# ---------------------------------------------------------------------------


@app.command("mercato-verify")
def cmd_mercato_verify(
    fetch_missing: bool = typer.Option(
        False, "--fetch-missing",
        help="Cerca su Sofascore/TM i giocatori non ancora nel DB e aggiorna automaticamente le tip",
    ),
    season: str = typer.Option("2025", "--season", help="Stagione da cercare (es. 2025)"),
    from_date: Optional[str] = typer.Option(None, "--from-date", help="Considera solo tip pubblicate da questa data"),
    to_date: Optional[str] = typer.Option(None, "--to-date", help="Considera solo tip pubblicate fino a questa data"),
) -> None:
    """Verifica tutte le tip non_verificata contro il database trasferimenti.

    Con --fetch-missing cerca automaticamente su Sofascore/TM i giocatori mancanti:
    - trovato con trasferimento corrispondente   -> confermata / parziale
    - trovato ma nessun trasferimento per stagione -> smentita (rimasto al club)
    - non trovato su nessuna fonte               -> rimane non_verificata
    """
    from datetime import date as _date
    from media_advisor.mercato.verifier import verify_all_pending

    root = _root()

    if fetch_missing:
        from media_advisor.mercato.aggregator import load_index
        from media_advisor.mercato.scraper import ScraperError, fetch_player_transfers, resolve_player_name
        from media_advisor.mercato.transfer_db import (
            TransferRecord, add_transfer, get_all_transfers, player_slug as make_slug,
        )
        from media_advisor.mercato.verifier import verify_tip
        from media_advisor.io.json_io import write_json
        from media_advisor.io.paths import mercato_index_path
        from datetime import datetime, timezone

        date_from = _date.fromisoformat(from_date) if from_date else None
        date_to = _date.fromisoformat(to_date) if to_date else None

        index = load_index(root)
        transfers = get_all_transfers(root)
        slugs_in_db = {t.player_slug for t in transfers}

        # Giocatori unici nelle tip non_verificata non ancora nel DB
        to_fetch: dict[str, str] = {}  # slug -> player_name
        for tip in index.tips:
            if tip.outcome != "non_verificata":
                continue
            if date_from or date_to:
                d = (tip.mentioned_at.date() if tip.mentioned_at else None)
                if d is None:
                    continue
                if date_from and d < date_from:
                    continue
                if date_to and d > date_to:
                    continue
            slug = make_slug(tip.player_name)
            if slug not in slugs_in_db and slug not in to_fetch:
                to_fetch[slug] = tip.player_name

        typer.echo(f"Giocatori da cercare: {len(to_fetch)}")
        found_with_transfers = 0
        found_no_transfers = 0
        not_found = 0

        existing_keys = {(t.player_slug, t.to_club or "", t.season) for t in transfers}

        for slug, player_name in sorted(to_fetch.items()):
            canonical = resolve_player_name(player_name, root)
            if canonical is None:
                not_found += 1
                continue
            typer.echo(f"  Cerco: {player_name}" + (f" -> {canonical}" if canonical != player_name else ""))
            try:
                raw = fetch_player_transfers(canonical, season=season, root=root)
            except ScraperError as e:
                typer.echo(f"    non trovato: {e}")
                not_found += 1
                continue

            if raw:
                for item in raw:
                    s = make_slug(item["player_name"])
                    key = (s, item.get("to_club") or "", item.get("season", ""))
                    if key in existing_keys:
                        continue
                    record = TransferRecord(
                        player_name=item["player_name"],
                        player_slug=s,
                        from_club=item.get("from_club"),
                        to_club=item.get("to_club"),
                        transfer_type=item.get("transfer_type", "unknown"),  # type: ignore[arg-type]
                        season=item.get("season", ""),
                        confirmed_at=item["confirmed_at"],
                        source=item.get("source", "sofascore"),
                        source_url=item.get("source_url"),
                    )
                    add_transfer(root, record)
                    existing_keys.add(key)
                    typer.echo(f"    + {record.player_name} -> {record.to_club} ({record.transfer_type}, {record.season})")
                slugs_in_db.add(slug)
                found_with_transfers += 1
            else:
                # Trovato su TM/SS ma nessun trasferimento per questa stagione
                # Non è una smentita: semplicemente non abbiamo un evento di trasferimento da confrontare
                # (il giocatore può essere rimasto al club, o i dati stagione sono incompleti).
                typer.echo(f"    trovato ma nessun trasferimento {season} -> non verificabile (nessun update outcome)")
                slugs_in_db.add(slug)
                found_no_transfers += 1
                try:
                    season_start = int(season)
                except Exception:
                    season_start = None

                def _in_transfer_window(dt) -> bool:
                    if season_start is None:
                        return False
                    # Stagione "2025" = finestra estate 2025 (giu-ago) + inverno 2026 (gen-feb).
                    y, m = dt.year, dt.month
                    return (y == season_start and 6 <= m <= 12) or (y == season_start + 1 and 1 <= m <= 2)

                for tip in index.tips:
                    if make_slug(tip.player_name) != slug:
                        continue

                    # Se la tip NON ricade nella finestra di mercato della stagione richiesta,
                    # una nota "nessun trasferimento stagione X" è fuorviante: rimuovila e,
                    # se era stata auto-smentita da questa regola legacy, riportala a non_verificata.
                    if tip.mentioned_at and not _in_transfer_window(tip.mentioned_at):
                        if tip.outcome_notes and f"nessun trasferimento stagione {season}" in tip.outcome_notes:
                            tip.outcome_notes = None
                        if tip.outcome == "smentita" and tip.outcome_source == "sofascore":
                            tip.outcome = "non_verificata"
                            tip.outcome_updated_at = datetime.now(timezone.utc)
                        continue

                    # Dentro finestra: lascia outcome invariato (non è un verdetto),
                    # ma annota che la fonte non riporta trasferimenti in stagione.
                    if tip.outcome == "non_verificata" and not tip.outcome_notes:
                        tip.outcome_notes = f"Giocatore trovato su fonti ufficiali: nessun trasferimento stagione {season}"
                        tip.outcome_updated_at = datetime.now(timezone.utc)

        # Salva index con le smentite automatiche
        index.updated_at = datetime.now(timezone.utc)
        write_json(mercato_index_path(root), index.model_dump(mode="json"))

        typer.echo(f"\nFetch: {found_with_transfers} con trasferimenti, {found_no_transfers} rimasti al club, {not_found} non trovati")

    typer.echo("\nVerifica tip in corso...")
    updated = verify_all_pending(root)
    if not updated:
        typer.echo("Nessuna tip aggiornata ulteriormente.")
    else:
        typer.echo(f"{len(updated)} tip aggiornate da verifica DB:")
        for u in updated:
            typer.echo(f"  {u['player_name']} -> {u['to_club']}: {u['outcome']}")


# ---------------------------------------------------------------------------
# mercato-report
# ---------------------------------------------------------------------------


@app.command("mercato-report")
def cmd_mercato_report() -> None:
    """Stampa il report di veridicità per canale."""
    from media_advisor.mercato.aggregator import get_channel_stats

    stats = get_channel_stats(_root())
    if not stats:
        typer.echo("Nessuna tip nel database mercato.")
        return

    typer.echo(f"\n{'Canale':<25} {'Tot':>5} {'Risolte':>8} {'Vere':>5} {'False':>6} {'Score':>7}")
    typer.echo("-" * 60)
    for s in stats:
        score_str = f"{s.veracity_score:.0%}" if s.veracity_score is not None else "  n/a"
        typer.echo(
            f"{s.channel_id:<25} {s.total_tips:>5} {s.resolved_tips:>8} "
            f"{s.true_tips:>5} {s.false_tips:>6} {score_str:>7}"
        )


# ---------------------------------------------------------------------------
# mercato-normalize-players
# ---------------------------------------------------------------------------


@app.command("mercato-normalize-players")
def cmd_mercato_normalize_players(
    channel: Optional[str] = typer.Option(None, "--channel", help="Limita a un canale"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Mostra le modifiche senza salvarle"),
) -> None:
    """Re-normalizza i player_name in tutti i tip file esistenti usando il registry + fuzzy.

    Utile dopo aver aggiunto nuovi alias in player-aliases.json o nuovi transfer confermati.
    Eseguire seguito da mercato-rebuild-index per aggiornare l'index globale.
    """
    from media_advisor.io.json_io import read_json, write_json
    from media_advisor.mercato.models import VideoMercatoResult
    from media_advisor.mercato.player_normalizer import load_player_registry, normalize_player_name

    root = _root()
    mercato_dir = root / "mercato"
    tips_root = mercato_dir / "tips"

    if not tips_root.exists():
        typer.echo("Nessuna tip trovata: manca la cartella mercato/tips/")
        raise typer.Exit(1)

    registry = load_player_registry(mercato_dir)
    typer.echo(f"Registry caricato: {len(set(registry.values()))} giocatori canonici")

    files = _collect_tip_files(tips_root, channel)

    total_tips = 0
    changed_tips = 0
    changed_files = 0

    for f in files:
        try:
            vr = VideoMercatoResult.model_validate(read_json(f))
        except Exception:
            continue

        file_changed = False
        for tip in (vr.tips or []):
            if not tip.player_name:
                continue
            normalized = normalize_player_name(tip.player_name, mercato_dir)
            total_tips += 1
            if normalized != tip.player_name:
                if dry_run:
                    typer.echo(f"  [{tip.video_id}] {tip.player_name!r} → {normalized!r}")
                tip.player_name = normalized
                changed_tips += 1
                file_changed = True

        if file_changed:
            changed_files += 1
            if not dry_run:
                write_json(f, vr.model_dump(mode="json"))

    suffix = " (DRY RUN)" if dry_run else ""
    typer.echo(
        f"Done{suffix}: {total_tips} tip analizzate, "
        f"{changed_tips} nomi corretti in {changed_files} file."
    )
    if not dry_run and changed_tips > 0:
        typer.echo("Riesegui 'mercato-rebuild-index' per aggiornare l'index globale.")


# ---------------------------------------------------------------------------
# mercato-rebuild-index
# ---------------------------------------------------------------------------


@app.command("mercato-rebuild-index")
def cmd_mercato_rebuild_index(
    channel: Optional[str] = typer.Option(None, "--channel", help="Limita a un canale"),
    prune_non_mercato: bool = typer.Option(
        True, "--prune-non-mercato/--keep-all", help="Rimuovi tip non-mercato usando le regole correnti"
    ),
    rewrite_tip_files: bool = typer.Option(
        True,
        "--rewrite-tip-files/--no-rewrite-tip-files",
        help="Normalizza e riscrive mercato/tips/** (consigliato per eliminare encoding sporchi tipo 'Atl�tico')",
    ),
) -> None:
    """Ricostruisce mercato/index.json da mercato/tips/** (utile dopo modifiche a filtri/prompt).

    Nota: l'index attuale è append-only: senza rebuild puoi vedere tip vecchie anche dopo aver fixato l'estrazione.
    """
    from datetime import datetime, timezone

    from media_advisor.io.json_io import read_json, write_json
    from media_advisor.io.paths import mercato_index_path
    from media_advisor.mercato.corroborator import corroborate
    from media_advisor.mercato.extractor import is_plausible_mercato_tip
    from media_advisor.mercato.models import MercatoIndex, VideoMercatoResult

    def _norm_club(s: str | None) -> str | None:
        if not s:
            return s
        import re as _re
        import unicodedata as _ud

        # Drop accents and odd replacement chars; keep something stable for matching.
        cleaned = s.replace("\ufffd", "")  # replacement char
        cleaned = _ud.normalize("NFKD", cleaned).encode("ascii", "ignore").decode("ascii")
        cleaned = _re.sub(r"\s+", " ", cleaned).strip()
        # Heuristic fix for common corruption: "Atltico" -> "Atletico"
        cleaned = cleaned.replace("Atltico", "Atletico")
        return cleaned or s

    def _sort_key(tip) -> tuple:
        def _norm(s: str | None) -> str:
            return (s or "").strip().lower()

        # Deterministic ordering for stable diffs/UI.
        return (
            _norm(tip.player_name),
            _norm(tip.to_club),
            _norm(tip.from_club),
            str(tip.mentioned_at or ""),
            _norm(tip.channel_id),
            _norm(tip.video_id),
            _norm(tip.tip_id),
        )

    root = _root()
    tips_root = root / "mercato" / "tips"
    if not tips_root.exists():
        typer.echo("Nessuna tip trovata: manca la cartella mercato/tips/")
        raise typer.Exit(1)

    files = _collect_tip_files(tips_root, channel)

    if not files:
        typer.echo("Nessun file trovato in mercato/tips/ (hai già runnato mercato-scan/mercato-analyze?)")
        raise typer.Exit(1)

    all_tips = []
    rewritten_files = 0
    for f in files:
        try:
            vr = VideoMercatoResult.model_validate(read_json(f))
            tips_out = []
            for tip in (vr.tips or []):
                # Normalize clubs to avoid false "smentite" due to unicode/encoding.
                tip.from_club = _norm_club(tip.from_club)
                tip.to_club = _norm_club(tip.to_club)
                if prune_non_mercato and not is_plausible_mercato_tip(tip):
                    continue
                tips_out.append(tip)
                all_tips.append(tip)

            # Optionally rewrite per-video files (so future rebuilds stay clean).
            if rewrite_tip_files:
                tips_out_sorted = sorted(tips_out, key=_sort_key)
                vr2 = vr.model_copy(update={"tips": tips_out_sorted})
                write_json(f, vr2.model_dump(mode="json"))
                rewritten_files += 1
        except Exception:
            continue

    # Rebuild index and re-run corroboration incrementally (so tips corroborate each other).
    index = MercatoIndex(updated_at=datetime.now(timezone.utc), tips=[])
    for tip in sorted(all_tips, key=_sort_key):
        corroborate(index, [tip])

    # Stable ordering for index.json (corroborate mutates corroborated_by order, but list order is now deterministic).
    index.tips = sorted(index.tips, key=_sort_key)

    out = mercato_index_path(root)
    write_json(out, index.model_dump(mode="json"))
    typer.echo(
        f"Index rebuilt: {out}  tips={len(index.tips)}  prune_non_mercato={prune_non_mercato}  "
        f"rewrite_tip_files={rewrite_tip_files} files={rewritten_files}"
    )


# ---------------------------------------------------------------------------
# mercato-enrich-dates
# ---------------------------------------------------------------------------


@app.command("mercato-enrich-dates")
def cmd_mercato_enrich_dates(
    channel: Optional[str] = typer.Option(None, "--channel", help="Limita a un canale (default: tutti i canali mercato)"),
    max_videos: int = typer.Option(600, "--max-videos", help="Numero massimo di video da analizzare per canale"),
) -> None:
    """Scarica le date di pubblicazione dei video tramite yt-dlp e popola channels/video-dates.json.

    Necessario per poter usare --from-date/--to-date in mercato-scan su video storici.
    Non scarica nessun file video — solo i metadati (veloce).
    """
    from media_advisor.fetch import fetch_channel_dates_ytdlp
    from media_advisor.io.json_io import read_json_or_default, write_json
    from media_advisor.io.paths import video_dates_cache_path
    from media_advisor.models.channels import ChannelsConfig

    root = _root()
    cfg = ChannelsConfig.model_validate(read_json_or_default(root / "channels" / "channels.json", default={}))

    channels_to_process = [
        c for c in cfg.channels
        if c.fetch_rule and getattr(c.fetch_rule, "channel_url", None)
        and (channel is None or c.id == channel)
    ]

    if not channels_to_process:
        typer.echo("Nessun canale trovato.")
        return

    dates_path = video_dates_cache_path(root)
    dates_cache: dict[str, str] = read_json_or_default(dates_path, default={}) or {}
    total_added = 0

    for ch in channels_to_process:
        channel_url = ch.fetch_rule.channel_url  # type: ignore[union-attr]
        typer.echo(f"[{ch.id}] Scarico date da yt-dlp ({channel_url}) ...")
        try:
            new_dates = fetch_channel_dates_ytdlp(channel_url, max_videos=max_videos)
            added = sum(1 for vid in new_dates if vid not in dates_cache or not dates_cache[vid])
            dates_cache.update(new_dates)
            total_added += added
            typer.echo(f"  -> {len(new_dates)} video trovati, {added} date nuove/aggiornate")
        except Exception as e:
            typer.echo(f"  Errore: {e}", err=True)

    write_json(dates_path, dates_cache)

    # Arricchisci anche i transcript già scaricati con le date ora disponibili
    typer.echo("\nArricchisco i transcript esistenti con le date...")
    from media_advisor.io.paths import transcript_path
    from media_advisor.models.transcript import TranscriptResponse, VideoMetadata

    enriched = 0
    transcripts_root = root / "data" / "transcripts"
    channel_dirs = (
        [transcripts_root / channel] if channel and (transcripts_root / channel).exists()
        else list(transcripts_root.iterdir()) if transcripts_root.exists() else []
    )
    for ch_dir in channel_dirs:
        if not ch_dir.is_dir():
            continue
        for t_file in ch_dir.glob("*.json"):
            vid = t_file.stem
            if vid not in dates_cache:
                continue
            try:
                from media_advisor.io.json_io import read_json, write_json as _wj
                raw = read_json(t_file)
                tr = TranscriptResponse.model_validate(raw)
                if tr.metadata and tr.metadata.published_at:
                    continue  # già ha la data
                meta = tr.metadata or VideoMetadata()
                meta = meta.model_copy(update={"published_at": dates_cache[vid]})
                tr2 = tr.model_copy(update={"metadata": meta})
                _wj(t_file, tr2.model_dump(mode="json"))
                enriched += 1
            except Exception:
                continue

    typer.echo(f"{enriched} transcript aggiornati con published_at")
    typer.echo(f"\nDone. Totale date in cache: {len(dates_cache)}")


# ---------------------------------------------------------------------------
# mercato-set-player-tm-id
# ---------------------------------------------------------------------------


@app.command("mercato-set-alias")
def cmd_mercato_set_alias(
    extracted: str = typer.Option(..., "--extracted", help="Nome come estratto dall'AI (es. 'Gigio Donnarumma')"),
    canonical: str = typer.Option(..., "--canonical", help="Nome canonico da cercare (es. 'Gianluigi Donnarumma')"),
) -> None:
    """Aggiunge un alias nome-AI -> nome-canonico in mercato/player-aliases.json.

    Utile quando l'AI estrae nomi abbreviati o errati e la ricerca fallisce.

    Esempi:
      media-advisor mercato-set-alias --extracted "Bastoni" --canonical "Alessandro Bastoni"
      media-advisor mercato-set-alias --extracted "Gigio Donnarumma" --canonical "Gianluigi Donnarumma"
    """
    import json, re as _re
    from pathlib import Path as _Path

    root = _root()
    aliases_path = root / "mercato" / "player-aliases.json"
    slug = _re.sub(r"[^a-z0-9]+", "-", extracted.lower().strip()).strip("-")

    data: dict = {}
    if aliases_path.exists():
        try:
            data = json.loads(aliases_path.read_text(encoding="utf-8"))
        except Exception:
            pass

    data[slug] = canonical
    aliases_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    typer.echo(f"Alias salvato: '{extracted}' (slug={slug}) -> '{canonical}'")


@app.command("mercato-set-player-tm-id")
def cmd_mercato_set_player_tm_id(
    player: str = typer.Option(..., "--player", help="Nome del giocatore"),
    tm_id: str = typer.Option(..., "--tm-id", help="TM ID numerico (trovalo su transfermarkt.it/profil/spieler/{id})"),
) -> None:
    """Salva manualmente il TM ID di un giocatore nella cache locale.

    Utile quando search_player() fallisce per bot-detection di Transfermarkt.
    Il TM ID si trova nell'URL del profilo giocatore su transfermarkt.it:
      https://www.transfermarkt.it/{slug}/profil/spieler/{tm_id}

    Esempio:
      media-advisor mercato-set-player-tm-id --player "Romelu Lukaku" --tm-id 96341
    """
    from media_advisor.mercato.scraper import set_player_tm_id

    set_player_tm_id(_root(), player, tm_id)
    typer.echo(f"Salvato: '{player}' -> TM ID {tm_id}")
    typer.echo("Ora puoi rieseguire mercato-fetch-transfers o mercato-import-season.")


if __name__ == "__main__":
    app()
