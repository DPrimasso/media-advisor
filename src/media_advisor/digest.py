from __future__ import annotations

from datetime import date, datetime
import heapq
from json import JSONDecodeError
from pathlib import Path
import re

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
_DIGEST_REQUIRED_HEADERS = (
    "✅ Situazioni calde / scenari aperti",
    "🕐 Situazioni da monitorare",
    "🚫 Voci ridimensionate / smentite",
)
_SECTION_EXPECTED_STATE = {
    "✅ Situazioni calde / scenari aperti": "caldo",
    "🕐 Situazioni da monitorare": "monitorare",
    "🚫 Voci ridimensionate / smentite": "smentita",
}
_DIGEST_ITEM_RE = re.compile(
    r"^(?P<player>.+?) \((?P<club>[^)]+)\) - Movimento: (?P<movimento>[^;]+); "
    r"Stato: (?P<stato>caldo|monitorare|smentita); "
    r"Motivo: (?P<motivo>[^;]+); Fonte: (?P<fonte>.+)$"
)

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


class DigestGenerationError(RuntimeError):
    """Raised when the LLM output is not publishable after retries."""


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


def _validate_digest_output(text: str) -> list[str]:
    errors: list[str] = []
    stripped = text.strip()
    if not stripped:
        return ["Digest vuoto."]

    lines = [line.strip() for line in stripped.splitlines() if line.strip()]
    header_positions = {header: [] for header in _DIGEST_REQUIRED_HEADERS}
    for idx, line in enumerate(lines):
        if line in header_positions:
            header_positions[line].append(idx)

    for header in _DIGEST_REQUIRED_HEADERS:
        pos = header_positions[header]
        if not pos:
            errors.append(f"Header mancante: '{header}'.")
        elif len(pos) > 1:
            errors.append(f"Header duplicato: '{header}'.")

    if all(header_positions[h] for h in _DIGEST_REQUIRED_HEADERS):
        ordered_positions = [header_positions[h][0] for h in _DIGEST_REQUIRED_HEADERS]
        if ordered_positions != sorted(ordered_positions):
            errors.append("Ordine sezioni non valido.")

    current_header: str | None = None
    section_item_count = {header: 0 for header in _DIGEST_REQUIRED_HEADERS}
    for line in lines:
        if line in _DIGEST_REQUIRED_HEADERS:
            current_header = line
            continue

        if current_header is None:
            errors.append(f"Testo fuori sezione: '{line}'.")
            continue

        match = _DIGEST_ITEM_RE.match(line)
        if not match:
            errors.append(f"Formato riga non valido: '{line}'.")
            continue

        section_item_count[current_header] += 1
        expected_state = _SECTION_EXPECTED_STATE[current_header]
        actual_state = match.group("stato")
        if actual_state != expected_state:
            errors.append(
                f"Stato '{actual_state}' non coerente con sezione '{current_header}' "
                f"(atteso '{expected_state}')."
            )

        if not match.group("fonte").strip():
            errors.append(f"Fonte vuota nella riga: '{line}'.")

    for header, count in section_item_count.items():
        if count == 0:
            errors.append(f"Sezione vuota: '{header}'.")

    return errors


def _is_valid_digest_output(text: str) -> bool:
    return not _validate_digest_output(text)


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
    if not digest_text:
        raise DigestGenerationError("Output digest vuoto ricevuto dal modello.")

    first_errors = _validate_digest_output(digest_text)
    if not first_errors:
        return digest_text

    retry_messages = messages + [
        {"role": "assistant", "content": digest_text},
        {
            "role": "user",
            "content": (
                "Rigenera il digest da zero in modo completo e pubblicabile. "
                "Correggi tutti i seguenti errori di validazione:\n"
                + "\n".join(f"- {err}" for err in first_errors)
                + "\n\nRispetta rigorosamente formato, ordine sezioni e sintassi riga."
            ),
        },
    ]
    retry_text = await _complete_digest_with_token_retry(client, retry_messages)
    retry_errors = _validate_digest_output(retry_text or "")
    if retry_text and not retry_errors:
        return retry_text

    raise DigestGenerationError(
        "Digest non pubblicabile dopo retry. Errori residui: "
        + "; ".join(retry_errors[:6])
    )
