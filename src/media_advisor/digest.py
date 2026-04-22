from __future__ import annotations

from datetime import date
from pathlib import Path

import openai

DIGEST_MODEL = "gpt-4.1-mini"

_CONFIDENCE_ORDER = {"confirmed": 0, "likely": 1, "rumor": 2, "denied": 3}
_CONFIDENCE_EMOJI = {
    "confirmed": "✅",
    "likely": "🔵",
    "rumor": "🔴",
    "denied": "❌",
}
_CHANNEL_NAMES: dict[str, str] = {
    "fabrizio-romano-italiano": "Fabrizio Romano",
    "azzurro-fluido": "Azzurro Fluido",
    "umberto-chiariello": "Umberto Chiariello",
    "neschio": "Neschio",
    "tuttomercatoweb": "TuttoMercatoWeb",
    "calciomercato-it": "Calciomercato.it",
    "nico-schira": "Nicolò Schira",
}
MONTHS_IT = [
    "", "Gennaio", "Febbraio", "Marzo", "Aprile", "Maggio", "Giugno",
    "Luglio", "Agosto", "Settembre", "Ottobre", "Novembre", "Dicembre",
]

_SYSTEM_PROMPT = (
    "Sei il redattore di un canale social specializzato in calciomercato italiano. "
    "Ricevi un elenco di indiscrezioni di mercato del giorno, ciascuna con fonte e livello di confidenza. "
    "Scrivi un sommario in italiano pronto per essere pubblicato sui social con queste regole:\n"
    "1. Inizia con una riga di titolo: '⚽ Calciomercato — [data]'.\n"
    "2. Ogni indiscrezione distinta è un paragrafo separato (massimo 30 parole).\n"
    "3. Inizia ogni paragrafo con l'emoji di confidenza già fornita nel dato.\n"
    "4. Cita sempre la fonte: 'Secondo [Fonte],' oppure 'Stando a [Fonte],'.\n"
    "5. Stile diretto e informativo, nomi giocatori in evidenza.\n"
    "6. Nessun elenco puntato, solo paragrafi brevi.\n"
    "7. Chiudi con una riga: '#Calciomercato #SerieA #transfermarket'."
)


async def generate_mercato_digest(
    root: Path,
    target_date: date,
    openai_api_key: str,
) -> str | None:
    """Genera un sommario mercato per la data indicata. Restituisce None se non ci sono tips."""
    from media_advisor.mercato.aggregator import get_all_tips

    all_tips = get_all_tips(root)
    day_tips = [
        t for t in all_tips
        if t.mentioned_at and t.mentioned_at.date() == target_date
    ]
    if not day_tips:
        return None

    day_tips.sort(key=lambda t: _CONFIDENCE_ORDER.get(str(t.confidence), 99))

    date_it = f"{target_date.day} {MONTHS_IT[target_date.month]} {target_date.year}"
    lines: list[str] = []
    for tip in day_tips[:20]:
        emoji = _CONFIDENCE_EMOJI.get(str(tip.confidence), "🔴")
        source = _CHANNEL_NAMES.get(tip.channel_id, tip.channel_id)
        line = f"{emoji} FONTE: {source} | {tip.player_name}"
        if tip.from_club or tip.to_club:
            line += f" ({tip.from_club or '?'} → {tip.to_club or '?'})"
        line += f": {tip.tip_text}"
        lines.append(line)

    client = openai.AsyncOpenAI(api_key=openai_api_key)
    completion = await client.chat.completions.create(
        model=DIGEST_MODEL,
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": f"Indiscrezioni del {date_it}:\n\n" + "\n".join(lines)},
        ],
        max_tokens=600,
        temperature=0.4,
    )
    return (completion.choices[0].message.content or "").strip() or None
