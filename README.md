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
| `npm run eval:advisor-quality` | Report quality advisor su `analysis/*/_advisor.json` |
| `npm run eval:advisor-quality -- --save-baseline=eval/advisor-quality-baseline.json` | Salva baseline per confronti futuri |
| `npm run eval:advisor-quality -- --baseline=eval/advisor-quality-baseline.json` | Confronto before/after con baseline |
| `npm run eval:advisor-gate -- --channel=<id> --min-fidelity=70` | Quality gate rollout per canale |
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
- `docs/advisor-scoring-methodology.md` - formula scoring, flags rollout, benchmark e limiti.

## Feature flags Advisor

Variabili opzionali (env):

- `ADVISOR_ENABLED=true|false`
- `ADVISOR_PREDICTION_ENABLED=true|false`
- `ADVISOR_MIN_FIDELITY=0..100`

Override CLI:

- `npm run run-list -- --advisor=off`
- `npm run run-list -- --advisor-predictions=off`
- `npm run run-list -- --advisor-min-fidelity=70`

Gate rapido rollout:

- `npm run eval:advisor-gate -- --channel=<id> --min-fidelity=70`
- `npm run eval:advisor-gate -- --min-fidelity=70 --min-advisor-score=60`

CI quality gate:

- workflow GitHub Actions: `.github/workflows/advisor-quality-gate.yml`
- trigger automatico su PR verso `main/master`
- trigger manuale con input (`channel`, `min_fidelity`, `min_advisor_score`)

## API

- **TranscriptAPI.com** – trascrizioni YouTube (credit-based)
- **OpenAI** – analisi tramite GPT

## Licenza

MIT
