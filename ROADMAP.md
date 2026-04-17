# Media Advisor — ROADMAP

_Aggiornato: aprile 2026_

---

## Stato attuale ✅

### Core pipeline (Python — completo)

- **Fetch video**: `fetch-now` via TranscriptAPI, con fetch rules per canale (last_n, title_contains, exclude_live)
- **Inbox flow**: `pending.json` → UI InboxView → `/api/confirm` → merge in video list
- **Transcript download**: client async httpx con retry
- **Pipeline analisi v2**: transcript → clean → segment → extract (PydanticAI + gpt-4o-mini) → aggregate → specificity filter → summary
- **Output**: `analysis/<channel_id>/<video_id>.json` con claims + evidence_quotes + summary
- **auto-update**: `media-advisor auto-update` — fetch → merge → pipeline (no passi manuali)

### Calciomercato (Python — avanzato)

- **Tip extraction**: `mercato-scan` / `mercato-analyze` estraggono indiscrezioni strutturate da transcript
- **Transfer DB**: `mercato/transfers.json` — trasferimenti ufficiali (manuale + Transfermarkt scraping)
- **Verifica outcome**: `mercato-verify` confronta tip vs DB, imposta `confermata`/`smentita`
- **Corroborazione incrociata**: tip corroborate tra canali diversi
- **Index globale**: `mercato/index.json` — 1350+ tip, filtrabili per player/canale/stagione/outcome
- **UI**: MercatoView, MercatoPlayerView con filtri, corroborazione, link YouTube

### Server + Frontend

- **FastAPI server** (`server/api.py`, porta 3001): endpoint video + mercato + static SPA fallback
- **Vue 3 + Vite** (porta 5173 in dev): 11 view (Home, Channel, Inbox, Mercato, Player, Squadre, Trend, TrendMacro)
- **Vite proxy**: `/api` → localhost:3001

### Canali attivi

| id | Nome | Tipo | Mercato | Video |
|----|------|------|---------|-------|
| fabrizio-romano-italiano | Fabrizio Romano Italiano | TranscriptAPI | ✅ | 500 max |
| azzurro-fluido | Azzurro Fluido | TranscriptAPI | — | 148 |
| umberto-chiariello | Umberto Chiariello | TranscriptAPI | — | last 50 |
| neschio | Neschio | TranscriptAPI | — | last 50 |
| tuttomercatoweb | TuttoMercatoWeb.com | TranscriptAPI | ✅ | 400 max |
| calciomercato-it | Calciomercato.it | TranscriptAPI | ✅ | 400 max |
| nico-schira | Nicolò Schira | TranscriptAPI | ✅ | 400 max |

---

## Da fare / Gap aperti

### 1. Analisi aggregata canale (TS → Python, sospeso)

`src/cli-channel-analyze.ts` + `src/analyzer/` fanno analisi a livello canale (profiling, inconsistency detection).
Non ancora portati in Python. Usati raramente — bassa priorità.

### 2. open-var non configurato

`channels/open-var.json` esiste ma `channels.json` non ha il canale. Serve URL YouTube di Open VAR.

### 3. Test suite

Dipendenze pytest/mypy/ruff presenti in `pyproject.toml` ma nessun test scritto.
Candidati: `mercato/verifier.py`, `pipeline/extractor.py`, `pipeline/aggregator.py`.

### 4. Eval framework

`eval/` ha `run_baseline.py` (Python) + `run-eval.ts` + `run-baseline.ts` (TypeScript, non aggiornati).
Il framework di valutazione non è integrato nella pipeline corrente.

### 5. Date tip mancanti

~1198 tip su 1350 hanno `mentioned_at: null`. Il campo `quote_start_sec` / `quote_end_sec`
è a `0.0` per molte tip estratte vecchie. Non bloccante, ma degrada la UI.

### 6. Transfermarkt scraping

`mercato-fetch-transfers` usa `curl_cffi` + BeautifulSoup per estrarre dati da Transfermarkt.
Funziona, ma fragile (HTML scraping). Da monitorare se cambia il sito.

---

## Comandi principali

Vedi [docs/commands.md](docs/commands.md) per la lista completa.

```bash
npm run dev                                          # server + frontend
media-advisor auto-update                            # fetch → merge → analisi
media-advisor run-list --channel <id> --force-analyze
media-advisor mercato-scan --channel fabrizio-romano-italiano
media-advisor mercato-verify
```
