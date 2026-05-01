from __future__ import annotations

from datetime import date, datetime
import heapq
import html as _html_lib
import json as _json
from json import JSONDecodeError
from pathlib import Path
import re
import unicodedata

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
_DIGEST_SECTION_ICONS = {
    _DIGEST_REQUIRED_HEADERS[0]: "🔥",
    _DIGEST_REQUIRED_HEADERS[1]: "👀",
    _DIGEST_REQUIRED_HEADERS[2]: "🧊",
}
_DIGEST_SECTION_LABELS_TELEGRAM = {
    _DIGEST_REQUIRED_HEADERS[0]: "✅ <b>CALDE</b>",
    _DIGEST_REQUIRED_HEADERS[1]: "🕐 <b>DA MONITORARE</b>",
    _DIGEST_REQUIRED_HEADERS[2]: "🚫 <b>RIDIMENSIONATE</b>",
}
_DIGEST_SECTION_LABELS_TWITTER = {
    _DIGEST_REQUIRED_HEADERS[0]: "🔥 CALDE",
    _DIGEST_REQUIRED_HEADERS[1]: "👀 MONITORARE",
    _DIGEST_REQUIRED_HEADERS[2]: "🧊 RIDIMENSIONATE",
}
_DIGEST_SMENTITA_HEADER = _DIGEST_REQUIRED_HEADERS[2]
_DIGEST_HEADERS_BY_CANONICAL = {
    "situazionicaldescenariaperti": "✅ Situazioni calde / scenari aperti",
    "situazionidamonitorare": "🕐 Situazioni da monitorare",
    "vociridimensionatesmentite": "🚫 Voci ridimensionate / smentite",
}
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
    "10. Se due o piu input parlano della stessa notizia (stesso giocatore e stesso scenario), scrivi UNA sola riga fusa.\n"
    "11. Quando fondi notizie simili, nel campo Fonte elenca tutte le fonti separate da virgola.\n"
    "12. Mantieni output completo: nessuna sezione mancante, nessuna riga tronca."
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


def _normalize_token(value: str | None) -> str:
    if not value:
        return ""
    ascii_value = (
        unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    )
    return re.sub(r"[^a-z0-9]", "", ascii_value.lower())


def _canonical_digest_header(line: str) -> str | None:
    cleaned = re.sub(r"^[^A-Za-zÀ-ÖØ-öø-ÿ]+", "", line.strip())
    canonical = _normalize_token(cleaned)
    return _DIGEST_HEADERS_BY_CANONICAL.get(canonical)


def _names_are_similar(a: str | None, b: str | None) -> bool:
    sa = _normalize_token(a)
    sb = _normalize_token(b)
    if not sa or not sb:
        return False
    if sa == sb:
        return True
    if min(len(sa), len(sb)) >= 4 and (sa in sb or sb in sa):
        return True
    return False


def _is_normalized_name_match(sa: str, sb: str) -> bool:
    if not sa or not sb:
        return False
    if sa == sb:
        return True
    return min(len(sa), len(sb)) >= 4 and (sa in sb or sb in sa)


def _tip_story_signature(tip) -> dict[str, object]:
    return {
        "player": _normalize_token(tip.player_name),
        "to_club": _normalize_token(tip.to_club),
        "from_club": _normalize_token(tip.from_club),
        "is_renewal": tip.transfer_type in {"extension", "renewal"},
    }


def _is_same_tip_story(signature_a: dict[str, object], signature_b: dict[str, object]) -> bool:
    player_a = str(signature_a["player"])
    player_b = str(signature_b["player"])
    if not _is_normalized_name_match(player_a, player_b):
        return False

    if bool(signature_a["is_renewal"]) != bool(signature_b["is_renewal"]):
        return False

    to_a = str(signature_a["to_club"])
    to_b = str(signature_b["to_club"])
    if to_a and to_b:
        return _is_normalized_name_match(to_a, to_b)

    from_a = str(signature_a["from_club"])
    from_b = str(signature_b["from_club"])
    if from_a and from_b:
        return _is_normalized_name_match(from_a, from_b)

    known_a = [club for club in (to_a, from_a) if club]
    known_b = [club for club in (to_b, from_b) if club]
    if not known_a or not known_b:
        return True
    return any(_is_normalized_name_match(ca, cb) for ca in known_a for cb in known_b)


def _dedupe_tips_with_sources(day_tips: list) -> list[dict]:
    ranked_tips = sorted(
        day_tips,
        key=lambda t: (
            _CONFIDENCE_ORDER.get(str(t.confidence), 99),
            -float(t.corroboration_score),
            t.player_name.lower(),
        ),
    )
    grouped: list[dict] = []
    for tip in ranked_tips:
        tip_signature = _tip_story_signature(tip)
        group = next(
            (g for g in grouped if _is_same_tip_story(g["lead_signature"], tip_signature)),
            None,
        )
        if group is None:
            grouped.append(
                {
                    "lead": tip,
                    "lead_signature": tip_signature,
                    "tips": [tip],
                    "channel_ids": {tip.channel_id},
                }
            )
            continue
        group["tips"].append(tip)
        group["channel_ids"].add(tip.channel_id)
        lead_rank = _CONFIDENCE_ORDER.get(str(group["lead"].confidence), 99)
        tip_rank = _CONFIDENCE_ORDER.get(str(tip.confidence), 99)
        if tip_rank < lead_rank or (
            tip_rank == lead_rank
            and float(tip.corroboration_score) > float(group["lead"].corroboration_score)
        ):
            group["lead"] = tip
            group["lead_signature"] = tip_signature
    return grouped


def _parse_digest_sections(
    digest_text: str,
) -> tuple[dict[str, list[dict[str, str]]], list[str]]:
    section_items: dict[str, list[dict[str, str]]] = {header: [] for header in _DIGEST_REQUIRED_HEADERS}
    fallback_lines: list[str] = []
    current_header: str | None = None

    for raw_line in digest_text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        canonical_header = _canonical_digest_header(line)
        if canonical_header is not None:
            current_header = canonical_header
            continue

        match = _DIGEST_ITEM_RE.match(line)
        if not match or current_header is None:
            fallback_lines.append(line)
            continue

        section_items[current_header].append(
            {
                "player": match.group("player").strip(),
                "club": match.group("club").strip(),
                "movimento": match.group("movimento").strip(),
                "stato": match.group("stato").strip(),
                "motivo": match.group("motivo").strip(),
                "fonte": match.group("fonte").strip(),
            }
        )

    return section_items, fallback_lines


def _digest_item_counts(section_items: dict[str, list[dict[str, str]]]) -> tuple[int, int, int, int]:
    hot = len(section_items["✅ Situazioni calde / scenari aperti"])
    monitor = len(section_items["🕐 Situazioni da monitorare"])
    denied = len(section_items["🚫 Voci ridimensionate / smentite"])
    return hot + monitor + denied, hot, monitor, denied


def _format_digest_for_report(digest_text: str) -> str:
    section_items, fallback_lines = _parse_digest_sections(digest_text)

    total_items = sum(len(items) for items in section_items.values())
    summary_line = (
        f"📌 **Quadro rapido**: {total_items} notizie consolidate "
        f"({len(section_items['✅ Situazioni calde / scenari aperti'])} calde, "
        f"{len(section_items['🕐 Situazioni da monitorare'])} da monitorare, "
        f"{len(section_items['🚫 Voci ridimensionate / smentite'])} ridimensionate/smentite)."
    )

    section_intro = {
        "✅ Situazioni calde / scenari aperti": "Le situazioni piu concrete e con maggior trazione.",
        "🕐 Situazioni da monitorare": "Piste aperte ma ancora senza conferme forti.",
        "🚫 Voci ridimensionate / smentite": "Voci depotenziate o non supportate dai riscontri.",
    }
    state_icon = {"caldo": "🔥", "monitorare": "👀", "smentita": "🧊"}
    formatted_lines: list[str] = [summary_line, ""]
    for header in _DIGEST_REQUIRED_HEADERS:
        items = section_items[header]
        formatted_lines.append(f"## {header} ({len(items)})")
        formatted_lines.append(section_intro[header])
        formatted_lines.append("")

        if not items:
            formatted_lines.append("- Nessuna notizia rilevante in questa sezione.")
            formatted_lines.append("")
            continue

        for item in items:
            icon = state_icon.get(item["stato"], "•")
            formatted_lines.append(
                f"- {icon} **{item['player']}** ({item['club']}): aggiornamento su **{item['movimento']}**."
            )
            formatted_lines.append(
                f"  _Contesto:_ {item['motivo']}.  \n  _Fonti:_ {item['fonte']}."
            )
        formatted_lines.append("")

    if fallback_lines:
        formatted_lines.append("## Note tecniche")
        for line in fallback_lines:
            formatted_lines.append(f"- {line}")

    return "\n".join(formatted_lines).strip()


def format_mercato_report_telegram(
    target_date: date,
    digest_text: str,
    generated_at: datetime | None = None,
) -> str:
    """Formatta il digest per Telegram con HTML parse mode."""
    def _h(t: str) -> str:
        return _html_lib.escape(str(t)) if t else ""

    generated = generated_at or datetime.now()
    date_it = _format_date_it(target_date)
    now_str = generated.strftime("%H:%M")
    section_items, fallback_lines = _parse_digest_sections(digest_text)
    total_items, hot_count, monitor_count, denied_count = _digest_item_counts(section_items)

    div = "─" * 18

    lines: list[str] = [
        f"📣 <b>CALCIOMERCATO</b>  |  <i>{_h(date_it)}</i>",
        "<i>Rassegna consolidata · Media Advisor</i>",
        "",
        f"📊 <b>{total_items}</b> notizie  ·  🔥 {hot_count} calde  ·  👀 {monitor_count} monitorate  ·  🧊 {denied_count} smentite",
    ]

    for header in _DIGEST_REQUIRED_HEADERS:
        label = _DIGEST_SECTION_LABELS_TELEGRAM[header]
        icon = _DIGEST_SECTION_ICONS[header]
        items = section_items[header]
        lines.extend(["", div, "", f"{label}  ({len(items)})"])

        if not items:
            lines.append("• Nessuna notizia rilevante.")
            continue

        for item in items:
            lines.append("")
            lines.append(f"{icon} <b>{_h(item['player'])}</b>")
            lines.append(f"<i>{_h(item['club'])} → {_h(item['movimento'])}</i>")
            lines.append(_h(item["motivo"]))
            lines.append(f"<i>Fonte:</i> {_h(item['fonte'])}")

    if fallback_lines:
        lines.extend(["", div, "", "ℹ️ <b>Note</b>"])
        for line in fallback_lines:
            lines.append(f"• {_h(line)}")

    lines.extend(["", div, f"⏱ <i>Aggiornato alle {now_str}</i>"])
    return "\n".join(lines).strip()


def format_mercato_report_twitter(
    target_date: date,
    digest_text: str,
    generated_at: datetime | None = None,
) -> str:
    """Formatta il digest per Twitter/X in testo plain."""
    generated = generated_at or datetime.now()
    date_it = _format_date_it(target_date)
    now_str = generated.strftime("%H:%M")
    section_items, _ = _parse_digest_sections(digest_text)
    total_items, hot_count, monitor_count, denied_count = _digest_item_counts(section_items)

    lines: list[str] = [
        f"CALCIOMERCATO | {date_it}",
        f"{total_items} notizie: {hot_count} calde, {monitor_count} monitorare, {denied_count} ridimensionate",
        "",
    ]

    for header in _DIGEST_REQUIRED_HEADERS:
        label = _DIGEST_SECTION_LABELS_TWITTER[header]
        icon = _DIGEST_SECTION_ICONS[header]
        items = section_items[header]
        lines.append(label)
        if not items:
            lines.append("- Nessun aggiornamento rilevante.")
            lines.append("")
            continue
        for item in items:
            lines.append(
                f"- {icon} {item['player']} ({item['club']}): {item['movimento']}. "
                f"{item['motivo']}. Fonte: {item['fonte']}."
            )
        lines.append("")

    lines.extend(
        [
            f"Aggiornato alle {now_str}",
            "#Calciomercato #SerieA",
        ]
    )
    return "\n".join(lines).strip()


def _story_key_for_match(match: re.Match[str]) -> tuple[str, str, str] | None:
    player = _normalize_token(match.group("player"))
    club = _normalize_token(match.group("club"))
    movimento = _normalize_token(match.group("movimento"))
    if not player:
        return None
    return (player, club, movimento)


def _story_key_for_line(line: str) -> tuple[str, str, str] | None:
    match = _DIGEST_ITEM_RE.match(line)
    if not match:
        return None
    return _story_key_for_match(match)


def _preferred_state(states: set[str]) -> str:
    # Regola deterministica:
    # se esiste una smentita prevale sulla stessa voce in monitorare/caldo;
    # altrimenti prevale caldo su monitorare.
    if "smentita" in states:
        return "smentita"
    if "caldo" in states:
        return "caldo"
    return "monitorare"


def _normalize_digest_output(text: str) -> str:
    lines = [line.strip() for line in text.strip().splitlines() if line.strip()]
    if not lines:
        return text

    items_by_story: dict[tuple[str, str, str], list[dict[str, str]]] = {}
    passthrough: list[str] = []

    for line in lines:
        if _canonical_digest_header(line) is not None:
            continue
        match = _DIGEST_ITEM_RE.match(line)
        key = _story_key_for_match(match) if match else None
        if not match or not key:
            passthrough.append(line)
            continue
        items_by_story.setdefault(key, []).append(
            {
                "line": line,
                "player": match.group("player").strip(),
                "club": match.group("club").strip(),
                "movimento": match.group("movimento").strip(),
                "stato": match.group("stato").strip(),
                "motivo": match.group("motivo").strip(),
                "fonte": match.group("fonte").strip(),
            }
        )

    section_items: dict[str, list[str]] = {header: [] for header in _DIGEST_REQUIRED_HEADERS}
    header_for_state = {
        "caldo": "✅ Situazioni calde / scenari aperti",
        "monitorare": "🕐 Situazioni da monitorare",
        "smentita": "🚫 Voci ridimensionate / smentite",
    }

    for story_items in items_by_story.values():
        states = {item["stato"] for item in story_items}
        chosen_state = _preferred_state(states)
        chosen = next((item for item in story_items if item["stato"] == chosen_state), story_items[0])

        all_sources: list[str] = []
        seen_sources: set[str] = set()
        for item in story_items:
            for source in [s.strip() for s in item["fonte"].split(",") if s.strip()]:
                source_key = source.lower()
                if source_key in seen_sources:
                    continue
                seen_sources.add(source_key)
                all_sources.append(source)

        merged_source = ", ".join(all_sources) if all_sources else chosen["fonte"]
        merged_line = (
            f"{chosen['player']} ({chosen['club']}) - Movimento: {chosen['movimento']}; "
            f"Stato: {chosen_state}; Motivo: {chosen['motivo']}; Fonte: {merged_source}"
        )
        section_items[header_for_state[chosen_state]].append(merged_line)

    out_lines: list[str] = []
    for header in _DIGEST_REQUIRED_HEADERS:
        out_lines.append(header)
        out_lines.extend(section_items[header])
        out_lines.append("")

    out_lines.extend(passthrough)
    return "\n".join(out_lines).strip()


def format_mercato_report_markdown(
    target_date: date,
    digest_text: str,
    generated_at: datetime | None = None,
) -> str:
    generated = generated_at or datetime.now()
    date_it = _format_date_it(target_date)
    now_str = generated.strftime("%H:%M del %d/%m/%Y")
    rendered_digest = _format_digest_for_report(digest_text)
    return (
        f"# Calciomercato — {date_it}\n\n"
        "> Rassegna giornaliera consolidata (notizie simili accorpate, fonti aggregate).\n\n"
        "## Legenda\n"
        "- ✅ `caldo`: scenario forte o avanzato\n"
        "- 🕐 `monitorare`: rumor in evoluzione\n"
        "- 🚫 `smentita`: voce ridimensionata o negata\n\n"
        f"{rendered_digest}\n\n"
        f"---\n_Generato da Media Advisor alle {now_str}_\n"
    )


def write_mercato_report(
    root: Path,
    target_date: date,
    digest_text: str,
    generated_at: datetime | None = None,
) -> tuple[Path, str]:
    generated_at = generated_at or datetime.now()
    day = target_date.isoformat()
    reports_dir = root / "reports"
    report_path = reports_dir / f"{day}.md"
    reports_dir.mkdir(parents=True, exist_ok=True)
    content = format_mercato_report_markdown(target_date, digest_text, generated_at=generated_at)
    report_path.write_text(content, encoding="utf-8")
    telegram_content = format_mercato_report_telegram(target_date, digest_text, generated_at=generated_at)
    twitter_content = format_mercato_report_twitter(target_date, digest_text, generated_at=generated_at)
    (reports_dir / f"{day}.telegram.html").write_text(telegram_content, encoding="utf-8")
    (reports_dir / f"{day}.twitter.txt").write_text(twitter_content, encoding="utf-8")

    cache_path = reports_dir / f"{day}.json"
    cache_path.write_text(
        _json.dumps(
            {
                "digest_raw": digest_text,
                "generated_at": generated_at.isoformat(),
                "telegram_path": f"reports/{day}.telegram.html",
                "twitter_path": f"reports/{day}.twitter.txt",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return report_path, content


def load_report_cache(root: Path, target_date: date) -> dict | None:
    """Legge il report salvato per una data. Ritorna {digest_raw, generated_at} o None."""
    cache_path = root / "reports" / f"{target_date.isoformat()}.json"
    if not cache_path.exists():
        return None
    try:
        return _json.loads(cache_path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _load_channel_name_map(root: Path) -> dict[str, str]:
    try:
        raw = read_json(channels_config_path(root))
        cfg = ChannelsConfig.model_validate(raw)
        return {channel.id: channel.name for channel in cfg.channels}
    except (FileNotFoundError, JSONDecodeError, OSError, ValidationError):
        return {}


def _validate_digest_output(
    text: str,
    *,
    allow_empty_smentita_section: bool = False,
) -> list[str]:
    """Se allow_empty_smentita_section è True, la terza sezione può essere vuota (nessun tip denied in input)."""
    errors: list[str] = []
    stripped = text.strip()
    if not stripped:
        return ["Digest vuoto."]

    lines = [line.strip() for line in stripped.splitlines() if line.strip()]
    header_positions = {header: [] for header in _DIGEST_REQUIRED_HEADERS}
    for idx, line in enumerate(lines):
        canonical_header = _canonical_digest_header(line)
        if canonical_header in header_positions:
            header_positions[canonical_header].append(idx)

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
    story_states: dict[tuple[str, str, str], set[str]] = {}
    story_lines: dict[tuple[str, str, str], list[str]] = {}
    for line in lines:
        canonical_header = _canonical_digest_header(line)
        if canonical_header is not None:
            current_header = canonical_header
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

        key = _story_key_for_match(match)
        if key:
            states = story_states.setdefault(key, set())
            states.add(match.group("stato"))
            story_lines.setdefault(key, []).append(line)

    for key, states in story_states.items():
        if len(states) <= 1:
            continue
        # Duplicate story across sections with different states is invalid:
        # the digest must contain one consolidated line per story.
        lines_for_story = story_lines.get(key, [])
        errors.append(
            "Notizia duplicata in stati diversi: "
            + " | ".join(lines_for_story[:3])
        )

    for header, count in section_item_count.items():
        if count == 0:
            if allow_empty_smentita_section and header == _DIGEST_SMENTITA_HEADER:
                continue
            errors.append(f"Sezione vuota: '{header}'.")

    return errors


def _is_valid_digest_output(
    text: str,
    *,
    allow_empty_smentita_section: bool = False,
) -> bool:
    return not _validate_digest_output(
        text, allow_empty_smentita_section=allow_empty_smentita_section
    )


def _sanitize_digest_field(value: str | None, fallback: str) -> str:
    raw = (value or "").replace("\n", " ").replace(";", ",").strip()
    return raw or fallback


def _build_denied_fallback_lines(
    day_tips: list,
    channel_names: dict[str, str],
    *,
    max_items: int = 3,
) -> list[str]:
    denied_tips = [t for t in day_tips if t.confidence == "denied"]
    if not denied_tips:
        return []
    denied_tips.sort(key=lambda t: float(t.corroboration_score), reverse=True)

    fallback_lines: list[str] = []
    for tip in denied_tips[:max_items]:
        player = (tip.player_name or "").strip()
        if not player:
            continue
        club = _sanitize_digest_field(tip.from_club or tip.to_club, "N/D")
        movement = _sanitize_digest_field(_truncate_tip_text(tip.tip_text, 120), "voce ridimensionata")
        source = _sanitize_digest_field(channel_names.get(tip.channel_id, tip.channel_id), tip.channel_id)
        fallback_lines.append(
            f"{player} ({club}) - Movimento: {movement}; "
            f"Stato: smentita; Motivo: voce ridimensionata dalla fonte; Fonte: {source}"
        )
    return fallback_lines


def _repair_smentita_section(text: str, fallback_lines: list[str]) -> str:
    """Keep only valid rows in smentita section; inject fallback lines if section is empty."""
    if not text.strip():
        return text

    lines = text.splitlines()
    out: list[str] = []
    in_smentita = False
    smentita_kept = 0

    for line in lines:
        stripped = line.strip()
        canonical_header = _canonical_digest_header(stripped) if stripped else None
        if canonical_header is not None:
            if in_smentita and smentita_kept == 0 and fallback_lines:
                out.extend(fallback_lines)
            in_smentita = canonical_header == _DIGEST_SMENTITA_HEADER
            out.append(line)
            continue

        if not in_smentita:
            out.append(line)
            continue

        if not stripped:
            out.append(line)
            continue

        match = _DIGEST_ITEM_RE.match(stripped)
        if match and match.group("stato") == "smentita":
            out.append(line)
            smentita_kept += 1
            continue
        # Drop invalid placeholder/noise rows inside smentita section.

    if in_smentita and smentita_kept == 0 and fallback_lines:
        out.extend(fallback_lines)

    return "\n".join(out).strip()


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
        if not completion.choices:
            continue
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
    grouped_tips = _dedupe_tips_with_sources(day_tips)
    grouped_tips = heapq.nsmallest(
        DIGEST_MAX_INPUT_TIPS,
        grouped_tips,
        key=lambda g: _CONFIDENCE_ORDER.get(str(g["lead"].confidence), 99),
    )

    lines: list[str] = []
    for group in grouped_tips:
        tip = group["lead"]
        emoji = _CONFIDENCE_EMOJI.get(str(tip.confidence), "🔴")
        sources = sorted(
            {channel_names.get(channel_id, channel_id) for channel_id in group["channel_ids"]}
        )
        source = ", ".join(sources)
        route = f" ({tip.from_club or '?'} → {tip.to_club or '?'})" if (tip.from_club or tip.to_club) else ""
        tip_text = _truncate_tip_text(tip.tip_text)
        lines.append(f"{emoji} FONTE: {source} | {tip.player_name}{route}: {tip_text}")

    has_denied_tip = any(t.confidence == "denied" for t in day_tips)
    allow_empty_smentita = not has_denied_tip

    client = openai.AsyncOpenAI(api_key=openai_api_key)
    denied_section_constraint = (
        "\n\nVINCOLO DATI: nell'input sono presenti una o piu voci con livello denied/smentita. "
        "La sezione '🚫 Voci ridimensionate / smentite' deve contenere almeno 1 riga "
        "reale e valida nel formato richiesto. Non usare righe placeholder/generiche "
        "(es. 'Nessuna voce...')."
        if has_denied_tip
        else ""
    )
    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"Indiscrezioni del {_format_date_it(target_date)}:\n\n"
                + "\n".join(lines)
                + denied_section_constraint
            ),
        },
    ]
    denied_fallback_lines = _build_denied_fallback_lines(day_tips, channel_names)

    digest_text = await _complete_digest_with_token_retry(client, messages)
    if not digest_text:
        raise DigestGenerationError("Output digest vuoto ricevuto dal modello.")
    digest_text = _normalize_digest_output(digest_text)
    if has_denied_tip:
        digest_text = _repair_smentita_section(digest_text, denied_fallback_lines)
        digest_text = _normalize_digest_output(digest_text)

    first_errors = _validate_digest_output(
        digest_text, allow_empty_smentita_section=allow_empty_smentita
    )
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
                + denied_section_constraint
            ),
        },
    ]
    retry_text = await _complete_digest_with_token_retry(client, retry_messages)
    retry_text = _normalize_digest_output(retry_text or "")
    if has_denied_tip:
        retry_text = _repair_smentita_section(retry_text, denied_fallback_lines)
        retry_text = _normalize_digest_output(retry_text)
    retry_errors = _validate_digest_output(
        retry_text or "",
        allow_empty_smentita_section=allow_empty_smentita,
    )
    if retry_text and not retry_errors:
        return retry_text

    raise DigestGenerationError(
        "Digest non pubblicabile dopo retry. Errori residui: "
        + "; ".join(retry_errors[:6])
    )
