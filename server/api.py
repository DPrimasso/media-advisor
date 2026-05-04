"""FastAPI server — porting of server/api.ts.

Endpoints:
  GET  /api/pending    — current pending videos
  POST /api/confirm    — confirm videos: append to channel lists + remove from pending
  POST /api/fetch-now  — run fetch-new-videos, return updated pending

In production also serves the Vue.js frontend from web/dist/.
"""

import asyncio
import hashlib
import hmac
import json
import re
import traceback
from contextvars import Token
from datetime import UTC, datetime, timezone
from pathlib import Path
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.exception_handlers import http_exception_handler
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy import text

from media_advisor.config import Settings
from media_advisor.costs import (
    CostRecorder,
    attach_cost_recorder,
    reset_cost_recorder,
    send_personal_cost_report,
)
from media_advisor.db.repository import (
    MERCATO_BLOB_ALIASES,
    fetch_mercato_blob_raw,
    upsert_mercato_blob,
)
from media_advisor.db.session import session_scope
from media_advisor.io.channel_store import (
    load_channels_config_dict,
    load_pending_dict,
    read_channel_video_urls,
    save_pending_dict,
    write_channel_video_urls,
)
from media_advisor.models.channels import ChannelsConfig
from media_advisor.models.pending import PendingResult

app = FastAPI(title="Media Advisor API")

_settings = Settings()
_root = _settings.root_dir.resolve()


def _append_server_error_log(message: str) -> None:
    """Append to logs/server-api-errors.log (HTTP 5xx + unhandled tracebacks)."""
    log_dir = _root / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    path = log_dir / "server-api-errors.log"
    ts = datetime.now(timezone.utc).isoformat()
    with path.open("a", encoding="utf-8") as f:
        f.write(f"\n{'=' * 60}\n{ts}\n{message}\n")


@app.exception_handler(HTTPException)
async def logging_http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    """Log server-side 5xx HTTPException detail (e.g. missing API keys)."""
    if exc.status_code >= 500:
        _append_server_error_log(
            f"[HTTPException] {request.method} {request.url.path}\n"
            f"status={exc.status_code}\ndetail={exc.detail!r}\n"
        )
    return await http_exception_handler(request, exc)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Log tracebacks for unexpected errors (see logs/server-api-errors.log)."""
    if isinstance(exc, HTTPException):
        return await http_exception_handler(request, exc)
    tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    _append_server_error_log(f"[UNHANDLED] {request.method} {request.url.path}\n{tb}")
    return JSONResponse(
        status_code=500,
        content={"detail": f"{type(exc).__name__}: {exc}"},
    )


def _cors_allow_origins() -> list[str]:
    parts = [x.strip() for x in (_settings.cors_origins or "").split(",") if x.strip()]
    return parts if parts else ["*"]


app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_allow_origins(),
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "X-Media-Advisor-Sync"],
)


def _require_sync_secret(
    x_media_advisor_sync: str | None = Header(default=None, alias="X-Media-Advisor-Sync"),
) -> None:
    """If MEDIA_ADVISOR_SYNC_SECRET is set, require matching header (production)."""
    secret = (_settings.sync_secret or "").strip()
    if not secret:
        return
    hdr = (x_media_advisor_sync or "").strip()
    ds = hashlib.sha256(secret.encode("utf-8")).hexdigest()
    dh = hashlib.sha256(hdr.encode("utf-8")).hexdigest()
    if not hmac.compare_digest(ds, dh):
        raise HTTPException(status_code=401, detail="X-Media-Advisor-Sync non valido o assente")


def _check_sqlite_ready() -> None:
    with session_scope(_root, read_only=True) as session:
        session.execute(text("SELECT 1"))


SyncSecretDep = Annotated[None, Depends(_require_sync_secret)]


def _require_transcript_api_key() -> None:
    if not (_settings.transcript_api_key or "").strip():
        raise HTTPException(status_code=500, detail="TRANSCRIPT_API_KEY non configurato")


def _require_pipeline_api_keys() -> None:
    _require_transcript_api_key()
    if not (_settings.openai_api_key or "").strip():
        raise HTTPException(status_code=500, detail="OPENAI_API_KEY non configurato")


TranscriptApiKeyDep = Annotated[None, Depends(_require_transcript_api_key)]
PipelineApiKeysDep = Annotated[None, Depends(_require_pipeline_api_keys)]


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


class PublishTelegramRequest(BaseModel):
    digest: str
    date: str | None = None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@app.get("/api/health")
async def get_health(
    ready: Annotated[int | None, Query(description="Se 1, verifica anche SQLite (SELECT 1)")] = None,
) -> dict[str, str]:
    if ready == 1:
        try:
            _check_sqlite_ready()
        except Exception:
            raise HTTPException(status_code=503, detail="database non pronto")
    return {"status": "ok", "service": "media-advisor"}


@app.get("/api/health/ready")
async def get_health_ready() -> dict[str, str]:
    try:
        _check_sqlite_ready()
    except Exception:
        raise HTTPException(status_code=503, detail="database non pronto")
    return {"status": "ok", "service": "media-advisor", "db": "ok"}


@app.get("/api/pending")
async def get_pending() -> Any:
    return load_pending_dict(_root)


@app.post("/api/confirm", response_model=ConfirmResponse)
async def post_confirm(body: ConfirmRequest) -> ConfirmResponse:
    items: list[ConfirmItem] = []
    if body.items:
        items = body.items
    elif body.channel_id and body.video_ids:
        items = [ConfirmItem(channel_id=body.channel_id, video_id=vid) for vid in body.video_ids]

    if not items:
        raise HTTPException(status_code=400, detail="No items to confirm")

    raw_config = load_channels_config_dict(_root)
    if not raw_config.get("channels"):
        raise HTTPException(status_code=500, detail="channel registry empty (run db-migrate-from-json)")
    config = ChannelsConfig.model_validate(raw_config)
    channel_map = {c.id: c.video_list for c in config.channels}

    to_append: dict[str, list[str]] = {}
    for item in items:
        list_file = channel_map.get(item.channel_id)
        if not list_file:
            continue
        to_append.setdefault(list_file, []).append(
            f"https://www.youtube.com/watch?v={item.video_id}"
        )

    for list_key, urls in to_append.items():
        existing = read_channel_video_urls(_root, list_key)
        existing_ids = {
            vid
            for u in existing
            if (vid := _extract_video_id(u))
        }
        for url in urls:
            vid = _extract_video_id(url)
            if vid and vid not in existing_ids:
                existing.append(url)
                existing_ids.add(vid)
        write_channel_video_urls(_root, list_key, existing)

    confirmed_keys = {f"{i.channel_id}:{i.video_id}" for i in items}
    pending = PendingResult.model_validate(load_pending_dict(_root))
    pending.items = [
        v for v in pending.items
        if f"{v.channel_id}:{v.video_id}" not in confirmed_keys
    ]
    save_pending_dict(_root, pending.model_dump(mode="json"))

    if body.trigger_pipeline:
        asyncio.create_task(_run_pipeline())

    return ConfirmResponse(ok=True, confirmed=len(items))


@app.post("/api/fetch-now")
async def post_fetch_now(
    _auth: SyncSecretDep,
    _keys: TranscriptApiKeyDep,
) -> Any:
    from media_advisor.fetch import run_fetch_new_videos

    result = await run_fetch_new_videos(_root, _settings.transcript_api_key)
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

    valid = {"non_verificata", "confermata", "parziale", "smentita", "non_conclusa"}
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

    from media_advisor.mercato.transfer_db import TransferRecord, add_transfer
    from media_advisor.mercato.transfer_db import player_slug as make_slug

    try:
        confirmed_at = datetime.fromisoformat(body.confirmed_at)
    except ValueError:
        raise HTTPException(status_code=400, detail="confirmed_at deve essere una data ISO (es. 2026-07-01)")
    if confirmed_at.tzinfo is None:
        confirmed_at = confirmed_at.replace(tzinfo=timezone.utc)
    else:
        confirmed_at = confirmed_at.astimezone(timezone.utc)

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
    from media_advisor.mercato.transfer_db import TransferRecord, add_transfer, get_all_transfers
    from media_advisor.mercato.transfer_db import player_slug as make_slug

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
    """Aggiunge un alias giocatore nel blob SQLite player_aliases e invalida la cache."""
    alias = body.alias.strip()
    canonical = body.canonical.strip()
    if not alias or not canonical:
        raise HTTPException(status_code=400, detail="alias e canonical sono obbligatori")

    with session_scope(_root) as session:
        raw = fetch_mercato_blob_raw(session, MERCATO_BLOB_ALIASES)
        data: dict[str, Any]
        if raw:
            try:
                parsed = json.loads(raw)
                data = parsed if isinstance(parsed, dict) else {}
            except json.JSONDecodeError:
                data = {}
        else:
            data = {}

        if "custom" not in data:
            data["custom"] = {"_label": "Alias personalizzati (dashboard)"}
        data["custom"][alias.lower()] = canonical
        upsert_mercato_blob(session, MERCATO_BLOB_ALIASES, data)

    from media_advisor.mercato.player_normalizer import load_player_registry

    load_player_registry.cache_clear()

    return {"ok": True, "alias": alias, "canonical": canonical}


@app.post("/api/mercato/analyze")
async def post_mercato_analyze(body: MercatoAnalyzeRequest) -> Any:
    s = Settings()
    if not s.openai_api_key:
        raise HTTPException(status_code=500, detail="OPENAI_API_KEY non configurato")
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
async def get_feed_digest(date: str | None = None, force: bool = False) -> Any:
    from datetime import date as date_type

    from media_advisor.digest import (
        DigestGenerationError,
        flatten_digest_items_for_api,
        format_mercato_report_markdown,
        generate_mercato_digest,
        hydrate_digest_sections_from_cache,
        load_report_cache,
        write_mercato_report,
    )

    s = Settings()
    if not s.openai_api_key:
        raise HTTPException(status_code=500, detail="OPENAI_API_KEY non configurato")

    try:
        target_date = date_type.fromisoformat(date) if date else date_type.today()
    except ValueError:
        raise HTTPException(status_code=400, detail="Formato data non valido, usa YYYY-MM-DD")

    if not force:
        cached = load_report_cache(_root, target_date)
        if cached and cached.get("digest_raw"):
            digest_text = cached["digest_raw"]
            sections = hydrate_digest_sections_from_cache(
                _root, target_date, digest_text, cached
            )
            digest_formatted = format_mercato_report_markdown(
                target_date,
                digest_text,
                section_items_enriched=sections,
            )
            return {
                "digest": digest_formatted,
                "digest_raw": digest_text,
                "digest_items": flatten_digest_items_for_api(sections),
                "date": target_date.isoformat(),
                "cached": True,
            }

    try:
        digest_text = await generate_mercato_digest(_root, target_date, s.openai_api_key)
    except DigestGenerationError as exc:
        raise HTTPException(status_code=502, detail=f"Digest non pubblicabile: {exc}")
    if not digest_text:
        return {"digest": None, "message": "Nessun contenuto per questa data"}

    now = datetime.now()
    _, digest_formatted, sections = write_mercato_report(
        _root, target_date, digest_text, generated_at=now
    )
    return {
        "digest": digest_formatted,
        "digest_raw": digest_text,
        "digest_items": flatten_digest_items_for_api(sections),
        "date": target_date.isoformat(),
        "cached": False,
    }


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
_YOUTUBE_ID_RE = re.compile(r"v=([a-zA-Z0-9_-]{11})")
_BACKFILL_PER_CHANNEL = 5


def _sync_log(msg: str) -> None:
    _sync_state["log"].append(msg)
    if len(_sync_state["log"]) > _MAX_LOG:
        _sync_state["log"] = _sync_state["log"][-_MAX_LOG:]
    try:
        print(f"[sync] {msg}", flush=True)
    except UnicodeEncodeError:
        print(f"[sync] {msg.encode('ascii', errors='replace').decode()}", flush=True)


async def _finalize_sync_cost_tracking(
    *,
    sync_kind: str,
    recorder: CostRecorder,
    started_at: datetime,
    cost_token: Token,
    settings: Settings,
) -> None:
    """Aggiunge breakdown costi a result + invia Telegram personale (best effort)."""
    finished_at = datetime.now(UTC)
    try:
        cost_payload = recorder.to_result_dict(settings)
        st = str(_sync_state.get("status") or "idle")
        err = _sync_state.get("error")
        err_str = str(err) if err else None
        cost_payload["telegram_personal"] = await send_personal_cost_report(
            sync_kind=sync_kind,
            started_at=started_at,
            finished_at=finished_at,
            recorder=recorder,
            settings=settings,
            status=st,
            error=err_str,
        )
        res = _sync_state.get("result")
        if isinstance(res, dict):
            res["costs"] = cost_payload
        else:
            _sync_state["result"] = {"costs": cost_payload}
    finally:
        reset_cost_recorder(cost_token)


def _extract_video_id(url: str) -> str | None:
    m = _YOUTUBE_ID_RE.search(url)
    return m.group(1) if m else None


def _vid_channel_pairs_having_transcripts(
    root: Path, vid_channel_pairs: list[tuple[str, str]]
) -> list[tuple[str, str]]:
    """Keep only (video_id, channel_id) pairs that exist in the transcript table."""
    if not vid_channel_pairs:
        return []
    from media_advisor.db.repository import transcript_existing_pair_keys
    from media_advisor.db.session import session_scope

    with session_scope(root, read_only=True) as session:
        have = transcript_existing_pair_keys(session, vid_channel_pairs)
    return [(vid, ch_id) for vid, ch_id in vid_channel_pairs if (ch_id, vid) in have]


def _collect_processing_candidates(
    root: Path,
    cfg: ChannelsConfig,
    pending_items: list,
    *,
    include_backfill: bool = True,
) -> tuple[set[str], dict[str, str], int]:
    """Build processing set from fresh pending + optional per-channel backfill.

    When ``include_backfill`` is True, scans each channel list newest-first and adds up to
    ``_BACKFILL_PER_CHANNEL`` videos missing transcript or analysis (recovery of transient misses).

    Sync "recent" and daily-report use ``include_backfill=False`` so only videos discovered
    in this fetch (pending) are processed, not older gaps in lists.
    """
    recent_ids: set[str] = {item.video_id for item in pending_items if item.video_id}
    channel_of: dict[str, str] = {
        item.video_id: item.channel_id for item in pending_items if item.video_id
    }
    backfill_count = 0

    if not include_backfill:
        return recent_ids, channel_of, backfill_count

    from media_advisor.db.repository import analysis_exists_in_db, transcript_exists_in_db
    from media_advisor.db.session import session_scope

    with session_scope(root, read_only=True) as session:
        for channel in cfg.channels:
            urls = read_channel_video_urls(root, channel.video_list)
            added_for_channel = 0
            for url in urls:
                if added_for_channel >= _BACKFILL_PER_CHANNEL:
                    break
                vid = _extract_video_id(url)
                if not vid or vid in channel_of:
                    continue
                if transcript_exists_in_db(session, channel.id, vid) and analysis_exists_in_db(
                    session, channel.id, vid
                ):
                    continue

                recent_ids.add(vid)
                channel_of[vid] = channel.id
                added_for_channel += 1
                backfill_count += 1

    return recent_ids, channel_of, backfill_count


@app.post("/api/sync")
async def post_sync(
    _auth: SyncSecretDep,
    _keys: PipelineApiKeysDep,
) -> Any:
    if _sync_state["status"] == "running":
        raise HTTPException(status_code=409, detail="Sync già in esecuzione")
    asyncio.create_task(_run_full_sync())
    return {"status": "started"}


@app.post("/api/sync/recent")
async def post_sync_recent(
    _auth: SyncSecretDep,
    _keys: PipelineApiKeysDep,
) -> Any:
    if _sync_state["status"] == "running":
        raise HTTPException(status_code=409, detail="Sync già in esecuzione")
    asyncio.create_task(_run_recent_sync())
    return {"status": "started"}


@app.post("/api/sync/daily-report")
async def post_sync_daily_report(
    _auth: SyncSecretDep,
    _keys: PipelineApiKeysDep,
) -> Any:
    if _sync_state["status"] == "running":
        raise HTTPException(status_code=409, detail="Sync già in esecuzione")
    asyncio.create_task(_run_daily_report())
    return {"status": "started"}


@app.post("/api/feed/digest/publish-telegram")
async def post_publish_telegram(body: PublishTelegramRequest) -> Any:
    """Pubblica un digest già generato su Telegram. Riceve { digest, date } dal frontend."""
    from datetime import date as date_type

    from media_advisor.digest import (
        build_enriched_digest_sections,
        format_mercato_report_telegram,
    )
    from media_advisor.mercato.aggregator import get_tips_for_date
    from media_advisor.telegram.client import TelegramClient, TelegramClientError

    digest_text = (body.digest or "").strip()
    date_str = body.date

    if not digest_text:
        raise HTTPException(status_code=400, detail="Campo 'digest' mancante o vuoto")

    s = Settings()
    if not s.telegram_bot_token or not s.telegram_chat_id:
        raise HTTPException(status_code=500, detail="Telegram non configurato (TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID)")

    try:
        target_date = date_type.fromisoformat(date_str) if date_str else date_type.today()
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Data non valida: {date_str}")

    tips = get_tips_for_date(_root, target_date)
    sections, _ = build_enriched_digest_sections(_root, target_date, digest_text, tips=tips)
    telegram_text = format_mercato_report_telegram(
        target_date,
        digest_text,
        generated_at=datetime.now(),
        section_items_enriched=sections,
    )

    try:
        result = await TelegramClient(
            s.telegram_bot_token,
            chat_id=s.telegram_chat_id,
            thread_id=s.telegram_thread_id,
        ).send_message(telegram_text, parse_mode="HTML")
        return {"published": True, "chunks_sent": result.chunks_sent, "message_ids": result.message_ids}
    except TelegramClientError as exc:
        raise HTTPException(status_code=502, detail=f"Telegram error: {exc}")


@app.get("/api/sync/status")
async def get_sync_status() -> Any:
    return _sync_state


async def _scan_mercato_videos(
    root: Path,
    api_key: str,
    vid_channel_pairs: list[tuple[str, str]],
) -> tuple[int, list]:
    """Analyze each (video_id, channel_id) pair for mercato tips. Returns (count, tips)."""
    from media_advisor.db.repository import mercato_existing_pair_keys
    from media_advisor.db.session import session_scope
    from media_advisor.io.channel_store import load_video_dates_dict
    from media_advisor.mercato.analyzer import analyze_video_mercato

    dates_cache: dict = load_video_dates_dict(root)

    with session_scope(root, read_only=True) as session:
        already_mercato: set[tuple[str, str]] = mercato_existing_pair_keys(session, vid_channel_pairs)

    mercato_analyzed = 0
    all_new_tips: list = []
    for vid, ch_id in vid_channel_pairs:
        key = (ch_id, vid)
        if key in already_mercato:
            continue
        try:
            result = await analyze_video_mercato(
                root=root, video_id=vid, channel_id=ch_id, api_key=api_key, dates_cache=dates_cache
            )
            all_new_tips.extend(result.tips)
            mercato_analyzed += 1
            already_mercato.add(key)
            if result.tips:
                _sync_log(f"    [{ch_id}/{vid}] {len(result.tips)} tip estratti")
        except Exception as e:
            _sync_log(f"    [{ch_id}/{vid}] errore: {e}")
    return mercato_analyzed, all_new_tips


async def _run_full_sync() -> None:
    from media_advisor.models.channels import ChannelsConfig

    cost_recorder = CostRecorder()
    cost_token = attach_cost_recorder(cost_recorder)
    cost_started = datetime.now(UTC)

    s = Settings()
    root = _root
    result_summary: dict = {}

    _sync_state.update(
        status="running",
        started_at=datetime.now(UTC).isoformat(),
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
        cfg = ChannelsConfig.model_validate(load_channels_config_dict(root))
        mercato_ids = {c.id for c in cfg.channels if getattr(c, "mercato_channel", False)}
        from media_advisor.db.repository import list_transcript_video_ids
        from media_advisor.db.session import session_scope

        with session_scope(root, read_only=True) as session:
            all_t = list_transcript_video_ids(session, None)
        pairs: list[tuple[str, str]] = [
            (vid, ch_id) for ch_id, vid in all_t if ch_id in mercato_ids
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
            finished_at=datetime.now(UTC).isoformat(),
            result=result_summary,
        )

    except Exception as exc:
        _sync_log(f"Errore: {exc}")
        _sync_state.update(
            status="error",
            finished_at=datetime.now(UTC).isoformat(),
            error=str(exc),
        )
    finally:
        await _finalize_sync_cost_tracking(
            sync_kind="full",
            recorder=cost_recorder,
            started_at=cost_started,
            cost_token=cost_token,
            settings=s,
        )


async def _run_recent_sync() -> None:
    """Sync recenti: fetch+merge come il totale, poi pipeline solo sui video nel pending di questa run.

    Non fa backfill su video vecchi in lista senza analisi (comportamento sync UI / scheduler).
    """
    from media_advisor.models.channels import ChannelsConfig

    cost_recorder = CostRecorder()
    cost_token = attach_cost_recorder(cost_recorder)
    cost_started = datetime.now(UTC)

    s = Settings()
    root = _root
    result_summary: dict = {}

    _sync_state.update(
        status="running",
        started_at=datetime.now(UTC).isoformat(),
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

        cfg = ChannelsConfig.model_validate(load_channels_config_dict(root))

        # Step 3 — Solo video nel pending appena fetchati (nessun backfill liste storiche)
        recent_ids, channel_of, backfill_count = _collect_processing_candidates(
            root, cfg, pending.items, include_backfill=False
        )
        result_summary["recent_pending_analysis"] = len(
            [item for item in pending.items if item.video_id]
        )
        result_summary["backfill_analysis"] = backfill_count

        if not recent_ids:
            _sync_log(
                "Step 3/5: Nessun video nuovo nel pending. Sync recent terminata (backfill disabilitato)."
            )
            _sync_state.update(
                status="done",
                finished_at=datetime.now(UTC).isoformat(),
                result=result_summary,
            )
            return

        from collections import Counter

        _sync_log(
            f"Step 3/5: Pipeline su {len(recent_ids)} video (solo pending fetch, nessun backfill liste)..."
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

        mercato_candidates = [
            (vid, channel_of[vid])
            for vid in recent_ids
            if channel_of.get(vid) in mercato_ch_ids
        ]
        recent_pairs = _vid_channel_pairs_having_transcripts(root, mercato_candidates)
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
            finished_at=datetime.now(UTC).isoformat(),
            result=result_summary,
        )

    except Exception as exc:
        _sync_log(f"Errore: {exc}")
        _sync_state.update(
            status="error",
            finished_at=datetime.now(UTC).isoformat(),
            error=str(exc),
        )
    finally:
        await _finalize_sync_cost_tracking(
            sync_kind="recent",
            recorder=cost_recorder,
            started_at=cost_started,
            cost_token=cost_token,
            settings=s,
        )


async def _run_daily_report() -> None:
    """Fetch recenti → pipeline → mercato-scan → genera digest del giorno."""
    from datetime import date as date_type

    from media_advisor.digest import (
        flatten_digest_items_for_api,
        format_mercato_report_telegram,
        generate_mercato_digest,
        write_mercato_report,
    )
    from media_advisor.models.channels import ChannelsConfig
    from media_advisor.telegram.client import TelegramClient, TelegramClientError

    cost_recorder = CostRecorder()
    cost_token = attach_cost_recorder(cost_recorder)
    cost_started = datetime.now(UTC)

    s = Settings()
    root = _root
    result_summary: dict = {}

    _sync_state.update(
        status="running",
        started_at=datetime.now(UTC).isoformat(),
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

        cfg = ChannelsConfig.model_validate(load_channels_config_dict(root))

        recent_ids, channel_of, backfill_count = _collect_processing_candidates(
            root, cfg, pending.items, include_backfill=False
        )
        result_summary["recent_pending_analysis"] = len(
            [item for item in pending.items if item.video_id]
        )
        result_summary["backfill_analysis"] = backfill_count

        if recent_ids:
            # Step 3 — Pipeline claims sui video nuovi
            _sync_log(
                f"Step 3/6: Pipeline claims su {len(recent_ids)} video (solo pending fetch, nessun backfill)..."
            )
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
            _sync_log("Step 4/6: Mercato scan (video processati in questa run)...")
            mercato_ch_ids = {c.id for c in cfg.channels if getattr(c, "mercato_channel", False)}
            mercato_candidates = [
                (vid, channel_of[vid])
                for vid in recent_ids
                if channel_of.get(vid) in mercato_ch_ids
            ]
            recent_pairs = _vid_channel_pairs_having_transcripts(root, mercato_candidates)
            mercato_analyzed, all_new_tips = await _scan_mercato_videos(root, s.openai_api_key, recent_pairs)
            if all_new_tips:
                from media_advisor.mercato.analyzer import update_index_with_new_tips
                update_index_with_new_tips(root, all_new_tips)
            _sync_log(f"  mercato: {mercato_analyzed} video, {len(all_new_tips)} tip estratti")
            result_summary["mercato_analyzed"] = mercato_analyzed
            result_summary["mercato_tips"] = len(all_new_tips)
        else:
            _sync_log(
                "Step 3-4/6: Nessun video nel pending di questa run, salto pipeline e mercato-scan (backfill disabilitato)."
            )
            result_summary.update(analyzed=0, failed=0, mercato_analyzed=0, mercato_tips=0)

        today = date_type.today()
        # Step 5 — Genera digest
        _sync_log("Step 5/6: Generazione sommario mercato...")
        digest_text = await generate_mercato_digest(root, today, s.openai_api_key)
        report_content: str | None = None
        telegram_content: str | None = None
        if digest_text:
            generated_at = datetime.now()
            report_file, report_content, section_enriched = write_mercato_report(
                root,
                today,
                digest_text,
                generated_at=generated_at,
            )
            telegram_content = format_mercato_report_telegram(
                today,
                digest_text,
                generated_at=generated_at,
                section_items_enriched=section_enriched,
            )
            _sync_log(f"  Sommario generato ({len(digest_text)} caratteri), salvato in {report_file.name}")
            result_summary["digest"] = report_content
            result_summary["digest_raw"] = digest_text
            result_summary["digest_items"] = flatten_digest_items_for_api(section_enriched)
        else:
            _sync_log("  Nessun tip con data per oggi — sommario non generato.")
            _sync_log("  Suggerimento: esegui 'mercato-enrich-dates' per popolare le date dei tip.")
            result_summary["digest"] = None

        # Step 6 — Publish Telegram (non bloccante)
        telegram_enabled = bool(s.telegram_bot_token and s.telegram_chat_id)
        telegram_result: dict[str, Any] = {
            "published": False,
            "chunks_sent": 0,
            "message_ids": [],
            "error": None,
            "enabled": telegram_enabled,
        }
        result_summary["telegram"] = telegram_result

        if telegram_content is None:
            _sync_log("Step 6/6: Salto publish Telegram (digest assente).")
        elif not telegram_enabled:
            _sync_log("Step 6/6: Telegram non configurato, publish saltato.")
        else:
            _sync_log("Step 6/6: Pubblicazione report su Telegram...")
            try:
                tg_send = await TelegramClient(
                    s.telegram_bot_token,
                    chat_id=s.telegram_chat_id,
                    thread_id=s.telegram_thread_id,
                ).send_message(telegram_content, parse_mode="HTML")
                telegram_result["published"] = tg_send.chunks_sent > 0
                telegram_result["chunks_sent"] = tg_send.chunks_sent
                telegram_result["message_ids"] = tg_send.message_ids
                _sync_log(
                    f"  Telegram publish OK: {tg_send.chunks_sent} chunk inviati"
                )
            except Exception as exc:
                telegram_result["error"] = str(exc)
                if isinstance(exc, (TelegramClientError, ValueError)):
                    _sync_log(f"  WARNING Telegram publish fallito (non bloccante): {exc}")
                else:
                    _sync_log(
                        "  WARNING Telegram publish fallito con errore inatteso "
                        f"(non bloccante): {exc}"
                    )

        _sync_log("Report giornaliero completato.")
        _sync_state.update(
            status="done",
            finished_at=datetime.now(UTC).isoformat(),
            result=result_summary,
        )

    except Exception as exc:
        _sync_log(f"Errore: {exc}")
        _sync_state.update(
            status="error",
            finished_at=datetime.now(UTC).isoformat(),
            error=str(exc),
        )
    finally:
        await _finalize_sync_cost_tracking(
            sync_kind="daily-report",
            recorder=cost_recorder,
            started_at=cost_started,
            cost_token=cost_token,
            settings=s,
        )


# ---------------------------------------------------------------------------
# Static files (Vue frontend from web/dist)
# ---------------------------------------------------------------------------

_web_dist = (_root / "web" / "dist").resolve()
_index_html = (_web_dist / "index.html").resolve()

if _web_dist.exists() and _index_html.is_file():
    app.mount("/assets", StaticFiles(directory=str(_web_dist / "assets")), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_fallback(full_path: str) -> FileResponse:
        try:
            candidate = (_web_dist / full_path).resolve()
            candidate.relative_to(_web_dist)
        except ValueError:
            return FileResponse(str(_index_html))
        if candidate.is_file():
            return FileResponse(str(candidate))
        return FileResponse(str(_index_html))


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import os

    import uvicorn

    # Default 3002 to match npm run server / Vite proxy; override with PORT.
    _port = int(os.environ.get("PORT", "3002"))
    uvicorn.run(app, host="0.0.0.0", port=_port)
