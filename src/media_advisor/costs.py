"""Rilevamento costi per run (contextvars) + report Telegram HTML."""

from __future__ import annotations

import html as html_lib
from collections import defaultdict
from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from media_advisor.config import Settings

_recorder_ctx: ContextVar[CostRecorder | None] = ContextVar(
    "media_advisor_cost_recorder", default=None
)


def get_cost_recorder() -> CostRecorder | None:
    return _recorder_ctx.get()


def attach_cost_recorder(recorder: CostRecorder) -> Token:
    """Imposta il recorder per il task corrente; restituisce token per reset()."""
    return _recorder_ctx.set(recorder)


def reset_cost_recorder(token: Token) -> None:
    _recorder_ctx.reset(token)


@dataclass
class ModelOpenAIUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    requests: int = 0
    requests_missing_usage: int = 0


@dataclass
class CostRecorder:
    """Accumulator per una singola run (sync / pipeline)."""

    openai_by_model: dict[str, ModelOpenAIUsage] = field(
        default_factory=lambda: defaultdict(ModelOpenAIUsage)
    )
    transcript_paid_by_endpoint: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    transcript_free_by_endpoint: dict[str, int] = field(default_factory=lambda: defaultdict(int))

    def record_openai_tokens(self, model: str, input_tokens: int, output_tokens: int) -> None:
        m = self.openai_by_model[model]
        m.input_tokens += max(0, input_tokens)
        m.output_tokens += max(0, output_tokens)
        m.requests += 1

    def record_openai_request_missing_usage(self, model: str) -> None:
        m = self.openai_by_model[model]
        m.requests_missing_usage += 1
        m.requests += 1

    def record_transcript_paid(self, endpoint: str) -> None:
        self.transcript_paid_by_endpoint[endpoint] += 1

    def record_transcript_free(self, endpoint: str) -> None:
        self.transcript_free_by_endpoint[endpoint] += 1

    def totals_openai(self) -> tuple[int, int, int]:
        inp = sum(u.input_tokens for u in self.openai_by_model.values())
        out = sum(u.output_tokens for u in self.openai_by_model.values())
        req = sum(u.requests for u in self.openai_by_model.values())
        return inp, out, req

    def estimated_openai_usd(self, settings: Settings) -> float | None:
        pin = settings.openai_input_usd_per_1m
        pout = settings.openai_output_usd_per_1m
        if pin is None and pout is None:
            return None
        total = 0.0
        pin_f = float(pin) if pin is not None else 0.0
        pout_f = float(pout) if pout is not None else 0.0
        for u in self.openai_by_model.values():
            total += (u.input_tokens / 1_000_000.0) * pin_f
            total += (u.output_tokens / 1_000_000.0) * pout_f
        return total

    def estimated_transcript_usd(self, settings: Settings) -> float | None:
        rate = settings.transcript_api_usd_per_paid_call
        if rate is None:
            return None
        n = sum(self.transcript_paid_by_endpoint.values())
        return float(rate) * n

    def to_result_dict(self, settings: Settings) -> dict[str, Any]:
        inp, out, req = self.totals_openai()
        paid_calls = sum(self.transcript_paid_by_endpoint.values())
        free_calls = sum(self.transcript_free_by_endpoint.values())
        o_usd = self.estimated_openai_usd(settings)
        t_usd = self.estimated_transcript_usd(settings)
        total_usd: float | None = (
            None if o_usd is None and t_usd is None else (o_usd or 0.0) + (t_usd or 0.0)
        )

        by_model: dict[str, Any] = {}
        for name, u in sorted(self.openai_by_model.items()):
            by_model[name] = {
                "input_tokens": u.input_tokens,
                "output_tokens": u.output_tokens,
                "requests": u.requests,
                "requests_missing_usage": u.requests_missing_usage,
            }

        return {
            "openai": {
                "total_input_tokens": inp,
                "total_output_tokens": out,
                "total_requests": req,
                "by_model": by_model,
                "estimated_usd": o_usd,
            },
            "transcript_api": {
                "paid_calls": paid_calls,
                "paid_by_endpoint": dict(self.transcript_paid_by_endpoint),
                "free_calls": free_calls,
                "free_by_endpoint": dict(self.transcript_free_by_endpoint),
                "estimated_usd": t_usd,
            },
            "estimated_total_usd": total_usd,
            "pricing_configured": {
                "openai_input_usd_per_1m": settings.openai_input_usd_per_1m is not None,
                "openai_output_usd_per_1m": settings.openai_output_usd_per_1m is not None,
                "transcript_api_usd_per_paid_call": settings.transcript_api_usd_per_paid_call
                is not None,
            },
        }


def record_openai_chat_completion(model: str, completion: Any) -> None:
    rec = get_cost_recorder()
    if rec is None:
        return
    usage = getattr(completion, "usage", None)
    if usage is None:
        rec.record_openai_request_missing_usage(model)
        return
    pt = int(getattr(usage, "prompt_tokens", 0) or 0)
    ct = int(getattr(usage, "completion_tokens", 0) or 0)
    if pt == 0 and ct == 0:
        rec.record_openai_request_missing_usage(model)
        return
    rec.record_openai_tokens(model, pt, ct)


def record_pydantic_ai_run_usage(model: str, run_usage: Any) -> None:
    """Somma token da pydantic_ai.usage.RunUsage (o compat)."""
    rec = get_cost_recorder()
    if rec is None:
        return
    inp = int(getattr(run_usage, "input_tokens", 0) or 0)
    out = int(getattr(run_usage, "output_tokens", 0) or 0)
    nreq = int(getattr(run_usage, "requests", 0) or 0)
    req_count = max(1, nreq)
    m = rec.openai_by_model[model]
    if inp == 0 and out == 0:
        m.requests_missing_usage += req_count
        m.requests += req_count
        return
    m.input_tokens += inp
    m.output_tokens += out
    m.requests += req_count


def format_cost_report_telegram_html(
    *,
    sync_kind: str,
    started_at: datetime,
    finished_at: datetime,
    recorder: CostRecorder,
    settings: Settings,
    status: str,
    error: str | None = None,
) -> str:
    """Messaggio HTML per Telegram (parse_mode=HTML)."""

    def esc(x: object) -> str:
        return html_lib.escape(str(x), quote=True)

    dur_s = (finished_at - started_at).total_seconds()
    summary = recorder.to_result_dict(settings)
    inp = summary["openai"]["total_input_tokens"]
    out_t = summary["openai"]["total_output_tokens"]
    o_req = summary["openai"]["total_requests"]
    paid = summary["transcript_api"]["paid_calls"]
    free = summary["transcript_api"]["free_calls"]

    lines: list[str] = [
        "💸 <b>Media Advisor — costi sync</b>",
        f"<i>{esc(sync_kind)}</i> · stato: <b>{esc(status)}</b>",
        f"⏱ {esc(started_at.strftime('%Y-%m-%d %H:%M:%S'))} → {esc(finished_at.strftime('%H:%M:%S'))} "
        f"({dur_s:.1f}s)",
        "",
        "<b>OpenAI</b>",
        f"• richieste: {o_req} · prompt tok: {inp} · completion tok: {out_t}",
    ]

    by_model = summary["openai"]["by_model"]
    if by_model:
        lines.append("<i>Per modello:</i>")
        for name, row in by_model.items():
            miss = row.get("requests_missing_usage") or 0
            extra = f" · ⚠️ senza usage: {miss}" if miss else ""
            lines.append(
                f"  • <code>{esc(name)}</code>: in={row['input_tokens']} out={row['output_tokens']} req={row['requests']}{extra}"
            )

    o_usd = summary["openai"]["estimated_usd"]
    if o_usd is not None:
        lines.append(f"• stima USD: <b>${o_usd:.4f}</b>")
    else:
        lines.append("• stima USD: <i>non configurata</i> (MEDIA_ADVISOR_OPENAI_*_USD_PER_1M)")

    lines.extend(
        [
            "",
            "<b>Transcript API</b>",
            f"• chiamate a pagamento: {paid} {esc(str(summary['transcript_api']['paid_by_endpoint']))}",
            f"• chiamate free (es. /channel/latest): {free} {esc(str(summary['transcript_api']['free_by_endpoint']))}",
        ]
    )
    t_usd = summary["transcript_api"]["estimated_usd"]
    if t_usd is not None:
        lines.append(f"• stima USD (solo paid): <b>${t_usd:.4f}</b>")
    else:
        lines.append(
            "• stima USD: <i>non configurata</i> (MEDIA_ADVISOR_TRANSCRIPT_API_USD_PER_CALL)"
        )

    tot = summary["estimated_total_usd"]
    lines.append("")
    if tot is not None:
        lines.append(f"<b>Totale stimato (run):</b> ${tot:.4f} USD")
    else:
        lines.append("<b>Totale stimato:</b> <i>configura almeno una tariffa in .env</i>")

    if error:
        lines.extend(["", f"⚠️ <b>Errore sync</b>: {esc(error[:500])}"])

    return "\n".join(lines)


async def send_personal_cost_report(
    *,
    sync_kind: str,
    started_at: datetime,
    finished_at: datetime,
    recorder: CostRecorder,
    settings: Settings,
    status: str,
    error: str | None = None,
) -> dict[str, Any]:
    """Invia report costi sulla chat personale; non solleva (restituisce esito)."""
    out: dict[str, Any] = {
        "enabled": False,
        "sent": False,
        "chunks_sent": 0,
        "message_ids": [],
        "error": None,
    }
    chat = (settings.telegram_personal_chat_id or "").strip()
    if not (settings.telegram_bot_token and chat):
        return out
    out["enabled"] = True
    text = format_cost_report_telegram_html(
        sync_kind=sync_kind,
        started_at=started_at,
        finished_at=finished_at,
        recorder=recorder,
        settings=settings,
        status=status,
        error=error,
    )
    try:
        from media_advisor.telegram.client import TelegramClient

        result = await TelegramClient(
            settings.telegram_bot_token,
            chat_id=chat,
            thread_id=settings.telegram_personal_thread_id,
        ).send_message(text, parse_mode="HTML")
        out["sent"] = result.chunks_sent > 0
        out["chunks_sent"] = result.chunks_sent
        out["message_ids"] = result.message_ids
    except Exception as exc:
        out["error"] = str(exc)
    return out
