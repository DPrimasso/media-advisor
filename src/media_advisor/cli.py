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
) -> None:
    """Scansiona i transcript già scaricati e analizza quelli con titolo mercato."""
    import re as _re

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

    transcripts_root = root / "transcripts"
    if not transcripts_root.exists():
        typer.echo("Nessun transcript trovato.")
        return

    channel_dirs = (
        [transcripts_root / channel] if channel else list(transcripts_root.iterdir())
    )

    async def _run() -> None:
        from media_advisor.mercato.analyzer import update_index_with_new_tips
        from media_advisor.mercato.models import MercatoTip

        # Cache latest results per channel (one API call per channel).
        latest_cache: dict[str, list[dict]] = {}

        def _get_channel_url(ch_id: str) -> str | None:
            try:
                cfg = ChannelsConfig.model_validate(read_json(root / "channels" / "channels.json"))
                ch = next((c for c in cfg.channels if c.id == ch_id), None)
                return (ch.fetch_rule.channel_url if ch and ch.fetch_rule else None)  # type: ignore[attr-defined]
            except Exception:
                return None

        async def _ensure_metadata(ch_id: str, vid: str) -> None:
            t_path = transcript_path(root, ch_id, vid)
            if not t_path.exists():
                return
            raw = read_json(t_path)
            tr = TranscriptResponse.model_validate(raw)
            if tr.metadata and tr.metadata.published_at:
                return
            channel_url = _get_channel_url(ch_id)
            if not channel_url:
                return
            if ch_id not in latest_cache:
                client = TranscriptClient(s.transcript_api_key)
                data = await client.get_channel_latest(channel_url)
                latest_cache[ch_id] = data.get("results", []) if isinstance(data, dict) else []
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
            for t_file in sorted(ch_dir.glob("*.json")):
                vid = t_file.stem
                total += 1
                try:
                    data = read_json(t_file)
                    title = (data.get("metadata") or {}).get("title") or ""
                    if not _MERCATO_KW.search(title):
                        skipped += 1
                        continue
                    await _ensure_metadata(ch_id, vid)
                    result = await analyze_video_mercato(
                        root=root,
                        video_id=vid,
                        channel_id=ch_id,
                        api_key=s.openai_api_key,
                        model=model,
                        force=force,
                        update_index=False,  # batch: aggiorna index una sola volta alla fine
                    )
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
    outcome: str = typer.Argument(..., help="non_verificata | confermata | parziale | smentita"),
    notes: Optional[str] = typer.Option(None, "--notes", help="Note sull'esito"),
) -> None:
    """Marca manualmente l'esito di un'indiscrezione di mercato."""
    from typing import cast

    from media_advisor.mercato.analyzer import update_tip_outcome
    from media_advisor.mercato.models import OutcomeValue

    valid: set[str] = {"non_verificata", "confermata", "parziale", "smentita"}
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
    typer.echo(f"✓ Trasferimento aggiunto: {saved.player_name} → {saved.to_club} ({saved.transfer_type})")

    # Verifica automatica
    from media_advisor.mercato.verifier import verify_all_pending
    updated = verify_all_pending(_root())
    if updated:
        typer.echo(f"  → {len(updated)} tip aggiornate automaticamente:")
        for u in updated:
            typer.echo(f"    {u['player_name']} → {u['to_club']}: {u['outcome']}")


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
        raw = fetch_player_transfers(player, season)
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
        typer.echo(f"  + {record.player_name} → {record.to_club} ({record.transfer_type}, {record.season})")

    typer.echo(f"\n{added_count} trasferimento/i aggiunto/i.")

    from media_advisor.mercato.verifier import verify_all_pending
    updated = verify_all_pending(_root())
    if updated:
        typer.echo(f"{len(updated)} tip aggiornate:")
        for u in updated:
            typer.echo(f"  {u['player_name']} → {u['to_club']}: {u['outcome']}")


# ---------------------------------------------------------------------------
# mercato-verify
# ---------------------------------------------------------------------------


@app.command("mercato-verify")
def cmd_mercato_verify() -> None:
    """Verifica tutte le tip non_verificata contro il database trasferimenti."""
    from media_advisor.mercato.verifier import verify_all_pending

    typer.echo("Verifica tip in corso...")
    updated = verify_all_pending(_root())
    if not updated:
        typer.echo("Nessuna tip aggiornata (nessun trasferimento nel database o nessuna tip non_verificata).")
        return
    typer.echo(f"{len(updated)} tip aggiornate:")
    for u in updated:
        typer.echo(f"  {u['player_name']} → {u['to_club']}: {u['outcome']}")


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


if __name__ == "__main__":
    app()
