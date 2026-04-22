"""FastAPI server — porting of server/api.ts.

Endpoints:
  GET  /api/pending    — current pending videos
  POST /api/confirm    — confirm videos: append to channel lists + remove from pending
  POST /api/fetch-now  — run fetch-new-videos, return updated pending

In production also serves the Vue.js frontend from web/dist/.
"""

import asyncio
import re
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from media_advisor.config import Settings
from media_advisor.io.json_io import read_json, read_json_or_default, write_json, read_video_list, write_video_list
from media_advisor.io.paths import channels_config_path, channel_list_path, pending_path
from media_advisor.models.channels import ChannelsConfig
from media_advisor.models.pending import PendingResult

app = FastAPI(title="Media Advisor API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type"],
)

_settings = Settings()
_root = _settings.root_dir.resolve()


# ---------------------------------------------------------------------------
# Request/response models
# ---------------------------------------------------------------------------


class ConfirmItem(BaseModel):
    channel_id: str
    video_id: str


class ConfirmRequest(BaseModel):
    items: list[ConfirmItem] | None = None
    channel_id: str | None = None
    video_ids: list[str] | None = None
    trigger_pipeline: bool = False


class ConfirmResponse(BaseModel):
    ok: bool
    confirmed: int


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@app.get("/api/pending")
async def get_pending() -> Any:
    path = pending_path(_root)
    data = read_json_or_default(path, default={"fetched_at": None, "items": []})
    return data


@app.post("/api/confirm", response_model=ConfirmResponse)
async def post_confirm(body: ConfirmRequest) -> ConfirmResponse:
    items: list[ConfirmItem] = []
    if body.items:
        items = body.items
    elif body.channel_id and body.video_ids:
        items = [ConfirmItem(channel_id=body.channel_id, video_id=vid) for vid in body.video_ids]

    if not items:
        raise HTTPException(status_code=400, detail="No items to confirm")

    config_path = channels_config_path(_root)
    raw_config = read_json_or_default(config_path)
    if raw_config is None:
        raise HTTPException(status_code=500, detail="channels.json not found")
    config = ChannelsConfig.model_validate(raw_config)
    channel_map = {c.id: c.video_list for c in config.channels}

    # Group by list file
    to_append: dict[Path, list[str]] = {}
    for item in items:
        list_file = channel_map.get(item.channel_id)
        if not list_file:
            continue
        list_path = channel_list_path(_root, list_file)
        if not list_path.exists():
            continue
        to_append.setdefault(list_path, []).append(
            f"https://www.youtube.com/watch?v={item.video_id}"
        )

    for list_path, urls in to_append.items():
        existing = read_video_list(list_path)
        existing_ids = {
            m.group(1)
            for u in existing
            if (m := re.search(r"v=([a-zA-Z0-9_-]{11})", u))
        }
        for url in urls:
            m = re.search(r"v=([a-zA-Z0-9_-]{11})", url)
            if m and m.group(1) not in existing_ids:
                existing.append(url)
                existing_ids.add(m.group(1))
        write_video_list(list_path, existing)

    # Remove confirmed from pending
    confirmed_keys = {f"{i.channel_id}:{i.video_id}" for i in items}
    ppath = pending_path(_root)
    raw_pending = read_json_or_default(ppath)
    if raw_pending is not None:
        pending = PendingResult.model_validate(raw_pending)
        pending.items = [
            v for v in pending.items
            if f"{v.channel_id}:{v.video_id}" not in confirmed_keys
        ]
        write_json(ppath, pending.model_dump(mode="json"))

    if body.trigger_pipeline:
        asyncio.create_task(_run_pipeline())

    return ConfirmResponse(ok=True, confirmed=len(items))


@app.post("/api/fetch-now")
async def post_fetch_now() -> Any:
    s = Settings()
    if not s.transcript_api_key:
        raise HTTPException(status_code=500, detail="TRANSCRIPT_API_KEY not set")
    from media_advisor.fetch import run_fetch_new_videos
    result = await run_fetch_new_videos(_root, s.transcript_api_key)
    return result.model_dump(mode="json")


# ---------------------------------------------------------------------------
# Mercato endpoints
# ---------------------------------------------------------------------------


class OutcomeRequest(BaseModel):
    outcome: str   # "non_verificata" | "confermata" | "parziale" | "smentita"
    notes: str | None = None
    source: str = "manual"


class SetDateRequest(BaseModel):
    date: str   # ISO date string es. "2026-04-07"


class MercatoAnalyzeRequest(BaseModel):
    video_id: str
    channel_id: str


class AddTransferRequest(BaseModel):
    player_name: str
    from_club: str | None = None
    to_club: str
    transfer_type: str = "unknown"
    season: str
    confirmed_at: str           # ISO date string es. "2026-07-01"
    source_url: str | None = None
    notes: str | None = None


class FetchTransfersRequest(BaseModel):
    player_name: str
    season: str | None = None   # es. "2025" (anno di inizio)


class AddAliasRequest(BaseModel):
    alias: str       # nome sbagliato (come appare nella UI)
    canonical: str   # nome corretto da usare


def _enrich_tips(tips: list, all_tips: list) -> list[dict]:
    """Aggiunge le 4 categorie di tip correlate a ogni tip dict."""
    from media_advisor.mercato.aggregator import build_tip_context
    context = build_tip_context(all_tips)
    _empty: dict = {
        "same_channel_consistent": [],
        "same_channel_inconsistent": [],
        "other_channel_confirming": [],
        "other_channel_contradicting": [],
    }
    result = []
    for t in tips:
        d = t.model_dump(mode="json")
        ctx = context.get(t.tip_id, _empty)
        d["same_channel_consistent"] = ctx["same_channel_consistent"]
        d["same_channel_inconsistent"] = ctx["same_channel_inconsistent"]
        d["other_channel_confirming"] = ctx["other_channel_confirming"]
        d["other_channel_contradicting"] = ctx["other_channel_contradicting"]
        result.append(d)
    return result


_SEASONS: dict[str, tuple[str, str]] = {
    "estate-2025":  ("2025-06-01", "2025-08-31"),
    "inverno-2026": ("2026-01-01", "2026-02-28"),
    "estate-2026":  ("2026-06-01", "2026-08-31"),
    "inverno-2027": ("2027-01-01", "2027-02-28"),
}


@app.get("/api/mercato/seasons")
async def get_mercato_seasons() -> Any:
    """Restituisce le stagioni disponibili con le date di riferimento."""
    return [
        {"id": k, "label": k.replace("-", " ").title(), "from": v[0], "to": v[1]}
        for k, v in _SEASONS.items()
    ]


@app.get("/api/mercato/tips")
async def get_mercato_tips(
    player: str | None = None,
    channel: str | None = None,
    outcome: str | None = None,
    season: str | None = None,
) -> Any:
    from datetime import date
    from media_advisor.mercato.aggregator import get_all_tips
    all_tips = get_all_tips(_root)
    tips = all_tips
    if player:
        tips = [t for t in tips if player.lower() in t.player_name.lower()]
    if channel:
        tips = [t for t in tips if t.channel_id == channel]
    if outcome:
        tips = [t for t in tips if t.outcome == outcome]
    if season and season in _SEASONS:
        date_from = date.fromisoformat(_SEASONS[season][0])
        date_to = date.fromisoformat(_SEASONS[season][1])
        tips = [
            t for t in tips
            if t.mentioned_at and date_from <= t.mentioned_at.date() <= date_to
        ]
    from datetime import datetime, timezone
    _epoch = datetime.min.replace(tzinfo=timezone.utc)
    tips_sorted = sorted(tips, key=lambda t: t.mentioned_at or _epoch, reverse=True)
    return _enrich_tips(tips_sorted, all_tips)


@app.get("/api/mercato/players")
async def get_mercato_players() -> Any:
    from media_advisor.mercato.aggregator import get_all_players
    players = get_all_players(_root)
    # Non includere le tips complete nella lista, solo il summary
    return [
        {k: v for k, v in p.model_dump(mode="json").items() if k != "tips"}
        for p in players
    ]


@app.get("/api/mercato/players/{player_slug}")
async def get_mercato_player(player_slug: str) -> Any:
    from media_advisor.mercato.aggregator import get_all_tips, get_tips_for_player
    player = get_tips_for_player(_root, player_slug)
    if player is None:
        raise HTTPException(status_code=404, detail="Giocatore non trovato")
    all_tips = get_all_tips(_root)
    d = player.model_dump(mode="json")
    d["tips"] = _enrich_tips(player.tips, all_tips)
    return d


@app.get("/api/mercato/channels/stats")
async def get_mercato_channel_stats() -> Any:
    from media_advisor.mercato.aggregator import get_channel_stats
    stats = get_channel_stats(_root)
    return [s.model_dump(mode="json") for s in stats]


@app.post("/api/mercato/tip/{tip_id}/outcome")
async def post_mercato_outcome(tip_id: str, body: OutcomeRequest) -> Any:
    from typing import cast

    from media_advisor.mercato.analyzer import update_tip_outcome
    from media_advisor.mercato.models import OutcomeValue

    valid = {"non_verificata", "confermata", "parziale", "smentita"}
    if body.outcome not in valid:
        raise HTTPException(status_code=400, detail=f"outcome deve essere: {valid}")

    try:
        update_tip_outcome(_root, tip_id, cast(OutcomeValue, body.outcome), body.notes, body.source)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return {"ok": True, "tip_id": tip_id, "outcome": body.outcome}


@app.post("/api/mercato/tip/{tip_id}/date")
async def post_mercato_set_date(tip_id: str, body: SetDateRequest) -> Any:
    """Imposta la data di pubblicazione (mentioned_at) di una tip senza data."""
    from datetime import datetime, timezone
    from media_advisor.mercato.analyzer import update_tip_date

    try:
        dt = datetime.strptime(body.date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        raise HTTPException(status_code=400, detail="Formato data non valido, usa YYYY-MM-DD")

    try:
        update_tip_date(_root, tip_id, dt)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return {"ok": True, "tip_id": tip_id, "mentioned_at": dt.isoformat()}


@app.post("/api/mercato/tip/{tip_id}/verify")
async def post_mercato_verify_tip(tip_id: str) -> Any:
    """Verifica una singola tip contro il database trasferimenti."""
    from media_advisor.mercato.verifier import verify_single_tip
    result = verify_single_tip(_root, tip_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Tip non trovata")
    return result


@app.post("/api/mercato/verify")
async def post_mercato_verify_all() -> Any:
    """Verifica tutte le tip non_verificata contro il database trasferimenti."""
    from media_advisor.mercato.verifier import verify_all_pending
    updated = verify_all_pending(_root)
    return {"ok": True, "updated": len(updated), "results": updated}


@app.get("/api/mercato/transfers")
async def get_mercato_transfers(player: str | None = None) -> Any:
    """Lista tutti i trasferimenti ufficiali nel database."""
    from media_advisor.mercato.transfer_db import get_all_transfers
    transfers = get_all_transfers(_root)
    if player:
        transfers = [t for t in transfers if player.lower() in t.player_name.lower()]
    transfers_sorted = sorted(transfers, key=lambda t: t.confirmed_at, reverse=True)
    return [t.model_dump(mode="json") for t in transfers_sorted]


@app.post("/api/mercato/transfers")
async def post_mercato_add_transfer(body: AddTransferRequest) -> Any:
    """Aggiunge un trasferimento confermato manualmente."""
    from datetime import datetime, timezone

    from media_advisor.mercato.transfer_db import TransferRecord, add_transfer, player_slug as make_slug

    try:
        confirmed_at = datetime.fromisoformat(body.confirmed_at).replace(tzinfo=timezone.utc)
    except ValueError:
        raise HTTPException(status_code=400, detail="confirmed_at deve essere una data ISO (es. 2026-07-01)")

    record = TransferRecord(
        player_name=body.player_name,
        player_slug=make_slug(body.player_name),
        from_club=body.from_club,
        to_club=body.to_club,
        transfer_type=body.transfer_type,  # type: ignore[arg-type]
        season=body.season,
        confirmed_at=confirmed_at,
        source="manual",
        source_url=body.source_url,
        notes=body.notes,
    )
    saved = add_transfer(_root, record)

    # Avvia verifica automatica in background per le tip di questo giocatore
    from media_advisor.mercato.verifier import verify_all_pending
    verify_all_pending(_root)

    return saved.model_dump(mode="json")


@app.delete("/api/mercato/transfers/{transfer_id}")
async def delete_mercato_transfer(transfer_id: str) -> Any:
    """Rimuove un trasferimento dal database."""
    from media_advisor.mercato.transfer_db import remove_transfer
    found = remove_transfer(_root, transfer_id)
    if not found:
        raise HTTPException(status_code=404, detail="Trasferimento non trovato")
    return {"ok": True, "transfer_id": transfer_id}


@app.post("/api/mercato/transfers/fetch")
async def post_mercato_fetch_transfers(body: FetchTransfersRequest) -> Any:
    """Scarica i trasferimenti di un giocatore da Transfermarkt e li salva."""
    from media_advisor.mercato.scraper import ScraperError, fetch_player_transfers
    from media_advisor.mercato.transfer_db import TransferRecord, add_transfer, get_all_transfers, player_slug as make_slug

    try:
        raw = fetch_player_transfers(body.player_name, body.season)
    except ScraperError as e:
        raise HTTPException(status_code=502, detail=str(e))

    if not raw:
        return {"ok": True, "added": 0, "message": "Nessun trasferimento trovato su Transfermarkt"}

    # Evita duplicati: confronta player_slug + to_club + season
    existing = get_all_transfers(_root)
    existing_keys = {(t.player_slug, t.to_club or "", t.season) for t in existing}

    added = []
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
        add_transfer(_root, record)
        existing_keys.add(key)
        added.append(record.model_dump(mode="json"))

    # Verifica automatica dopo aver aggiunto i nuovi trasferimenti
    from media_advisor.mercato.verifier import verify_all_pending
    verify_all_pending(_root)

    return {"ok": True, "added": len(added), "transfers": added}


@app.post("/api/mercato/aliases")
async def add_player_alias(body: AddAliasRequest) -> Any:
    """Aggiunge un alias giocatore a player-aliases.json e invalida la cache."""
    import json as json_mod

    alias = body.alias.strip()
    canonical = body.canonical.strip()
    if not alias or not canonical:
        raise HTTPException(status_code=400, detail="alias e canonical sono obbligatori")

    aliases_path = _root / "mercato" / "player-aliases.json"
    if aliases_path.exists():
        data: dict = json_mod.loads(aliases_path.read_text(encoding="utf-8"))
    else:
        data = {}

    if "custom" not in data:
        data["custom"] = {"_label": "Alias personalizzati (dashboard)"}
    data["custom"][alias.lower()] = canonical

    aliases_path.write_text(
        json_mod.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    from media_advisor.mercato.player_normalizer import load_player_registry
    load_player_registry.cache_clear()

    return {"ok": True, "alias": alias, "canonical": canonical}


@app.post("/api/mercato/analyze")
async def post_mercato_analyze(body: MercatoAnalyzeRequest) -> Any:
    s = Settings()
    if not s.openai_api_key:
        raise HTTPException(status_code=500, detail="OPENAI_API_KEY not set")
    from media_advisor.mercato.analyzer import analyze_video_mercato
    result = await analyze_video_mercato(
        root=_root,
        video_id=body.video_id,
        channel_id=body.channel_id,
        api_key=s.openai_api_key,
    )
    return result.model_dump(mode="json")


# ---------------------------------------------------------------------------
# Feed digest
# ---------------------------------------------------------------------------


@app.get("/api/feed/digest")
async def get_feed_digest(date: str | None = None) -> Any:
    from datetime import date as date_type
    from media_advisor.digest import generate_mercato_digest

    s = Settings()
    if not s.openai_api_key:
        raise HTTPException(status_code=500, detail="OPENAI_API_KEY non configurato")

    try:
        target_date = date_type.fromisoformat(date) if date else date_type.today()
    except ValueError:
        raise HTTPException(status_code=400, detail="Formato data non valido, usa YYYY-MM-DD")

    digest_text = await generate_mercato_digest(_root, target_date, s.openai_api_key)
    if not digest_text:
        return {"digest": None, "message": "Nessun contenuto per questa data"}
    return {"digest": digest_text, "date": target_date.isoformat()}


# ---------------------------------------------------------------------------
# Background pipeline trigger
# ---------------------------------------------------------------------------


async def _run_pipeline() -> None:
    s = Settings()
    if not s.transcript_api_key or not s.openai_api_key:
        return
    from media_advisor.run_pipeline import run_from_list
    await run_from_list(
        root=_root,
        transcript_api_key=s.transcript_api_key,
        openai_api_key=s.openai_api_key,
    )


# ---------------------------------------------------------------------------
# Full sync (fetch → merge → pipeline → mercato scan)
# ---------------------------------------------------------------------------

from datetime import datetime, timezone as _tz

_sync_state: dict = {
    "status": "idle",          # "idle" | "running" | "done" | "error"
    "started_at": None,
    "finished_at": None,
    "log": [],                 # list of strings, last N messages
    "result": None,            # summary dict when done
    "error": None,
    "progress": None,          # None | {total, current, channel}
}

_MAX_LOG = 40


def _sync_log(msg: str) -> None:
    _sync_state["log"].append(msg)
    if len(_sync_state["log"]) > _MAX_LOG:
        _sync_state["log"] = _sync_state["log"][-_MAX_LOG:]
    try:
        print(f"[sync] {msg}", flush=True)
    except UnicodeEncodeError:
        print(f"[sync] {msg.encode('ascii', errors='replace').decode()}", flush=True)


@app.post("/api/sync")
async def post_sync() -> Any:
    if _sync_state["status"] == "running":
        raise HTTPException(status_code=409, detail="Sync già in esecuzione")
    s = Settings()
    if not s.transcript_api_key:
        raise HTTPException(status_code=500, detail="TRANSCRIPT_API_KEY non configurato")
    if not s.openai_api_key:
        raise HTTPException(status_code=500, detail="OPENAI_API_KEY non configurato")
    asyncio.create_task(_run_full_sync())
    return {"status": "started"}


@app.post("/api/sync/recent")
async def post_sync_recent() -> Any:
    if _sync_state["status"] == "running":
        raise HTTPException(status_code=409, detail="Sync già in esecuzione")
    s = Settings()
    if not s.transcript_api_key:
        raise HTTPException(status_code=500, detail="TRANSCRIPT_API_KEY non configurato")
    if not s.openai_api_key:
        raise HTTPException(status_code=500, detail="OPENAI_API_KEY non configurato")
    asyncio.create_task(_run_recent_sync())
    return {"status": "started"}


@app.post("/api/sync/daily-report")
async def post_sync_daily_report() -> Any:
    if _sync_state["status"] == "running":
        raise HTTPException(status_code=409, detail="Sync già in esecuzione")
    s = Settings()
    if not s.transcript_api_key:
        raise HTTPException(status_code=500, detail="TRANSCRIPT_API_KEY non configurato")
    if not s.openai_api_key:
        raise HTTPException(status_code=500, detail="OPENAI_API_KEY non configurato")
    asyncio.create_task(_run_daily_report())
    return {"status": "started"}


@app.get("/api/sync/status")
async def get_sync_status() -> Any:
    return _sync_state


async def _scan_mercato_videos(
    root: Path,
    api_key: str,
    vid_channel_pairs: list[tuple[str, str]],
) -> tuple[int, list]:
    """Analyze each (video_id, channel_id) pair for mercato tips. Returns (count, tips)."""
    from media_advisor.io.paths import mercato_tips_path
    from media_advisor.mercato.analyzer import analyze_video_mercato

    mercato_analyzed = 0
    all_new_tips: list = []
    for vid, ch_id in vid_channel_pairs:
        if mercato_tips_path(root, ch_id, vid).exists():
            continue
        try:
            result = await analyze_video_mercato(root=root, video_id=vid, channel_id=ch_id, api_key=api_key)
            all_new_tips.extend(result.tips)
            mercato_analyzed += 1
            if result.tips:
                _sync_log(f"    [{ch_id}/{vid}] {len(result.tips)} tip estratti")
        except Exception as e:
            _sync_log(f"    [{ch_id}/{vid}] errore: {e}")
    return mercato_analyzed, all_new_tips


async def _run_full_sync() -> None:
    from media_advisor.models.channels import ChannelsConfig

    s = Settings()
    root = _root
    result_summary: dict = {}

    _sync_state.update(
        status="running",
        started_at=datetime.now(_tz.utc).isoformat(),
        finished_at=None,
        log=[],
        result=None,
        error=None,
        progress=None,
    )

    try:
        # Step 1 — Fetch nuovi video
        _sync_log("Step 1/4: Recupero nuovi video dai canali...")
        from media_advisor.fetch import run_fetch_new_videos
        pending = await run_fetch_new_videos(root, s.transcript_api_key)
        n_new = len(pending.items)
        _sync_log(f"  {n_new} nuovi video trovati")
        result_summary["new_videos"] = n_new

        if n_new == 0:
            _sync_log("Nessun nuovo video. Verifico transcript/analisi mancanti...")

        # Step 2 — Merge in channel lists
        _sync_log("Step 2/4: Aggiungo video alle liste canale...")
        from media_advisor.merge import merge_pending_into_channels
        added = merge_pending_into_channels(root)
        _sync_log(f"  {added} video aggiunti alle liste")
        result_summary["added_to_lists"] = added

        # Step 3 — Transcript + analisi claims
        _sync_log("Step 3/4: Transcript e analisi claims (tutti i canali)...")
        from media_advisor.run_pipeline import run_from_list
        pipeline_result = await run_from_list(
            root=root,
            transcript_api_key=s.transcript_api_key,
            openai_api_key=s.openai_api_key,
        )
        total_transcripts = sum(c.transcripts_fetched for c in pipeline_result.channels)
        total_analyzed = sum(c.analyzed for c in pipeline_result.channels)
        total_failed = sum(c.failed for c in pipeline_result.channels)
        _sync_log(f"  transcript={total_transcripts} analizzati={total_analyzed} falliti={total_failed}")
        for ch in pipeline_result.channels:
            if ch.transcripts_fetched or ch.analyzed:
                _sync_log(f"  [{ch.id}] transcript={ch.transcripts_fetched} analizzati={ch.analyzed}")
        result_summary["transcripts"] = total_transcripts
        result_summary["analyzed"] = total_analyzed
        result_summary["failed"] = total_failed

        # Step 4 — Mercato scan sui canali mercato
        _sync_log("Step 4/4: Mercato scan (canali mercato)...")
        cfg_raw = read_json(channels_config_path(root))
        cfg = ChannelsConfig.model_validate(cfg_raw)
        mercato_channels = [c for c in cfg.channels if getattr(c, "mercato_channel", False)]

        pairs: list[tuple[str, str]] = [
            (t_file.stem, ch.id)
            for ch in mercato_channels
            if (root / "data" / "transcripts" / ch.id).exists()
            for t_file in sorted((root / "data" / "transcripts" / ch.id).glob("*.json"))
        ]
        mercato_analyzed, all_new_tips = await _scan_mercato_videos(root, s.openai_api_key, pairs)

        if all_new_tips:
            _sync_log(f"  Aggiornamento index mercato con {len(all_new_tips)} nuovi tip...")
            from media_advisor.mercato.analyzer import update_index_with_new_tips
            update_index_with_new_tips(root, all_new_tips)

        _sync_log(f"  mercato: {mercato_analyzed} video analizzati, {len(all_new_tips)} tip estratti")
        result_summary["mercato_analyzed"] = mercato_analyzed
        result_summary["mercato_tips"] = len(all_new_tips)

        _sync_log("Sincronizzazione completata.")
        _sync_state.update(
            status="done",
            finished_at=datetime.now(_tz.utc).isoformat(),
            result=result_summary,
        )

    except Exception as exc:
        _sync_log(f"Errore: {exc}")
        _sync_state.update(
            status="error",
            finished_at=datetime.now(_tz.utc).isoformat(),
            error=str(exc),
        )


async def _run_recent_sync() -> None:
    """Sync recenti: fetch+merge come il totale, poi pipeline solo sui video appena scoperti in questa run.

    Non processa backlog senza analisi (quello resta a POST /api/sync). Se il fetch non trova
    nulla di nuovo, termina senza chiamare transcript.
    """
    from media_advisor.io.paths import transcript_path as _tp
    from media_advisor.models.channels import ChannelsConfig

    s = Settings()
    root = _root
    result_summary: dict = {}

    _sync_state.update(
        status="running",
        started_at=datetime.now(_tz.utc).isoformat(),
        finished_at=None,
        log=[],
        result=None,
        error=None,
        progress=None,
    )

    try:
        # Step 1 — Stesso fetch del sync totale: nuovi upload → pending.json
        _sync_log("Step 1/5: Recupero nuovi video dai canali (come sync totale)...")
        from media_advisor.fetch import run_fetch_new_videos

        pending = await run_fetch_new_videos(root, s.transcript_api_key)
        n_fetched_new = len(pending.items)
        _sync_log(f"  {n_fetched_new} nuovi video trovati dall'API")
        result_summary["new_videos"] = n_fetched_new

        # Step 2 — Merge nelle liste canale (newest-first: prepend in merge)
        _sync_log("Step 2/5: Aggiungo video alle liste canale...")
        from media_advisor.merge import merge_pending_into_channels

        added = merge_pending_into_channels(root)
        _sync_log(f"  {added} video aggiunti alle liste")
        result_summary["added_to_lists"] = added

        cfg_raw = read_json(channels_config_path(root))
        cfg = ChannelsConfig.model_validate(cfg_raw)

        # Step 3 — Solo i video in pending di questa run (dopo merge sono già in lista)
        recent_ids: set[str] = set()
        channel_of: dict[str, str] = {}
        for item in pending.items:
            if not item.video_id:
                continue
            recent_ids.add(item.video_id)
            channel_of[item.video_id] = item.channel_id

        result_summary["recent_pending_analysis"] = len(recent_ids)

        if not recent_ids:
            _sync_log(
                "Step 3/5: Nessun video nuovo in questa run. Per transcript/analisi arretrati usa sync totale."
            )
            _sync_state.update(
                status="done",
                finished_at=datetime.now(_tz.utc).isoformat(),
                result=result_summary,
            )
            return

        from collections import Counter

        _sync_log(
            f"Step 3/5: Pipeline solo sui {len(recent_ids)} video nuovi di questa run (non il backlog)..."
        )
        for ch_id, n in sorted(Counter(channel_of[v] for v in recent_ids).items()):
            _sync_log(f"  [{ch_id}] {n} da processare")

        total_to_process = len(recent_ids)
        _sync_log(f"  → {total_to_process} video da processare in totale")

        # Inizializza progress tracker
        _sync_state["progress"] = {"total": total_to_process, "current": 0, "channel": ""}

        def _progress_cb(ch_id: str, vid: str) -> None:
            _sync_state["progress"]["current"] += 1
            _sync_state["progress"]["channel"] = ch_id

        # Step 4 — Transcript + analisi claims solo su recent_ids
        _sync_log("Step 4/5: Transcript e analisi claims (solo coda recenti)...")
        from media_advisor.run_pipeline import run_from_list

        pipeline_result = await run_from_list(
            root=root,
            transcript_api_key=s.transcript_api_key,
            openai_api_key=s.openai_api_key,
            only_video_ids=recent_ids,
            progress_callback=_progress_cb,
        )
        total_transcripts = sum(c.transcripts_fetched for c in pipeline_result.channels)
        total_analyzed = sum(c.analyzed for c in pipeline_result.channels)
        total_failed = sum(c.failed for c in pipeline_result.channels)
        _sync_state["progress"]["channel"] = ""
        _sync_log(f"  transcript={total_transcripts} analizzati={total_analyzed} falliti={total_failed}")
        for ch in pipeline_result.channels:
            if ch.transcripts_fetched or ch.analyzed:
                _sync_log(f"  [{ch.id}] transcript={ch.transcripts_fetched} analizzati={ch.analyzed}")
        result_summary["transcripts"] = total_transcripts
        result_summary["analyzed"] = total_analyzed
        result_summary["failed"] = total_failed

        # Step 5 — Mercato scan sui video recenti dei canali mercato
        _sync_log("Step 5/5: Mercato scan (video recenti)...")
        mercato_ch_ids = {c.id for c in cfg.channels if getattr(c, "mercato_channel", False)}

        recent_pairs = [
            (vid, channel_of[vid])
            for vid in recent_ids
            if channel_of.get(vid) in mercato_ch_ids and _tp(root, channel_of[vid], vid).exists()
        ]
        mercato_analyzed, all_new_tips = await _scan_mercato_videos(root, s.openai_api_key, recent_pairs)

        if all_new_tips:
            _sync_log(f"  Aggiornamento index mercato con {len(all_new_tips)} nuovi tip...")
            from media_advisor.mercato.analyzer import update_index_with_new_tips
            update_index_with_new_tips(root, all_new_tips)

        _sync_log(f"  mercato: {mercato_analyzed} video analizzati, {len(all_new_tips)} tip estratti")
        result_summary["mercato_analyzed"] = mercato_analyzed
        result_summary["mercato_tips"] = len(all_new_tips)

        _sync_log("Sincronizzazione recenti completata.")
        _sync_state.update(
            status="done",
            finished_at=datetime.now(_tz.utc).isoformat(),
            result=result_summary,
        )

    except Exception as exc:
        _sync_log(f"Errore: {exc}")
        _sync_state.update(
            status="error",
            finished_at=datetime.now(_tz.utc).isoformat(),
            error=str(exc),
        )


async def _run_daily_report() -> None:
    """Fetch recenti → pipeline → mercato-scan → genera digest del giorno."""
    from datetime import date as date_type
    from media_advisor.io.paths import transcript_path as _tp
    from media_advisor.models.channels import ChannelsConfig
    from media_advisor.digest import generate_mercato_digest, MONTHS_IT

    s = Settings()
    root = _root
    result_summary: dict = {}

    _sync_state.update(
        status="running",
        started_at=datetime.now(_tz.utc).isoformat(),
        finished_at=None,
        log=[],
        result=None,
        error=None,
        progress=None,
    )

    try:
        # Step 1 — Fetch nuovi video
        _sync_log("Step 1/6: Recupero nuovi video dai canali...")
        from media_advisor.fetch import run_fetch_new_videos
        pending = await run_fetch_new_videos(root, s.transcript_api_key)
        n_fetched_new = len(pending.items)
        _sync_log(f"  {n_fetched_new} nuovi video trovati")
        result_summary["new_videos"] = n_fetched_new

        # Step 2 — Merge nelle liste canale
        _sync_log("Step 2/6: Aggiungo video alle liste canale...")
        from media_advisor.merge import merge_pending_into_channels
        added = merge_pending_into_channels(root)
        _sync_log(f"  {added} video aggiunti")
        result_summary["added_to_lists"] = added

        cfg_raw = read_json(channels_config_path(root))
        cfg = ChannelsConfig.model_validate(cfg_raw)

        recent_ids: set[str] = {v.video_id for v in pending.items if v.video_id}
        channel_of: dict[str, str] = {v.video_id: v.channel_id for v in pending.items if v.video_id}

        if recent_ids:
            # Step 3 — Pipeline claims sui video nuovi
            _sync_log(f"Step 3/6: Pipeline claims su {len(recent_ids)} video nuovi...")
            from media_advisor.run_pipeline import run_from_list
            pipeline_result = await run_from_list(
                root=root,
                transcript_api_key=s.transcript_api_key,
                openai_api_key=s.openai_api_key,
                only_video_ids=recent_ids,
            )
            total_analyzed = sum(c.analyzed for c in pipeline_result.channels)
            total_failed = sum(c.failed for c in pipeline_result.channels)
            _sync_log(f"  analizzati={total_analyzed} falliti={total_failed}")
            result_summary["analyzed"] = total_analyzed
            result_summary["failed"] = total_failed

            # Step 4 — Mercato scan sui video nuovi dei canali mercato
            _sync_log("Step 4/6: Mercato scan (video nuovi)...")
            mercato_ch_ids = {c.id for c in cfg.channels if getattr(c, "mercato_channel", False)}
            recent_pairs = [
                (vid, channel_of[vid])
                for vid in recent_ids
                if channel_of.get(vid) in mercato_ch_ids and _tp(root, channel_of[vid], vid).exists()
            ]
            mercato_analyzed, all_new_tips = await _scan_mercato_videos(root, s.openai_api_key, recent_pairs)
            if all_new_tips:
                from media_advisor.mercato.analyzer import update_index_with_new_tips
                update_index_with_new_tips(root, all_new_tips)
            _sync_log(f"  mercato: {mercato_analyzed} video, {len(all_new_tips)} tip estratti")
            result_summary["mercato_analyzed"] = mercato_analyzed
            result_summary["mercato_tips"] = len(all_new_tips)
        else:
            _sync_log("Step 3-4/6: Nessun video nuovo, salto pipeline e mercato-scan.")
            result_summary.update(analyzed=0, failed=0, mercato_analyzed=0, mercato_tips=0)

        today = date_type.today()
        reports_dir = root / "reports"
        reports_dir.mkdir(exist_ok=True)

        # Step 5 — Genera digest
        _sync_log("Step 5/6: Generazione sommario mercato...")
        digest_text = await generate_mercato_digest(root, today, s.openai_api_key)
        if digest_text:
            date_it = f"{today.day} {MONTHS_IT[today.month]} {today.year}"
            now_str = datetime.now().strftime("%H:%M del %d/%m/%Y")
            md_content = (
                f"# Calciomercato — {date_it}\n\n"
                f"{digest_text}\n\n"
                f"---\n_Generato da Media Advisor alle {now_str}_\n"
            )
            report_file = reports_dir / f"{today.isoformat()}.md"
            report_file.write_text(md_content, encoding="utf-8")
            _sync_log(f"  Sommario generato ({len(digest_text)} caratteri), salvato in {report_file.name}")
            result_summary["digest"] = digest_text
        else:
            _sync_log("  Nessun tip con data per oggi — sommario non generato.")
            _sync_log("  Suggerimento: esegui 'mercato-enrich-dates' per popolare le date dei tip.")
            result_summary["digest"] = None

        _sync_log("Report giornaliero completato.")
        _sync_state.update(
            status="done",
            finished_at=datetime.now(_tz.utc).isoformat(),
            result=result_summary,
        )

    except Exception as exc:
        _sync_log(f"Errore: {exc}")
        _sync_state.update(
            status="error",
            finished_at=datetime.now(_tz.utc).isoformat(),
            error=str(exc),
        )


# ---------------------------------------------------------------------------
# Static files (Vue frontend from web/dist)
# ---------------------------------------------------------------------------

_web_dist = _root / "web" / "dist"
_index_html = _web_dist / "index.html"

if _web_dist.exists() and _index_html.exists():
    app.mount("/assets", StaticFiles(directory=str(_web_dist / "assets")), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_fallback(full_path: str) -> FileResponse:
        static = _web_dist / full_path
        if static.exists() and static.is_file():
            return FileResponse(str(static))
        return FileResponse(str(_index_html))


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    # On Windows, `reload=True` requires an import string and can be fragile
    # depending on how Python is launched. We prefer a reliable default here.
    #
    # If you want reload in dev, run explicitly:
    #   uvicorn server.api:app --reload --port 3001 --app-dir .
    uvicorn.run(app, host="0.0.0.0", port=3001)
