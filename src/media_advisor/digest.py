from __future__ import annotations

import heapq
import html as _html_lib
import json as _json
import math
import os
import re
import tempfile
import unicodedata
from datetime import date, datetime
from json import JSONDecodeError
from pathlib import Path
from typing import Any

import openai
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from media_advisor.costs import record_openai_chat_completion
from media_advisor.io.channel_store import load_channels_config_dict
from media_advisor.mercato.models import MercatoTip
from media_advisor.mercato.quote_timing import refined_start_sec_for_digest
from media_advisor.models.channels import ChannelConfig, ChannelsConfig

DIGEST_MODEL = "gpt-4.1-mini"
DIGEST_TOKEN_STEPS = (900, 1500)
DIGEST_MAX_INPUT_TIPS = 20
DIGEST_MAX_TIP_TEXT_CHARS = 220


def _atomic_write_text(path: Path, text: str, *, encoding: str = "utf-8") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f"{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding=encoding) as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


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

TWITTER_VERIFICA_MAX_SOURCES = 3


class DigestItemSource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    channel_id: str
    channel_label: str
    video_id: str
    video_title: str | None = None
    start_sec: float | None = None
    watch_url: str


class DigestItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    player: str
    club: str
    movimento: str
    stato: str
    motivo: str
    fonte: str
    sources: list[DigestItemSource] = Field(default_factory=list)


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
    "12. Mantieni tutte e tre le intestazioni di sezione nell'ordine indicato; nessuna riga voce tronca.\n"
    "13. Ogni sezione puo avere zero righe voce (solo intestazione) se non ci sono indiscrezioni "
    "da classificare in quel bucket; non riempire con placeholder."
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


def _split_fonte_tokens(fonte: str) -> list[str]:
    out: list[str] = []
    for chunk in re.split(r"[,;]", fonte):
        c = chunk.strip()
        if not c:
            continue
        low = c.lower()
        if " e " in low and len(c) < 80:
            idx = low.find(" e ")
            left, right = c[:idx].strip(), c[idx + 3 :].strip()
            if left:
                out.append(left)
            if right:
                out.append(right)
        else:
            out.append(c)
    return out


def _channel_fonte_match_score(t_norm: str, ch: ChannelConfig) -> int:
    """Score token normalizzato vs canale (id + name)."""
    nid = _normalize_token(ch.id)
    nn = _normalize_token(ch.name)
    if not t_norm:
        return 0
    if t_norm == nid:
        return 95
    if t_norm == nn:
        return 100
    if len(t_norm) >= 4 and t_norm in nn:
        return 72
    if len(nn) >= 4 and nn in t_norm:
        return 68
    return 0


def _best_channel_id_for_fonte_token(token: str, cfg: ChannelsConfig) -> str | None:
    t_norm = _normalize_token(token)
    if not t_norm:
        return None
    best_id: str | None = None
    best_score = 0
    for ch in cfg.channels:
        score = _channel_fonte_match_score(t_norm, ch)
        if score > best_score:
            best_score = score
            best_id = ch.id
    return best_id if best_score >= 60 else None


def _ordered_channel_ids_from_fonte(fonte: str, cfg: ChannelsConfig) -> list[str]:
    ordered: list[str] = []
    seen: set[str] = set()
    for token in _split_fonte_tokens(fonte):
        cid = _best_channel_id_for_fonte_token(token, cfg)
        if cid and cid not in seen:
            seen.add(cid)
            ordered.append(cid)
    return ordered


def _club_match_score_digest(digest_club: str, tip: MercatoTip) -> int:
    s = 0
    for c in (tip.from_club, tip.to_club):
        if c and _names_are_similar(digest_club, c):
            s += 10
    return s


def _movimento_overlap_score(movimento: str, tip: MercatoTip) -> int:
    """Quante parole significative del movimento compaiono in tip/quote (normalizzate)."""
    if not movimento or not movimento.strip():
        return 0
    tokens = [w for w in re.findall(r"[\wàèéìòùÀÈÉÌÒÙ]+", movimento) if len(w) > 2]
    blob = _normalize_token((tip.tip_text or "") + " " + (tip.quote_text or ""))
    return sum(1 for w in tokens if _normalize_token(w) in blob)


def _pick_best_tip_for_channel(
    pool: list[MercatoTip],
    digest_club: str,
    row_movimento: str,
    root: Path,
) -> MercatoTip | None:
    if not pool:
        return None
    max_club = max(_club_match_score_digest(digest_club, t) for t in pool)
    narrowed = [t for t in pool if _club_match_score_digest(digest_club, t) == max_club]

    def rank(t: MercatoTip) -> tuple:
        _start, src = refined_start_sec_for_digest(root, t)
        aligned = src == "aligned"
        ov = _movimento_overlap_score(row_movimento, t)
        st = _start if _start is not None else 1e12
        return (0 if aligned else 1, -ov, st)

    return min(narrowed, key=rank)


def _watch_url_digest(video_id: str, start_sec: float | None) -> str:
    """Deep link YouTube: parametro t in secondi interi (senza suffisso 's', compat massima)."""
    base = f"https://www.youtube.com/watch?v={video_id}"
    if start_sec is None:
        return base
    try:
        t = float(start_sec)
    except (TypeError, ValueError):
        return base
    if math.isnan(t):
        return base
    ti = max(0, int(round(t)))
    return f"{base}&t={ti}"


def _format_seconds_mmss_digest(sec: float | None) -> str:
    if sec is None:
        return "??:??"
    try:
        s = float(sec)
    except (TypeError, ValueError):
        return "??:??"
    if math.isnan(s):
        return "??:??"
    s = max(0, int(s))
    h, rem = divmod(s, 3600)
    m, ss = divmod(rem, 60)
    if h:
        return f"{h}:{m:02d}:{ss:02d}"
    return f"{m}:{ss:02d}"


def _h(t: str | None) -> str:
    """HTML-escape a value for Telegram HTML parse mode, returning '' for None/empty."""
    return _html_lib.escape(str(t)) if t else ""


def _resolve_digest_sources_for_row(
    row: dict[str, str],
    tips: list[MercatoTip],
    cfg: ChannelsConfig,
    id_to_name: dict[str, str],
    root: Path,
) -> list[DigestItemSource]:
    dp = _normalize_token(row["player"])
    if not dp:
        return []
    player_tips = [
        t for t in tips if _is_normalized_name_match(dp, _normalize_token(t.player_name))
    ]
    channel_order = _ordered_channel_ids_from_fonte(row["fonte"], cfg)
    sources: list[DigestItemSource] = []
    for cid in channel_order:
        pool = [t for t in player_tips if t.channel_id == cid]
        best = _pick_best_tip_for_channel(pool, row["club"], row.get("movimento", ""), root)
        if not best:
            continue
        start_f, _src = refined_start_sec_for_digest(root, best)
        sources.append(
            DigestItemSource(
                channel_id=best.channel_id,
                channel_label=id_to_name.get(best.channel_id, best.channel_id),
                video_id=best.video_id,
                video_title=None,
                start_sec=start_f,
                watch_url=_watch_url_digest(best.video_id, start_f),
            )
        )
    return sources


def build_enriched_digest_sections(
    root: Path,
    target_date: date,
    digest_text: str,
    tips: list[MercatoTip] | None = None,
) -> tuple[dict[str, list[DigestItem]], list[str]]:
    """Parse digest + risolve link YouTube per ogni voce dai MercatoTip del giorno."""
    from media_advisor.mercato.aggregator import get_tips_for_date

    if tips is None:
        tips = get_tips_for_date(root, target_date)
    raw_sections, fallback = _parse_digest_sections(digest_text)
    try:
        raw_cfg = load_channels_config_dict(root)
        cfg = ChannelsConfig.model_validate(raw_cfg)
    except (FileNotFoundError, JSONDecodeError, OSError, ValidationError):
        cfg = ChannelsConfig(channels=[])
    id_to_name = {ch.id: ch.name for ch in cfg.channels}
    if not id_to_name:
        id_to_name = _load_channel_name_map(root)

    enriched: dict[str, list[DigestItem]] = {h: [] for h in _DIGEST_REQUIRED_HEADERS}
    for header in _DIGEST_REQUIRED_HEADERS:
        for row in raw_sections[header]:
            sources = _resolve_digest_sources_for_row(row, tips, cfg, id_to_name, root)
            enriched[header].append(
                DigestItem(
                    player=row["player"],
                    club=row["club"],
                    movimento=row["movimento"],
                    stato=row["stato"],
                    motivo=row["motivo"],
                    fonte=row["fonte"],
                    sources=sources,
                )
            )
    return enriched, fallback


def flatten_digest_items_for_api(section_items: dict[str, list[DigestItem]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for header in _DIGEST_REQUIRED_HEADERS:
        for it in section_items.get(header, []):
            d = it.model_dump(mode="json")
            d["section"] = header
            out.append(d)
    return out


def sections_from_flat_digest_items(items: list[dict[str, Any]]) -> dict[str, list[DigestItem]]:
    out: dict[str, list[DigestItem]] = {h: [] for h in _DIGEST_REQUIRED_HEADERS}
    for row in items:
        sec = row.get("section")
        if sec not in out:
            continue
        data = {k: v for k, v in row.items() if k != "section"}
        out[sec].append(DigestItem.model_validate(data))
    return out


def hydrate_digest_sections_from_cache(
    root: Path,
    target_date: date,
    digest_text: str,
    cached: dict | None,
) -> dict[str, list[DigestItem]]:
    """Usa digest_items dalla cache JSON se valido; altrimenti ricalcola senza LLM."""
    raw_items = (cached or {}).get("digest_items")
    if isinstance(raw_items, list) and raw_items:
        try:
            return sections_from_flat_digest_items(raw_items)
        except Exception:
            pass
    section, _ = build_enriched_digest_sections(root, target_date, digest_text)
    return section


def _digest_item_counts(section_items: dict[str, list[dict[str, str]]]) -> tuple[int, int, int, int]:
    hot = len(section_items["✅ Situazioni calde / scenari aperti"])
    monitor = len(section_items["🕐 Situazioni da monitorare"])
    denied = len(section_items["🚫 Voci ridimensionate / smentite"])
    return hot + monitor + denied, hot, monitor, denied


def _format_fonte_markdown(item: DigestItem) -> str:
    """Una sola riga Fonte: testo o link cliccabili per canale."""
    if item.sources:
        parts = [
            f"[{s.channel_label} ({_format_seconds_mmss_digest(s.start_sec)})]({s.watch_url})"
            for s in item.sources
        ]
        return "  _Fonte:_ " + " · ".join(parts)
    return f"  _Fonte:_ {item.fonte}"


def _format_digest_for_report(
    digest_text: str,
    *,
    section_items_enriched: dict[str, list[DigestItem]] | None = None,
) -> str:
    if section_items_enriched is None:
        section_items, fallback_lines = _parse_digest_sections(digest_text)
        counts = section_items
    else:
        section_items = None
        _, fallback_lines = _parse_digest_sections(digest_text)
        counts = section_items_enriched

    total_items = sum(len(items) for items in counts.values())
    summary_line = (
        f"📌 **Quadro rapido**: {total_items} notizie consolidate "
        f"({len(counts['✅ Situazioni calde / scenari aperti'])} calde, "
        f"{len(counts['🕐 Situazioni da monitorare'])} da monitorare, "
        f"{len(counts['🚫 Voci ridimensionate / smentite'])} ridimensionate/smentite)."
    )

    section_intro = {
        "✅ Situazioni calde / scenari aperti": "Le situazioni piu concrete e con maggior trazione.",
        "🕐 Situazioni da monitorare": "Piste aperte ma ancora senza conferme forti.",
        "🚫 Voci ridimensionate / smentite": "Voci depotenziate o non supportate dai riscontri.",
    }
    state_icon = {"caldo": "🔥", "monitorare": "👀", "smentita": "🧊"}
    formatted_lines: list[str] = [summary_line, ""]
    for header in _DIGEST_REQUIRED_HEADERS:
        items_raw = counts[header] if section_items is None else None
        items_en = section_items_enriched[header] if section_items_enriched is not None else None
        n = len(items_raw or items_en or [])
        formatted_lines.append(f"## {header} ({n})")
        formatted_lines.append(section_intro[header])
        formatted_lines.append("")

        if n == 0:
            formatted_lines.append("- Nessuna notizia rilevante in questa sezione.")
            formatted_lines.append("")
            continue

        if section_items_enriched is not None and items_en is not None:
            for item in items_en:
                icon = state_icon.get(item.stato, "•")
                formatted_lines.append(
                    f"- {icon} **{item.player}** ({item.club}): aggiornamento su **{item.movimento}**."
                )
                formatted_lines.append(
                    f"  _Contesto:_ {item.motivo}."
                )
                formatted_lines.append(_format_fonte_markdown(item))
        elif items_raw is not None:
            for item in items_raw:
                icon = state_icon.get(item["stato"], "•")
                formatted_lines.append(
                    f"- {icon} **{item['player']}** ({item['club']}): aggiornamento su **{item['movimento']}**."
                )
                formatted_lines.append(
                    f"  _Contesto:_ {item['motivo']}."
                )
                formatted_lines.append(f"  _Fonte:_ {item['fonte']}")
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
    *,
    section_items_enriched: dict[str, list[DigestItem]] | None = None,
) -> str:
    """Formatta il digest per Telegram con HTML parse mode."""
    generated = generated_at or datetime.now()
    date_it = _format_date_it(target_date)
    now_str = generated.strftime("%H:%M")
    if section_items_enriched is None:
        section_items, fallback_lines = _parse_digest_sections(digest_text)
        total_items, hot_count, monitor_count, denied_count = _digest_item_counts(section_items)
    else:
        section_items = None
        _, fallback_lines = _parse_digest_sections(digest_text)
        total_items = sum(len(section_items_enriched[h]) for h in _DIGEST_REQUIRED_HEADERS)
        hot_count = len(section_items_enriched["✅ Situazioni calde / scenari aperti"])
        monitor_count = len(section_items_enriched["🕐 Situazioni da monitorare"])
        denied_count = len(section_items_enriched["🚫 Voci ridimensionate / smentite"])

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
        if section_items_enriched is None:
            items_dict = section_items[header] if section_items is not None else []
            items_en = None
        else:
            items_dict = None
            items_en = section_items_enriched[header]
        n = len(items_dict or items_en or [])
        lines.extend(["", div, "", f"{label}  ({n})"])

        if n == 0:
            lines.append("• Nessuna notizia rilevante.")
            continue

        if section_items_enriched is not None and items_en is not None:
            for item in items_en:
                lines.append("")
                lines.append(f"{icon} <b>{_h(item.player)}</b>")
                lines.append(f"<i>{_h(item.club)} → {_h(item.movimento)}</i>")
                lines.append(_h(item.motivo))
                if item.sources:
                    v_parts: list[str] = []
                    for s in item.sources:
                        lab = f"{s.channel_label} ({_format_seconds_mmss_digest(s.start_sec)})"
                        v_parts.append(f"<a href=\"{_h(s.watch_url)}\">{_h(lab)}</a>")
                    lines.append("<i>Fonte:</i> " + " · ".join(v_parts))
                else:
                    lines.append(f"<i>Fonte:</i> {_h(item.fonte)}")
        elif items_dict is not None:
            for item in items_dict:
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


_TRANSFER_TYPE_IT: dict[str, str] = {
    "loan": "prestito",
    "permanent": "cessione",
    "free_agent": "svincolato",
    "extension": "rinnovo",
    "renewal": "rinnovo",
    "unknown": "",
}


def _build_sorted_team_groups(
    groups: list[dict],
) -> tuple[dict[str, list[dict]], list[str]]:
    """Raggruppa i gruppi di tip (già deduplicati) per squadra e li ordina per numero di gruppi (desc) poi alfabeticamente."""
    team_groups: dict[str, list[dict]] = {}
    for group in groups:
        lead = group["lead"]
        clubs: set[str] = set()
        if lead.from_club:
            clubs.add(lead.from_club)
        if lead.to_club:
            clubs.add(lead.to_club)
        for club in clubs:
            team_groups.setdefault(club, []).append(group)
    sorted_teams = sorted(
        team_groups.keys(),
        key=lambda t: (-len(team_groups[t]), t.lower()),
    )
    return team_groups, sorted_teams


def build_team_groups_for_api(
    tips: list[MercatoTip],
    root: Path,
) -> list[dict]:
    """Raggruppa i tip per squadra e restituisce dati strutturati per l'API/dashboard.

    Condivide la stessa logica di raggruppamento di format_tips_by_team_telegram()
    così qualsiasi modifica futura si riflette automaticamente su entrambi i flussi.
    """
    if not tips:
        return []

    channel_names = _load_channel_name_map(root)
    groups = _dedupe_tips_with_sources(tips)
    team_groups, sorted_teams = _build_sorted_team_groups(groups)

    result: list[dict] = []
    for team in sorted_teams:
        team_tip_groups = team_groups[team]
        tips_out: list[dict] = []
        for group in team_tip_groups:
            lead = group["lead"]
            sources: list[dict] = []
            for ch_id in sorted(group["channel_ids"]):
                ch_name = channel_names.get(ch_id, ch_id)
                tip_with_ts = next(
                    (
                        t for t in group["tips"]
                        if t.channel_id == ch_id and t.video_id and t.quote_start_sec is not None
                    ),
                    None,
                )
                sources.append({
                    "channel_id": ch_id,
                    "channel_label": ch_name,
                    "video_id": tip_with_ts.video_id if tip_with_ts else None,
                    "start_sec": tip_with_ts.quote_start_sec if tip_with_ts else None,
                    "watch_url": _watch_url_digest(tip_with_ts.video_id, tip_with_ts.quote_start_sec) if tip_with_ts else None,
                })
            tt = _TRANSFER_TYPE_IT.get(str(lead.transfer_type), "") if lead.transfer_type else ""
            is_renewal = lead.from_club and lead.to_club and lead.from_club == lead.to_club
            move_parts: list[str] = []
            if is_renewal:
                move_parts.append("rinnovo")
            elif lead.from_club and lead.to_club:
                move_parts.append(f"{lead.from_club} → {lead.to_club}")
            elif lead.from_club:
                move_parts.append(f"cedente: {lead.from_club}")
            elif lead.to_club:
                move_parts.append("possibile acquisto")
            if tt and not is_renewal:
                move_parts.append(tt)

            tips_out.append({
                "player_name": lead.player_name,
                "from_club": lead.from_club,
                "to_club": lead.to_club,
                "transfer_type": str(lead.transfer_type) if lead.transfer_type else None,
                "move_label": " · ".join(move_parts),
                "tip_text": lead.tip_text,
                "confidence": str(lead.confidence) if lead.confidence else None,
                "sources": sources,
            })
        result.append({
            "team": team,
            "tip_count": len(team_tip_groups),
            "tips": tips_out,
        })
    return result


def format_tips_by_team_telegram(
    tips: list[MercatoTip],
    target_date: date,
    root: Path,
    generated_at: datetime | None = None,
) -> str | None:
    """Organizza i tip per squadra coinvolta (from_club / to_club).
    Se un tip tocca due squadre appare in entrambe le sezioni.
    Ritorna None se non ci sono tip.
    """
    if not tips:
        return None

    generated = generated_at or datetime.now()
    date_it = _format_date_it(target_date)
    now_str = generated.strftime("%H:%M")
    channel_names = _load_channel_name_map(root)

    groups = _dedupe_tips_with_sources(tips)
    team_groups, sorted_teams = _build_sorted_team_groups(groups)

    if not team_groups:
        return None

    div = "─" * 18
    lines: list[str] = [
        f"📡 <b>CALCIOMERCATO</b> — <i>{_h(date_it)}</i>",
        f"<i>{len(groups)} notizie · {len(sorted_teams)} squadre coinvolte · Media Advisor</i>",
    ]

    for team in sorted_teams:
        team_gs = team_groups[team]
        n = len(team_gs)
        label = "notizia" if n == 1 else "notizie"
        lines.extend(["", div, f"<b>{_h(team.upper())}</b>  ·  {n} {label}", div])

        for group in team_gs:
            lead = group["lead"]
            tt = _TRANSFER_TYPE_IT.get(str(lead.transfer_type), str(lead.transfer_type))

            is_renewal = lead.from_club and lead.to_club and lead.from_club == lead.to_club
            if is_renewal:
                move_parts = ["rinnovo"]
            elif lead.from_club and lead.to_club:
                move_parts = [f"{_h(lead.from_club)} → {_h(lead.to_club)}"]
            elif lead.from_club:
                move_parts = [f"cedente: {_h(lead.from_club)}"]
            elif lead.to_club:
                move_parts = ["possibile acquisto"]
            else:
                move_parts = []
            if tt and not is_renewal:
                move_parts.append(_h(tt))
            move_label = f"  <i>{' · '.join(move_parts)}</i>" if move_parts else ""

            lines.append("")
            lines.append(f"<b>{_h(lead.player_name)}</b>{move_label}")
            if lead.tip_text:
                lines.append(_h(lead.tip_text))

            source_parts: list[str] = []
            for ch_id in sorted(group["channel_ids"]):
                ch_name = _h(channel_names.get(ch_id, ch_id))
                tip_with_ts = next(
                    (
                        t for t in group["tips"]
                        if t.channel_id == ch_id and t.video_id and t.quote_start_sec is not None
                    ),
                    None,
                )
                if tip_with_ts:
                    start = _format_seconds_mmss_digest(tip_with_ts.quote_start_sec)
                    url = _watch_url_digest(tip_with_ts.video_id, tip_with_ts.quote_start_sec)
                    source_parts.append(f'<a href="{_h(url)}">{ch_name} ({start})</a>')
                else:
                    source_parts.append(ch_name)
            lines.append("<i>Fonte:</i> " + " · ".join(source_parts))

    lines.extend(["", div, f"<i>Aggiornato alle {now_str}</i>"])
    return "\n".join(lines).strip()


def format_mercato_report_twitter(
    target_date: date,
    digest_text: str,
    generated_at: datetime | None = None,
    *,
    section_items_enriched: dict[str, list[DigestItem]] | None = None,
) -> str:
    """Formatta il digest per Twitter/X in testo plain."""
    generated = generated_at or datetime.now()
    date_it = _format_date_it(target_date)
    now_str = generated.strftime("%H:%M")
    if section_items_enriched is None:
        section_items, _ = _parse_digest_sections(digest_text)
        total_items, hot_count, monitor_count, denied_count = _digest_item_counts(section_items)
    else:
        section_items = None
        total_items = sum(len(section_items_enriched[h]) for h in _DIGEST_REQUIRED_HEADERS)
        hot_count = len(section_items_enriched["✅ Situazioni calde / scenari aperti"])
        monitor_count = len(section_items_enriched["🕐 Situazioni da monitorare"])
        denied_count = len(section_items_enriched["🚫 Voci ridimensionate / smentite"])

    lines: list[str] = [
        f"CALCIOMERCATO | {date_it}",
        f"{total_items} notizie: {hot_count} calde, {monitor_count} monitorare, {denied_count} ridimensionate",
        "",
    ]

    for header in _DIGEST_REQUIRED_HEADERS:
        label = _DIGEST_SECTION_LABELS_TWITTER[header]
        icon = _DIGEST_SECTION_ICONS[header]
        if section_items_enriched is None:
            items = section_items[header] if section_items is not None else []
            items_en_tw: list[DigestItem] | None = None
        else:
            items = None
            items_en_tw = section_items_enriched[header]
        n = len(items or items_en_tw or [])
        lines.append(label)
        if not n:
            lines.append("- Nessun aggiornamento rilevante.")
            lines.append("")
            continue
        if section_items_enriched is not None and items_en_tw is not None:
            for item in items_en_tw:
                lines.append(
                    f"- {icon} {item.player} ({item.club}): {item.movimento}. {item.motivo}."
                )
                if item.sources:
                    parts_tw: list[str] = []
                    for s in item.sources[:TWITTER_VERIFICA_MAX_SOURCES]:
                        parts_tw.append(f"{s.channel_label} {_watch_url_digest(s.video_id, s.start_sec)}")
                    suffix = " …" if len(item.sources) > TWITTER_VERIFICA_MAX_SOURCES else ""
                    lines.append(f"  Fonte: {' | '.join(parts_tw)}{suffix}")
                else:
                    lines.append(f"  Fonte: {item.fonte}")
        elif items is not None:
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


def _strip_model_preamble(text: str) -> str:
    cleaned = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL | re.IGNORECASE)
    lines = cleaned.splitlines()
    first_header_idx = next(
        (i for i, line in enumerate(lines) if _canonical_digest_header(line.strip()) is not None),
        None,
    )
    if first_header_idx is not None and first_header_idx > 0:
        lines = lines[first_header_idx:]
    return "\n".join(lines).strip()


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
    *,
    section_items_enriched: dict[str, list[DigestItem]] | None = None,
) -> str:
    generated = generated_at or datetime.now()
    date_it = _format_date_it(target_date)
    now_str = generated.strftime("%H:%M del %d/%m/%Y")
    rendered_digest = _format_digest_for_report(
        digest_text,
        section_items_enriched=section_items_enriched,
    )
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
) -> tuple[Path, str, dict[str, list[DigestItem]]]:
    from media_advisor.mercato.aggregator import get_tips_for_date

    generated_at = generated_at or datetime.now()
    tips = get_tips_for_date(root, target_date)
    section_enriched, _ = build_enriched_digest_sections(
        root, target_date, digest_text, tips=tips
    )
    day = target_date.isoformat()
    reports_dir = root / "reports"
    report_path = reports_dir / f"{day}.md"
    content = format_mercato_report_markdown(
        target_date,
        digest_text,
        generated_at=generated_at,
        section_items_enriched=section_enriched,
    )
    telegram_content = format_mercato_report_telegram(
        target_date,
        digest_text,
        generated_at=generated_at,
        section_items_enriched=section_enriched,
    )
    twitter_content = format_mercato_report_twitter(
        target_date,
        digest_text,
        generated_at=generated_at,
        section_items_enriched=section_enriched,
    )

    digest_items_flat = flatten_digest_items_for_api(section_enriched)
    from media_advisor.config import Settings
    from media_advisor.db.repository import upsert_daily_report
    from media_advisor.db.session import session_scope

    with session_scope(root) as session:
        upsert_daily_report(
            session,
            report_date=target_date,
            digest_raw=digest_text,
            digest_items=digest_items_flat,
            markdown_body=content,
            telegram_html=telegram_content,
            twitter_txt=twitter_content,
            generated_at=generated_at,
        )

    if Settings().export_report_files:
        _atomic_write_text(report_path, content)
        _atomic_write_text(reports_dir / f"{day}.telegram.html", telegram_content)
        _atomic_write_text(reports_dir / f"{day}.twitter.txt", twitter_content)
        cache_path = reports_dir / f"{day}.json"
        _atomic_write_text(
            cache_path,
            _json.dumps(
                {
                    "digest_raw": digest_text,
                    "digest_items": digest_items_flat,
                    "generated_at": generated_at.isoformat(),
                    "telegram_path": f"reports/{day}.telegram.html",
                    "twitter_path": f"reports/{day}.twitter.txt",
                },
                ensure_ascii=False,
                indent=2,
            ),
        )
    return report_path, content, section_enriched


def load_report_cache(root: Path, target_date: date) -> dict | None:
    """Legge il report salvato per una data. Ritorna dict con digest_raw, digest_items (opz.), generated_at, … o None."""
    from media_advisor.db.repository import fetch_daily_report_cache_dict
    from media_advisor.db.session import session_scope

    with session_scope(root, read_only=True) as session:
        from_db = fetch_daily_report_cache_dict(session, target_date)
    if from_db and from_db.get("digest_raw"):
        return from_db
    cache_path = root / "reports" / f"{target_date.isoformat()}.json"
    if not cache_path.exists():
        return None
    try:
        return _json.loads(cache_path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _load_channel_name_map(root: Path) -> dict[str, str]:
    try:
        raw = load_channels_config_dict(root)
        cfg = ChannelsConfig.model_validate(raw)
        return {channel.id: channel.name for channel in cfg.channels}
    except (FileNotFoundError, JSONDecodeError, OSError, ValidationError):
        return {}


def _validate_digest_output(text: str) -> list[str]:
    """Richiede le tre intestazioni nell'ordine corretto e righe voce ben formate; le sezioni possono essere senza righe."""
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

    return errors


def _is_valid_digest_output(text: str) -> bool:
    return not _validate_digest_output(text)


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
    model: str = DIGEST_MODEL,
) -> str | None:
    last_text: str | None = None
    for max_tokens in DIGEST_TOKEN_STEPS:
        completion = await client.chat.completions.create(
            model=model,
            messages=messages,
            max_tokens=max_tokens,
            temperature=0.4,
        )
        record_openai_chat_completion(model, completion)
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
    api_key: str,
    model: str | None = None,
    base_url: str | None = None,
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

    effective_model = model or DIGEST_MODEL
    client = openai.AsyncOpenAI(api_key=api_key, base_url=base_url)
    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"Indiscrezioni del {_format_date_it(target_date)}:\n\n"
                + "\n".join(lines)
            ),
        },
    ]
    denied_fallback_lines = _build_denied_fallback_lines(day_tips, channel_names)

    digest_text = await _complete_digest_with_token_retry(client, messages, model=effective_model)
    if not digest_text:
        raise DigestGenerationError("Output digest vuoto ricevuto dal modello.")
    digest_text = _strip_model_preamble(digest_text)
    digest_text = _normalize_digest_output(digest_text)
    if has_denied_tip:
        digest_text = _repair_smentita_section(digest_text, denied_fallback_lines)
        digest_text = _normalize_digest_output(digest_text)

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
    retry_text = await _complete_digest_with_token_retry(client, retry_messages, model=effective_model)
    retry_text = _strip_model_preamble(retry_text or "")
    retry_text = _normalize_digest_output(retry_text)
    if has_denied_tip:
        retry_text = _repair_smentita_section(retry_text, denied_fallback_lines)
        retry_text = _normalize_digest_output(retry_text)
    retry_errors = _validate_digest_output(retry_text or "")
    if retry_text and not retry_errors:
        return retry_text

    raise DigestGenerationError(
        "Digest non pubblicabile dopo retry. Errori residui: "
        + "; ".join(retry_errors[:6])
    )
