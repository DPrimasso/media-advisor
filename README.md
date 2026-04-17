# Media Advisor

Analisi AI di video YouTube: estrae trascrizioni, identifica temi, claim e bias per canali monitorati. Vedi [ROADMAP.md](ROADMAP.md) per stato e piano modifiche.

## Setup

```bash
npm install
cp .env.example .env
# Modifica .env con TRANSCRIPT_API_KEY e OPENAI_API_KEY
```

## Struttura progetto

```
media-advisor/
├── channels/           # Config canali e liste video
│   ├── channels.json   # Registro canali (versionato)
│   └── {id}.json       # URL video per canale (locale, non in git)
├── transcripts/        # Trascrizioni (per canale)
│   ├── {channel_id}/   # transcript per canale
│   └── _misc/          # Fetch singoli senza canale
├── analysis/           # Output analisi (per canale)
├── web/                # Dashboard Vue.js
├── mercato/            # Tip mercato + index (locale, non in git)
└── scripts/            # Utility
```

**Dati locali (non in git):** `transcripts/`, `analysis/`, `mercato/`, liste `channels/*.json` (tranne che il registro `channels/channels.json`). Dopo un clone crea le liste video e lancia pipeline / `mercato-scan` come al solito.

## Comandi

| Comando | Descrizione |
|---------|-------------|
| `npm run run-list` | Pipeline principale: scarica transcript, analizza video, analisi canale |
| `npm run run-list -- --channel=id` | Solo un canale |
| `npm run transcript <url>` | Transcript singolo → `transcripts/_misc/` |
| `npm run transcript <url> --channel=id` | Transcript singolo → `transcripts/{id}/` |
| `npm run add-punto-chiaro` | Aggiunge "Il punto chiaro" da @radiocrc2023 a Umberto Chiariello |
| `npm run migrate-transcripts` | Migra transcript flat → per-canale (una tantum) |
| `npm run backfill-dates` | Recupera solo le date mancanti (TranscriptAPI/yt-dlp/Piped/Invidious) |
| `npm run backfill-dates -- --channel=id` | Solo un canale |
| `npm run auto-update` | Fetch nuovi video (regole) → merge → transcript + analisi (automatico) |
| `npm run auto-update -- --channel=id` | Solo un canale |
| `npm run dev` | Server + dashboard (Inbox funziona) |

**Auto-update giornaliero**: pianifica `npm run auto-update` con Task Scheduler (Windows) o cron (`0 8 * * *` = ogni giorno alle 8).

## Mercato (tip calciomercato)

- **Analisi singolo video**:
  - `python -m media_advisor.cli mercato-analyze <video_id> --channel <channel_id> --force`
- **Scan batch su transcript già scaricati**:
  - `python -m media_advisor.cli mercato-scan --channel <channel_id> --force`
- **Rebuild index (consigliato dopo modifiche a filtri/prompt o per ripulire dati “stale”)**:
  - `python -m media_advisor.cli mercato-rebuild-index --prune-non-mercato`

## Dashboard

```bash
cd web && npm install
npm run dev   # solo frontend (richiede server su 3002 per Inbox)
```

**Dev completo** (server API + dashboard, per Inbox e conferma video):
```bash
npm run dev   # avvia server (3002) + Vite in parallelo
```

La dashboard legge:
- `analysis/` via `web/public/analysis/` (copiato con `npm run prepare-public`)
- `mercato/` via API `http://localhost:3002/api/mercato/*`

Nota: `npm run dev` in root ora esegue un pre-step `dev:kill` per liberare le porte `3001/3002/5173/5174` e avviare sempre istanze “pulite”.

## Piano Creator Advisor (quality upgrade)

Per la pianificazione completa delle migliorie quality/advisor:

- `docs/advisor-quality-roadmap.md` - roadmap, architettura target, milestone, rischi.
- `docs/advisor-quality-task-breakdown.md` - task operativi per sprint con DoD e verifiche.

## API

- **TranscriptAPI.com** – trascrizioni YouTube (credit-based)
- **OpenAI** – analisi tramite GPT

## Licenza

MIT
