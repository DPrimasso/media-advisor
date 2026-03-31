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
│   ├── channels.json   # Registro canali
│   └── {id}.json       # URL video per canale
├── transcripts/        # Trascrizioni (per canale)
│   ├── {channel_id}/   # transcript per canale
│   └── _misc/          # Fetch singoli senza canale
├── analysis/           # Output analisi (per canale)
├── web/                # Dashboard Vue.js
└── scripts/            # Utility
```

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

## Dashboard

```bash
cd web && npm install
npm run dev   # solo frontend (richiede server su 3001 per Inbox)
```

**Dev completo** (server API + dashboard, per Inbox e conferma video):
```bash
npm run dev   # avvia server (3001) + Vite in parallelo
```

La dashboard legge da `web/public/analysis/`. Esegui `npm run prepare-public` dopo nuove analisi (o riavvia `npm run dev`).

## Piano Creator Advisor (quality upgrade)

Per la pianificazione completa delle migliorie quality/advisor:

- `docs/advisor-quality-roadmap.md` - roadmap, architettura target, milestone, rischi.
- `docs/advisor-quality-task-breakdown.md` - task operativi per sprint con DoD e verifiche.

## API

- **TranscriptAPI.com** – trascrizioni YouTube (credit-based)
- **OpenAI** – analisi tramite GPT

## Licenza

MIT
