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
from media_advisor.io.json_io import read_json_or_default, write_json, read_video_list, write_video_list
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


@app.get("/api/mercato/tips")
async def get_mercato_tips(
    player: str | None = None,
    channel: str | None = None,
    outcome: str | None = None,
) -> Any:
    from media_advisor.mercato.aggregator import get_all_tips
    all_tips = get_all_tips(_root)
    tips = all_tips
    if player:
        tips = [t for t in tips if player.lower() in t.player_name.lower()]
    if channel:
        tips = [t for t in tips if t.channel_id == channel]
    if outcome:
        tips = [t for t in tips if t.outcome == outcome]
    tips_sorted = sorted(tips, key=lambda t: t.mentioned_at, reverse=True)
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
    uvicorn.run("server.api:app", host="0.0.0.0", port=3001, reload=True)
