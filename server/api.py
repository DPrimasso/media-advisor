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
    outcome: str   # "true" | "false" | "partial"
    notes: str | None = None


class MercatoAnalyzeRequest(BaseModel):
    video_id: str
    channel_id: str


@app.get("/api/mercato/tips")
async def get_mercato_tips(
    player: str | None = None,
    channel: str | None = None,
    outcome: str | None = None,
) -> Any:
    from media_advisor.mercato.aggregator import get_all_tips
    tips = get_all_tips(_root)
    if player:
        tips = [t for t in tips if player.lower() in t.player_name.lower()]
    if channel:
        tips = [t for t in tips if t.channel_id == channel]
    if outcome:
        tips = [t for t in tips if t.outcome == outcome]
    tips_sorted = sorted(tips, key=lambda t: t.mentioned_at, reverse=True)
    return [t.model_dump(mode="json") for t in tips_sorted]


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
    from media_advisor.mercato.aggregator import get_tips_for_player
    player = get_tips_for_player(_root, player_slug)
    if player is None:
        raise HTTPException(status_code=404, detail="Giocatore non trovato")
    return player.model_dump(mode="json")


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

    valid = {"true", "false", "partial"}
    if body.outcome not in valid:
        raise HTTPException(status_code=400, detail=f"outcome deve essere: {valid}")

    try:
        update_tip_outcome(_root, tip_id, cast(OutcomeValue, body.outcome), body.notes)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return {"ok": True, "tip_id": tip_id, "outcome": body.outcome}


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
