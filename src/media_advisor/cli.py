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
    model: str = typer.Option("gpt-4.1-mini", "--model", help="LLM model for extraction"),
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
    model: str = typer.Option("gpt-4.1-mini", "--model"),
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

    if not pending.items and not all_unanalyzed:
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
    """Confirm a video from pending: append to channel list and remove from pending (DB)."""
    root = _root()

    from media_advisor.io.channel_store import (
        load_channels_config_dict,
        load_pending_dict,
        read_channel_video_urls,
        save_pending_dict,
        write_channel_video_urls,
    )
    from media_advisor.models.channels import ChannelsConfig
    from media_advisor.models.pending import PendingResult

    pending = PendingResult.model_validate(load_pending_dict(root))
    item = next((v for v in pending.items if v.video_id == video_id), None)
    if not item:
        typer.echo(f"Video {video_id} not found in pending", err=True)
        raise typer.Exit(1)

    config = ChannelsConfig.model_validate(load_channels_config_dict(root))
    channel = next((c for c in config.channels if c.id == item.channel_id), None)
    if not channel:
        typer.echo(f"Channel {item.channel_id} not found in registry", err=True)
        raise typer.Exit(1)

    urls = read_channel_video_urls(root, channel.video_list)
    url = f"https://www.youtube.com/watch?v={video_id}"
    if url not in urls:
        urls.append(url)
        write_channel_video_urls(root, channel.video_list, urls)
        typer.echo(f"Added {video_id} to {channel.video_list}")

    pending.items = [v for v in pending.items if v.video_id != video_id]
    save_pending_dict(root, pending.model_dump(mode="json"))
    typer.echo(f"Removed {video_id} from pending")


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
        import re as _re

        client = TranscriptClient(s.transcript_api_key)
        transcript = await client.get_transcript(video, include_timestamp=True, send_metadata=True)

        m_vid = _re.search(r"(?:v=)([a-zA-Z0-9_-]{11})", video)
        video_id = m_vid.group(1) if m_vid else (video if len(video) == 11 else None)

        dest = output
        if dest is None and channel and video_id:
            from media_advisor.io.paths import transcript_path

            dest = transcript_path(_root(), channel, video_id)

        if dest:
            from media_advisor.io.json_io import write_json

            payload = transcript.model_dump(mode="json")
            write_json(dest, payload)
            if channel and video_id:
                from media_advisor.io.transcript_storage import db_upsert_transcript

                db_upsert_transcript(_root(), channel, video_id, payload)
            typer.echo(f"Saved transcript to {dest}" + (" (+ DB)" if channel and video_id else ""))

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
    model: str = typer.Option("gpt-4.1-mini", "--model"),
    force: bool = typer.Option(False, "--force", help="Re-analyze even if analysis exists"),
) -> None:
    """Analyze a single video (transcript must already be saved)."""
    s = _get_settings()
    if not s.openai_api_key:
        typer.echo("Error: OPENAI_API_KEY not set", err=True)
        raise typer.Exit(1)

    root = _root()
    from media_advisor.db.repository import analysis_exists_in_db, upsert_video_analysis
    from media_advisor.db.session import session_scope
    from media_advisor.io.transcript_storage import load_transcript_dict
    from media_advisor.models.transcript import TranscriptResponse
    from media_advisor.pipeline.analyze_v2 import analyze_video_v2

    with session_scope(root, read_only=True) as session:
        if analysis_exists_in_db(session, channel, video_id) and not force:
            typer.echo("Analysis already in DB (use --force to re-analyze)")
            return

    async def _run() -> None:
        raw_t = load_transcript_dict(root, channel, video_id)
        if raw_t is None:
            typer.echo(f"Transcript not found in DB for {channel}/{video_id}", err=True)
            raise typer.Exit(1)
        transcript = TranscriptResponse.model_validate(raw_t)
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
        with session_scope(root) as session:
            upsert_video_analysis(session, channel, video_id, analysis.model_dump(mode="json"))
        typer.echo("Analysis saved to DB")
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
    model: str = typer.Option("gpt-4.1-mini", "--model"),
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
    from media_advisor.io.channel_store import load_channels_config_dict
    from media_advisor.models.transcript import TranscriptResponse, VideoMetadata
    from media_advisor.models.channels import ChannelsConfig

    def _get_channel_url(root) -> str | None:
        try:
            cfg = ChannelsConfig.model_validate(load_channels_config_dict(root))
            ch = next((c for c in cfg.channels if c.id == channel), None)
            return (ch.fetch_rule.channel_url if ch and ch.fetch_rule else None)  # type: ignore[attr-defined]
        except Exception:
            return None

    async def _ensure_transcript_metadata(root) -> None:
        from media_advisor.io.transcript_storage import load_transcript_dict, save_transcript_to_store

        raw = load_transcript_dict(root, channel, video_id)
        if raw is None:
            return
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
            save_transcript_to_store(root, channel, video_id, tr2.model_dump(mode="json"))
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
    model: str = typer.Option("gpt-4.1-mini", "--model"),
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

    from media_advisor.db.repository import list_transcript_video_ids, mercato_existing_pair_keys
    from media_advisor.db.session import session_scope
    from media_advisor.io.channel_store import load_channels_config_dict, load_video_dates_dict
    from media_advisor.mercato.analyzer import analyze_video_mercato
    from media_advisor.transcript_api.client import TranscriptClient
    from media_advisor.models.transcript import TranscriptResponse, VideoMetadata
    from media_advisor.models.channels import ChannelsConfig

    with session_scope(root, read_only=True) as session:
        id_pairs = list_transcript_video_ids(session, channel)
        pre_mercato = mercato_existing_pair_keys(session, [(vid, ch_id) for ch_id, vid in id_pairs])
    if not id_pairs:
        typer.echo("Nessun transcript nel database. Esegui db-migrate-from-json o la pipeline.")
        return

    async def _run() -> None:
        from media_advisor.mercato.analyzer import update_index_with_new_tips
        from media_advisor.mercato.models import MercatoTip

        # Cache latest results per channel (one API call per channel).
        latest_cache: dict[str, list[dict]] = {}
        _dates_cache: dict[str, str] = load_video_dates_dict(root)

        _channels_cfg = ChannelsConfig.model_validate(load_channels_config_dict(root))
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
            from media_advisor.io.transcript_storage import load_transcript_dict, save_transcript_to_store

            raw = load_transcript_dict(root, ch_id, vid)
            if raw is None:
                return
            tr = TranscriptResponse.model_validate(raw)
            if tr.metadata and tr.metadata.published_at:
                return

            # 1. Prova la dates cache persistente (salvata da fetch-now)
            cached_date = _dates_cache.get(vid)
            if cached_date:
                meta = tr.metadata or VideoMetadata()
                meta = meta.model_copy(update={"published_at": cached_date})
                tr2 = tr.model_copy(update={"metadata": meta})
                save_transcript_to_store(root, ch_id, vid, tr2.model_dump(mode="json"))
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
            save_transcript_to_store(root, ch_id, vid, tr2.model_dump(mode="json"))

        total, analyzed, skipped = 0, 0, 0
        all_new_tips: list[MercatoTip] = []
        for ch_id, vid in id_pairs:
            is_mercato_ch = _is_mercato_channel(ch_id)
            total += 1
            if not all_videos and not is_mercato_ch:
                skipped += 1
                continue
            try:
                from media_advisor.io.transcript_storage import load_transcript_dict

                data = load_transcript_dict(root, ch_id, vid)
                if not data:
                    skipped += 1
                    continue
                title = (data.get("metadata") or {}).get("title") or ""
                if not all_videos and not is_mercato_ch and not _MERCATO_KW.search(title):
                    skipped += 1
                    continue
                await _ensure_metadata(ch_id, vid)
                if date_from or date_to:
                    data = load_transcript_dict(root, ch_id, vid) or data
                    pub_str = (data.get("metadata") or {}).get("published_at")
                    if not pub_str:
                        skipped += 1
                        continue
                    pub_d = _date.fromisoformat(pub_str[:10])
                    if date_from and pub_d < date_from:
                        skipped += 1
                        continue
                    if date_to and pub_d > date_to:
                        skipped += 1
                        continue
                _tip_existed = (ch_id, vid) in pre_mercato and not force
                result = await analyze_video_mercato(
                    root=root,
                    video_id=vid,
                    channel_id=ch_id,
                    api_key=s.openai_api_key,
                    model=model,
                    force=force,
                    update_index=False,
                )
                if not _tip_existed:
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
        from media_advisor.mercato.analyzer import save_mercato_index
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
        save_mercato_index(root, index)

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
    """Re-normalizza i player_name nelle tip mercato (SQLite) usando il registry + fuzzy.

    Utile dopo aver aggiunto nuovi alias o transfer confermati.
    Eseguire seguito da mercato-rebuild-index per aggiornare l'index globale.
    """
    import json

    from media_advisor.db.repository import list_mercato_video_result_rows, upsert_mercato_video_result
    from media_advisor.db.session import session_scope
    from media_advisor.mercato.models import VideoMercatoResult
    from media_advisor.mercato.player_normalizer import load_player_registry, normalize_player_name

    root = _root()

    with session_scope(root, read_only=True) as session:
        rows = list_mercato_video_result_rows(session, channel)

    if not rows:
        typer.echo("Nessuna tip nel database. Esegui mercato-scan o db-migrate-from-json.")
        raise typer.Exit(1)

    registry = load_player_registry(root)
    typer.echo(f"Registry caricato: {len(set(registry.values()))} giocatori canonici")

    total_tips = 0
    changed_tips = 0
    changed_rows = 0

    for row in rows:
        try:
            vr = VideoMercatoResult.model_validate(json.loads(row.payload_json))
        except Exception:
            continue

        row_changed = False
        for tip in (vr.tips or []):
            if not tip.player_name:
                continue
            normalized = normalize_player_name(tip.player_name, root)
            total_tips += 1
            if normalized != tip.player_name:
                if dry_run:
                    typer.echo(f"  [{tip.video_id}] {tip.player_name!r} → {normalized!r}")
                tip.player_name = normalized
                changed_tips += 1
                row_changed = True

        if row_changed:
            changed_rows += 1
            if not dry_run:
                with session_scope(root) as session:
                    upsert_mercato_video_result(
                        session, row.channel_id, row.video_id, vr.model_dump(mode="json")
                    )

    suffix = " (DRY RUN)" if dry_run else ""
    typer.echo(
        f"Done{suffix}: {total_tips} tip analizzate, "
        f"{changed_tips} nomi corretti in {changed_rows} record."
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
    """Ricostruisce l'index mercato globale da tips in SQLite (fallback: mercato/tips/**).

    Nota: l'index attuale è append-only: senza rebuild puoi vedere tip vecchie anche dopo aver fixato l'estrazione.
    """
    import json
    from datetime import datetime, timezone

    from media_advisor.db.repository import list_mercato_video_result_rows, upsert_mercato_video_result
    from media_advisor.db.session import session_scope
    from media_advisor.io.json_io import read_json
    from media_advisor.mercato.analyzer import save_mercato_index
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

    with session_scope(root, read_only=True) as session:
        db_rows = list_mercato_video_result_rows(session, channel)

    all_tips = []
    rewritten = 0

    def _process_vr(vr: VideoMercatoResult, ch_id: str, vid: str) -> None:
        nonlocal rewritten
        tips_out = []
        for tip in (vr.tips or []):
            tip.from_club = _norm_club(tip.from_club)
            tip.to_club = _norm_club(tip.to_club)
            if prune_non_mercato and not is_plausible_mercato_tip(tip):
                continue
            tips_out.append(tip)
            all_tips.append(tip)
        if rewrite_tip_files:
            tips_out_sorted = sorted(tips_out, key=_sort_key)
            vr2 = vr.model_copy(update={"tips": tips_out_sorted})
            with session_scope(root) as session:
                upsert_mercato_video_result(session, ch_id, vid, vr2.model_dump(mode="json"))
            rewritten += 1

    if db_rows:
        for row in db_rows:
            try:
                vr = VideoMercatoResult.model_validate(json.loads(row.payload_json))
                _process_vr(vr, row.channel_id, row.video_id)
            except Exception:
                continue
    elif tips_root.exists():
        files = _collect_tip_files(tips_root, channel)
        if not files:
            typer.echo("Nessun file in mercato/tips/ né record nel DB.")
            raise typer.Exit(1)
        for f in files:
            try:
                vr = VideoMercatoResult.model_validate(read_json(f))
                ch_id = f.parent.name
                vid = f.stem
                _process_vr(vr, ch_id, vid)
            except Exception:
                continue
    else:
        typer.echo("Nessuna tip nel DB e manca mercato/tips/.")
        raise typer.Exit(1)

    if not all_tips:
        typer.echo("Nessuna tip dopo filtri (prune_non_mercato?).")
        raise typer.Exit(1)

    index = MercatoIndex(updated_at=datetime.now(timezone.utc), tips=[])
    for tip in sorted(all_tips, key=_sort_key):
        corroborate(index, [tip])

    index.tips = sorted(index.tips, key=_sort_key)
    save_mercato_index(root, index)
    typer.echo(
        f"Index rebuilt (db): tips={len(index.tips)}  prune_non_mercato={prune_non_mercato}  "
        f"rewrite_tip_files={rewrite_tip_files} rows_updated={rewritten}"
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
    from media_advisor.io.channel_store import load_channels_config_dict, load_video_dates_dict, save_video_dates_dict
    from media_advisor.models.channels import ChannelsConfig

    root = _root()
    cfg = ChannelsConfig.model_validate(load_channels_config_dict(root))

    channels_to_process = [
        c for c in cfg.channels
        if c.fetch_rule and getattr(c.fetch_rule, "channel_url", None)
        and (channel is None or c.id == channel)
    ]

    if not channels_to_process:
        typer.echo("Nessun canale trovato.")
        return

    dates_cache: dict[str, str] = load_video_dates_dict(root)
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

    save_video_dates_dict(root, dates_cache)

    # Arricchisci anche i transcript già scaricati con le date ora disponibili
    typer.echo("\nArricchisco i transcript esistenti con le date...")
    from media_advisor.db.repository import list_transcript_video_ids
    from media_advisor.db.session import session_scope
    from media_advisor.models.transcript import TranscriptResponse, VideoMetadata

    enriched = 0
    with session_scope(root, read_only=True) as session:
        id_pairs = list_transcript_video_ids(session, channel)
    for ch_store_id, vid in id_pairs:
        if vid not in dates_cache:
            continue
        try:
            from media_advisor.io.transcript_storage import load_transcript_dict, save_transcript_to_store

            raw = load_transcript_dict(root, ch_store_id, vid)
            if raw is None:
                continue
            tr = TranscriptResponse.model_validate(raw)
            if tr.metadata and tr.metadata.published_at:
                continue
            meta = tr.metadata or VideoMetadata()
            meta = meta.model_copy(update={"published_at": dates_cache[vid]})
            tr2 = tr.model_copy(update={"metadata": meta})
            save_transcript_to_store(root, ch_store_id, vid, tr2.model_dump(mode="json"))
            enriched += 1
        except Exception:
            continue

    typer.echo(f"{enriched} transcript aggiornati con published_at")
    typer.echo(f"\nDone. Totale date in cache: {len(dates_cache)}")


# ---------------------------------------------------------------------------
# mercato-backfill-dates
# ---------------------------------------------------------------------------


@app.command("mercato-backfill-dates")
def cmd_mercato_backfill_dates(
    channel: Optional[str] = typer.Option(None, "--channel", help="Limita a un canale"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Mostra cosa cambierebbe senza scrivere"),
) -> None:
    """Popola mentioned_at nei tip esistenti leggendo published_at dai transcript.

    Da eseguire dopo mercato-enrich-dates per aggiornare i tip storici
    senza ri-estrarre nulla con GPT. Ricostruisce l'index al termine.
    """
    from datetime import datetime, timezone
    from media_advisor.io.json_io import read_json, write_json, read_json_or_default
    from media_advisor.io.paths import video_dates_cache_path

    root = _root()
    tips_root = root / "mercato" / "tips"
    if not tips_root.exists():
        typer.echo("Nessun tip trovato.")
        return

    dates_cache: dict[str, str] = read_json_or_default(video_dates_cache_path(root), default={}) or {}

    channel_dirs = (
        [tips_root / channel] if channel and (tips_root / channel).exists()
        else [d for d in tips_root.iterdir() if d.is_dir()]
    )

    updated_files, updated_tips, missing_date = 0, 0, 0

    for ch_dir in channel_dirs:
        for tip_file in sorted(ch_dir.glob("*.json")):
            vid = tip_file.stem
            ch_id = ch_dir.name

            # Cerca la data: prima nella dates cache, poi nel transcript
            date_str: str | None = dates_cache.get(vid)
            if not date_str:
                from media_advisor.io.transcript_storage import load_transcript_dict

                try:
                    raw = load_transcript_dict(root, ch_id, vid)
                    if raw:
                        date_str = (raw.get("metadata") or {}).get("published_at")
                except Exception:
                    pass

            if not date_str:
                missing_date += 1
                continue

            try:
                dt = datetime.fromisoformat(date_str)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                mentioned_at_iso = dt.isoformat()
            except ValueError:
                missing_date += 1
                continue

            try:
                data = read_json(tip_file)
            except Exception:
                continue

            tips_list = data.get("tips") or []
            changed = False
            for tip in tips_list:
                if not tip.get("mentioned_at"):
                    tip["mentioned_at"] = mentioned_at_iso
                    updated_tips += 1
                    changed = True

            if changed:
                updated_files += 1
                if not dry_run:
                    write_json(tip_file, data)

    action = "Aggiornerei" if dry_run else "Aggiornati"
    typer.echo(f"{action} {updated_tips} tip in {updated_files} file.")
    typer.echo(f"Video senza data trovata: {missing_date}")

    if updated_files > 0 and not dry_run:
        typer.echo("\nRicostruzione index mercato...")
        from media_advisor.mercato.aggregator import rebuild_index
        rebuild_index(root)
        typer.echo("Index ricostruito.")
    elif dry_run:
        typer.echo("\n(dry-run: nessuna modifica applicata)")


# ---------------------------------------------------------------------------
# analysis-backfill-dates
# ---------------------------------------------------------------------------


@app.command("analysis-backfill-dates")
def cmd_analysis_backfill_dates(
    channel: str | None = typer.Option(None, "--channel", help="Limita a un canale specifico"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Mostra cosa cambierebbe senza scrivere"),
) -> None:
    """Popola published_at nei file di analisi che ce l'hanno null, leggendo da video-dates.json."""
    from media_advisor.io.json_io import read_json, write_json, read_json_or_default
    from media_advisor.io.paths import video_dates_cache_path

    root = _root()
    analysis_root = root / "data" / "analysis"
    if not analysis_root.exists():
        typer.echo("Nessuna analisi trovata.")
        return

    dates_cache: dict[str, str] = read_json_or_default(video_dates_cache_path(root), default={}) or {}

    ch_dirs = (
        [analysis_root / channel] if channel and (analysis_root / channel).exists()
        else [d for d in analysis_root.iterdir() if d.is_dir()]
    )

    updated, already_ok, missing_date = 0, 0, 0

    for ch_dir in sorted(ch_dirs):
        for a_file in sorted(ch_dir.glob("*.json")):
            vid = a_file.stem
            data = read_json(a_file)
            if data is None:
                continue
            meta = data.get("metadata") or {}
            if meta.get("published_at"):
                already_ok += 1
                continue
            date = dates_cache.get(vid)
            if not date:
                missing_date += 1
                typer.echo(f"  [missing] {ch_dir.name}/{vid}")
                continue
            if not dry_run:
                meta["published_at"] = date
                data["metadata"] = meta
                write_json(a_file, data)
            updated += 1
            typer.echo(f"  [ok] {ch_dir.name}/{vid} -> {date}")

    typer.echo(f"\nRisultato: {updated} aggiornati, {already_ok} già ok, {missing_date} senza data")
    if dry_run:
        typer.echo("(dry-run: nessuna modifica applicata)")


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


# ---------------------------------------------------------------------------
# daily-report
# ---------------------------------------------------------------------------


@app.command("daily-report")
def cmd_daily_report(
    date: Optional[str] = typer.Option(None, "--date", help="Data YYYY-MM-DD (default: oggi)"),
    no_update: bool = typer.Option(False, "--no-update", help="Salta auto-update e mercato-scan, usa i dati già presenti"),
    model: str = typer.Option("gpt-4.1-mini", "--model", help="Modello OpenAI per la pipeline claims"),
) -> None:
    """Fetch → mercato-scan → sommario giornaliero in reports/YYYY-MM-DD.md.

    Flusso completo:
      1. Scarica i nuovi video dai canali mercato (auto-update)
      2. Estrae le indiscrezioni dai transcript (mercato-scan)
      3. Genera il sommario in italiano ottimizzato per i social
      4. Salva in reports/YYYY-MM-DD.md e stampa su stdout

    Usa --no-update per saltare i passi 1 e 2 (es. per rigenerare il report su dati già presenti).
    """
    from datetime import date as date_type
    from media_advisor.digest import DigestGenerationError, generate_mercato_digest, write_mercato_report

    s = _get_settings()
    if not s.openai_api_key:
        typer.echo("Error: OPENAI_API_KEY not set", err=True)
        raise typer.Exit(1)

    try:
        target_date = date_type.fromisoformat(date) if date else date_type.today()
    except ValueError:
        typer.echo(f"Error: formato data non valido '{date}', usa YYYY-MM-DD", err=True)
        raise typer.Exit(1)

    root = _root()

    if not no_update:
        if not s.transcript_api_key:
            typer.echo("Error: TRANSCRIPT_API_KEY not set", err=True)
            raise typer.Exit(1)

        # Step 1: fetch → merge → pipeline claims
        typer.echo("[daily-report] 1/3  Fetch + merge + analisi claims...")
        from media_advisor.fetch import run_fetch_new_videos
        from media_advisor.merge import merge_pending_into_channels
        from media_advisor.run_pipeline import run_from_list

        pending = asyncio.run(run_fetch_new_videos(root, s.transcript_api_key))
        new_ids: set[str] = set()
        if pending.items:
            merge_pending_into_channels(root)
            new_ids = {v.video_id for v in pending.items}
            asyncio.run(
                run_from_list(
                    root=root,
                    transcript_api_key=s.transcript_api_key,
                    openai_api_key=s.openai_api_key,
                    model=model,
                    only_video_ids=new_ids,
                )
            )
            typer.echo(f"    Nuovi video analizzati: {len(new_ids)}")
        else:
            typer.echo("    Nessun nuovo video.")

        # Step 2: mercato-scan sui nuovi video dei canali mercato
        typer.echo("[daily-report] 2/3  Mercato scan sui nuovi video...")
        if new_ids:
            from media_advisor.mercato.analyzer import analyze_video_mercato
            from media_advisor.mercato.aggregator import rebuild_index
            from media_advisor.db.repository import mercato_existing_pair_keys, transcript_existing_pair_keys
            from media_advisor.db.session import session_scope
            from media_advisor.io.channel_store import load_channels_config_dict
            from media_advisor.models.channels import ChannelsConfig

            cfg = ChannelsConfig.model_validate(load_channels_config_dict(root))
            mercato_ch_ids = {c.id for c in cfg.channels if c.mercato_channel}

            mercato_items = [v for v in pending.items if v.channel_id in mercato_ch_ids]
            scan_pairs = [(v.video_id, v.channel_id) for v in mercato_items]
            with session_scope(root, read_only=True) as session:
                skip_mercato = mercato_existing_pair_keys(session, scan_pairs)
                have_transcript = transcript_existing_pair_keys(session, scan_pairs)

            async def _scan_new() -> None:
                for v in mercato_items:
                    key = (v.channel_id, v.video_id)
                    if key in skip_mercato:
                        continue
                    if key not in have_transcript:
                        continue
                    try:
                        await analyze_video_mercato(
                            root=root,
                            video_id=v.video_id,
                            channel_id=v.channel_id,
                            api_key=s.openai_api_key,
                            model=model,
                            force=False,
                            update_index=False,
                        )
                    except Exception as exc:
                        typer.echo(f"    [warn] mercato-scan {v.video_id}: {exc}", err=True)

            asyncio.run(_scan_new())
            if mercato_items:
                rebuild_index(root)
                typer.echo(f"    Scan mercato: {len(mercato_items)} video processati.")
        else:
            typer.echo("    Nessun nuovo video mercato da scansionare.")

    # Step 3: genera digest
    typer.echo("[daily-report] 3/3  Generazione sommario...")
    try:
        digest_text = asyncio.run(generate_mercato_digest(root, target_date, s.openai_api_key))
    except DigestGenerationError as exc:
        typer.echo(f"Errore: digest non valido/non pubblicabile ({exc})", err=True)
        raise typer.Exit(1)

    if not digest_text:
        typer.echo(f"Nessuna indiscrezione trovata per il {target_date.isoformat()}.")
        typer.echo("Suggerimento: verifica che i tip abbiano 'mentioned_at' valorizzato (mercato-enrich-dates).")
        raise typer.Exit(0)

    report_file, content, _ = write_mercato_report(root, target_date, digest_text)
    typer.echo(f"\n{'='*60}")
    typer.echo(content)
    typer.echo(f"{'='*60}")
    typer.echo(f"\nSalvato in: {report_file}")
    typer.echo(f"Versione Telegram: {report_file.with_suffix('.telegram.html')}")
    typer.echo(f"Versione Twitter: {report_file.with_suffix('.twitter.txt')}")


# ---------------------------------------------------------------------------
# publish-telegram
# ---------------------------------------------------------------------------


@app.command("publish-telegram")
def cmd_publish_telegram(
    date: Optional[str] = typer.Option(None, "--date", help="Data YYYY-MM-DD (default: oggi)"),
) -> None:
    """Genera il digest mercato per una data e lo pubblica su Telegram.

    Usa --date per pubblicare una data precedente (es. --date 2026-04-23).
    Richiede TELEGRAM_BOT_TOKEN e TELEGRAM_CHAT_ID nelle variabili d'ambiente.
    """
    from datetime import date as date_type
    from media_advisor.digest import DigestGenerationError, format_mercato_report_telegram, generate_mercato_digest
    from media_advisor.telegram.client import TelegramClient, TelegramClientError

    s = _get_settings()
    if not s.openai_api_key:
        typer.echo("Error: OPENAI_API_KEY not set", err=True)
        raise typer.Exit(1)
    if not s.telegram_bot_token or not s.telegram_chat_id:
        typer.echo("Error: TELEGRAM_BOT_TOKEN e TELEGRAM_CHAT_ID devono essere configurati", err=True)
        raise typer.Exit(1)

    try:
        target_date = date_type.fromisoformat(date) if date else date_type.today()
    except ValueError:
        typer.echo(f"Error: formato data non valido '{date}', usa YYYY-MM-DD", err=True)
        raise typer.Exit(1)

    root = _root()

    typer.echo(f"Generazione digest per {target_date.isoformat()}...")
    try:
        digest_text = asyncio.run(generate_mercato_digest(root, target_date, s.openai_api_key))
    except DigestGenerationError as exc:
        typer.echo(f"Errore: digest non valido/non pubblicabile ({exc})", err=True)
        raise typer.Exit(1)

    if not digest_text:
        typer.echo(f"Nessuna indiscrezione trovata per il {target_date.isoformat()}.")
        typer.echo("Suggerimento: verifica che i tip abbiano 'mentioned_at' valorizzato (mercato-enrich-dates).")
        raise typer.Exit(0)

    telegram_content = format_mercato_report_telegram(target_date, digest_text)
    typer.echo(f"Invio su Telegram (chat_id={s.telegram_chat_id})...")
    try:
        result = asyncio.run(
            TelegramClient(
                s.telegram_bot_token,
                chat_id=s.telegram_chat_id,
                thread_id=s.telegram_thread_id,
            ).send_message(telegram_content, parse_mode="HTML")
        )
        typer.echo(f"Pubblicato: {result.chunks_sent} chunk inviati, message_ids={result.message_ids}")
    except TelegramClientError as exc:
        typer.echo(f"Errore Telegram: {exc}", err=True)
        raise typer.Exit(1)


# ---------------------------------------------------------------------------
# db-migrate-from-json
# ---------------------------------------------------------------------------


@app.command("db-migrate-from-json")
def cmd_db_migrate_from_json() -> None:
    """Importa JSON legacy (transcripts, reports, analysis, mercato, channels) nel SQLite locale."""
    from media_advisor.db.repository import (
        migrate_analysis_from_json_tree,
        migrate_channels_from_disk,
        migrate_daily_reports_from_files,
        migrate_mercato_from_disk,
        migrate_transcripts_from_json_tree,
    )
    from media_advisor.db.session import session_scope

    root = _root()
    transcripts_root = root / "data" / "transcripts"
    reports_dir = root / "reports"
    analysis_root = root / "data" / "analysis"
    with session_scope(root) as session:
        t_imp, t_err = migrate_transcripts_from_json_tree(transcripts_root, session)
        r_imp, r_err = migrate_daily_reports_from_files(reports_dir, session)
        a_imp, a_err = migrate_analysis_from_json_tree(analysis_root, session)
        m_counts = migrate_mercato_from_disk(root, session)
        ch_counts = migrate_channels_from_disk(root, session)
    typer.echo(f"transcripts: imported {t_imp}, read errors {t_err}")
    typer.echo(f"daily_reports: imported {r_imp}, read errors {r_err}")
    typer.echo(f"video_analysis: imported {a_imp}, read errors {a_err}")
    typer.echo(f"mercato: {m_counts}")
    typer.echo(f"channels: {ch_counts}")
    typer.echo(f"database: {_get_settings().get_database_url(data_root=root)}")


if __name__ == "__main__":
    app()
