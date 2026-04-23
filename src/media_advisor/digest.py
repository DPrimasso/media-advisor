from __future__ import annotations

from datetime import date, datetime
import heapq
from json import JSONDecodeError
from pathlib import Path

import openai
from pydantic import ValidationError
from media_advisor.io.json_io import read_json
from media_advisor.io.paths import channels_config_path
from media_advisor.models.channels import ChannelsConfig

DIGEST_MODEL = "gpt-4.1-mini"
DIGEST_TOKEN_STEPS = (900, 1500)
DIGEST_MAX_INPUT_TIPS = 20
DIGEST_MAX_TIP_TEXT_CHARS = 220

_CONFIDENCE_ORDER = {"confirmed": 0, "likely": 1, "rumor": 2, "denied": 3}
_CONFIDENCE_EMOJI = {
    "confirmed": "✅",
    "likely": "🔵",
    "rumor": "🔴",
    "denied": "❌",
}
MONTHS_IT = [
    "", "Gennaio", "Febbraio", "Marzo", "Aprile", "Maggio", "Giugno",
    "Luglio", "Agosto", "Settembre", "Ottobre", "Novembre", "Dicembre",
]

_SYSTEM_PROMPT = (
    "Sei il redattore di una rassegna calciomercato italiana. "
    "Ricevi indiscrezioni giornaliere con fonte e livello di confidenza. "
    "Genera un digest pronto pubblicazione, con stile giornalistico asciutto e struttura rigida.\n"
    "Regole editoriali obbligatorie:\n"
    "1. NON inserire titolo, data, saluti, hashtag o testo introduttivo/finale.\n"
    "2. Usa la piramide inversa: ogni riga deve aprire con il fatto principale, poi dettaglio minimo.\n"
    "3. Una notizia per riga, frasi brevi, verbi attivi, lessico uniforme e concreto.\n"
    "4. Evita formule vaghe o rumorose (es: 'si vedra', 'tutto puo cambiare', 'situazione da monitorare' ripetuta uguale).\n"
    "5. NON inventare dettagli, NON cambiare squadre o nomi, NON omettere voci dell'input.\n"
    "6. Usa SEMPRE e SOLO queste tre sezioni, in questo ordine e con intestazione identica:\n"
    "   ✅ Situazioni calde / scenari aperti\n"
    "   🕐 Situazioni da monitorare\n"
    "   🚫 Voci ridimensionate / smentite\n"
    "7. Assegnazione sezioni: confermate/probabili -> sezione 1; rumor iniziali -> sezione 2; smentite/ridimensionate -> sezione 3.\n"
    "8. Ogni voce deve rispettare ESATTAMENTE questo formato su singola riga:\n"
    "   'Giocatore (Club) - Movimento: <azione sintetica>; Stato: <caldo|monitorare|smentita>; Motivo: <perche in 3-8 parole>; Fonte: <nome fonte>'.\n"
    "9. Il campo Fonte e sempre obbligatorio e deve usare solo il prefisso 'Fonte:'.\n"
    "10. Mantieni output completo: nessuna sezione mancante, nessuna riga tronca."
)


def _truncate_tip_text(text: str, max_chars: int = DIGEST_MAX_TIP_TEXT_CHARS) -> str:
    if len(text) <= max_chars:
        return text
    truncated = text[: max_chars - 1].rsplit(" ", 1)[0].strip()
    return (truncated or text[: max_chars - 1].strip()) + "…"


def _format_date_it(value: date) -> str:
    return f"{value.day} {MONTHS_IT[value.month]} {value.year}"


def format_mercato_report_markdown(
    target_date: date,
    digest_text: str,
    generated_at: datetime | None = None,
) -> str:
    generated = generated_at or datetime.now()
    date_it = _format_date_it(target_date)
    now_str = generated.strftime("%H:%M del %d/%m/%Y")
    return (
        f"# Calciomercato — {date_it}\n\n"
        f"{digest_text.strip()}\n\n"
        f"---\n_Generato da Media Advisor alle {now_str}_\n"
    )


def write_mercato_report(
    root: Path,
    target_date: date,
    digest_text: str,
    generated_at: datetime | None = None,
) -> tuple[Path, str]:
    report_path = root / "reports" / f"{target_date.isoformat()}.md"
    report_path.parent.mkdir(exist_ok=True)
    content = format_mercato_report_markdown(target_date, digest_text, generated_at=generated_at)
    report_path.write_text(content, encoding="utf-8")
    return report_path, content


def _load_channel_name_map(root: Path) -> dict[str, str]:
    try:
        raw = read_json(channels_config_path(root))
        cfg = ChannelsConfig.model_validate(raw)
        return {channel.id: channel.name for channel in cfg.channels}
    except (FileNotFoundError, JSONDecodeError, OSError, ValidationError):
        return {}


def _is_valid_digest_output(text: str) -> bool:
    required_headers = (
        "✅ Situazioni calde / scenari aperti",
        "🕐 Situazioni da monitorare",
        "🚫 Voci ridimensionate / smentite",
    )
    stripped = text.strip()
    if not stripped:
        return False
    if any(header not in stripped for header in required_headers):
        return False

    lines = [line.strip() for line in stripped.splitlines() if line.strip()]
    news_lines = [line for line in lines if line not in required_headers]
    if not news_lines:
        return False
    return all("Fonte: " in line and line.split("Fonte: ", 1)[1].strip() for line in news_lines)


async def _complete_digest_with_token_retry(
    client: openai.AsyncOpenAI,
    messages: list[dict[str, str]],
) -> str | None:
    last_text: str | None = None
    for max_tokens in DIGEST_TOKEN_STEPS:
        completion = await client.chat.completions.create(
            model=DIGEST_MODEL,
            messages=messages,
            max_tokens=max_tokens,
            temperature=0.4,
        )
        choice = completion.choices[0]
        text = (choice.message.content or "").strip()
        if text:
            last_text = text
        if text and choice.finish_reason != "length":
            return text
    return last_text


async def generate_mercato_digest(
    root: Path,
    target_date: date,
    openai_api_key: str,
) -> str | None:
    """Genera un sommario mercato per la data indicata. Restituisce None se non ci sono tips."""
    from media_advisor.mercato.aggregator import get_tips_for_date

    day_tips = get_tips_for_date(root, target_date)
    if not day_tips:
        return None

    channel_names = _load_channel_name_map(root)
    day_tips = heapq.nsmallest(
        DIGEST_MAX_INPUT_TIPS,
        day_tips,
        key=lambda t: _CONFIDENCE_ORDER.get(str(t.confidence), 99),
    )

    lines: list[str] = []
    for tip in day_tips:
        emoji = _CONFIDENCE_EMOJI.get(str(tip.confidence), "🔴")
        source = channel_names.get(tip.channel_id, tip.channel_id)
        route = f" ({tip.from_club or '?'} → {tip.to_club or '?'})" if (tip.from_club or tip.to_club) else ""
        tip_text = _truncate_tip_text(tip.tip_text)
        lines.append(f"{emoji} FONTE: {source} | {tip.player_name}{route}: {tip_text}")

    client = openai.AsyncOpenAI(api_key=openai_api_key)
    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": f"Indiscrezioni del {_format_date_it(target_date)}:\n\n" + "\n".join(lines)},
    ]
    digest_text = await _complete_digest_with_token_retry(client, messages)
    if digest_text and _is_valid_digest_output(digest_text):
        return digest_text
    if digest_text:
        retry_messages = messages + [
            {"role": "assistant", "content": digest_text},
            {
                "role": "user",
                "content": (
                    "Rigenera il sommario completo senza troncare righe finali. "
                    "Mantieni esattamente le 3 sezioni richieste e la fonte su ogni voce."
                ),
            },
        ]
        retry_text = await _complete_digest_with_token_retry(client, retry_messages)
        if retry_text and _is_valid_digest_output(retry_text):
            return retry_text
    return digest_text
