# Media Advisor — Guida per Claude Code

Questo file viene caricato automaticamente da Claude Code ad ogni sessione.
Dettagli completi in `docs/`.

## Cos'è il progetto

Strumento per analizzare video YouTube di opinionisti di calcio italiano.
Scarica transcript via TranscriptAPI, li analizza con GPT-4o-mini estraendo claim strutturati
e indiscrezioni di calciomercato, li visualizza in una dashboard Vue.js.

## Stack

| Layer | Tech |
|-------|------|
| Pipeline + CLI | Python 3.13, PydanticAI, OpenAI gpt-4o-mini |
| API server | FastAPI + uvicorn (`server/api.py`) |
| Frontend | Vue 3 + Vite (`web/`) |
| Dev runner | `npm run dev` → uvicorn (3002) + Vite (5173) |

## Regole critiche

1. **Il canonical è Python** — la pipeline e il CLI sono in `src/media_advisor/`. Non toccare i file `.ts` della pipeline (sono stati rimossi). Se serve modificare la pipeline, modificare i file Python.
2. **Usare `python -m pip`** — su Windows ci sono due ambienti Python; `pip` standalone punta a quello sbagliato.
3. **Validare su singolo video prima di scalare** — `media-advisor analyze <video_id> --channel <channel_id> --force`, poi mostrare il risultato prima di lanciare il batch.

## Comandi principali

```bash
# Dev
npm run dev                          # uvicorn + Vite in parallelo

# Pipeline claims
media-advisor analyze <id> --channel <ch> --force   # test singolo video
media-advisor run-list --channel <ch> --force-analyze  # batch canale
media-advisor auto-update            # fetch → merge → pipeline automatico

# Pipeline mercato
media-advisor mercato-scan --channel fabrizio-romano-italiano
media-advisor mercato-verify
media-advisor mercato-rebuild-index

# Installazione dipendenze Python
python -m pip install -e ".[dev]"
```

## Canali

| id | Nome | mercato | Note |
|----|------|---------|------|
| fabrizio-romano-italiano | Fabrizio Romano Italiano | ✅ | canale mercato principale |
| azzurro-fluido | Azzurro Fluido | — | canale claims principale, 148 video |
| umberto-chiariello | Umberto Chiariello | — | "Il punto chiaro" |
| neschio | Neschio | — | |
| tuttomercatoweb | TuttoMercatoWeb.com | ✅ | |
| calciomercato-it | Calciomercato.it | ✅ | |
| nico-schira | Nicolò Schira | ✅ | |

## Cosa NON è ancora Python (rimane TS)

- `src/analyzer/` + `src/cli-channel-analyze.ts` — analisi aggregata canale (da portare in Python)
- `eval/` — framework valutazione (parzialmente obsoleto)
- `web/` — frontend Vue (rimane sempre Vite/JS)

## Documentazione dettagliata

- [docs/project-overview.md](docs/project-overview.md) — architettura, struttura directory, canali, schema output
- [docs/commands.md](docs/commands.md) — tutti i comandi CLI + npm
- [docs/pipeline-design.md](docs/pipeline-design.md) — come funziona la pipeline, schema claim e mercato tip
- [docs/tech-stack.md](docs/tech-stack.md) — dipendenze, versioni, vincoli ambiente
- [ROADMAP.md](ROADMAP.md) — stato progetto e gap aperti
