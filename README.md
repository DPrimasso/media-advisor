# Media Advisor

Analisi AI di video YouTube: estrae trascrizioni, identifica temi, claim e bias per canali monitorati.

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
| `npm run backfill-dates -- --channel=open-var` | Solo un canale |
| `cd web && npm run dev` | Avvia dashboard |

## Dashboard

```bash
cd web
npm install
npm run dev
```

La dashboard legge da `web/public/analysis/`. Esegui `npm run prepare-public` (o riavvia `npm run dev`) dopo aver generato nuove analisi.

## Piano Creator Advisor (quality upgrade)

Per la pianificazione completa delle migliorie quality/advisor:

- `docs/advisor-quality-roadmap.md` - roadmap, architettura target, milestone, rischi.
- `docs/advisor-quality-task-breakdown.md` - task operativi per sprint con DoD e verifiche.

## API

- **TranscriptAPI.com** – trascrizioni YouTube (credit-based)
- **OpenAI** – analisi tramite GPT

## Licenza

MIT
