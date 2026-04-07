# Project Overview

## Cos'è Media Advisor

Strumento per analizzare video YouTube di opinionisti di calcio italiano (principalmente Napoli).

**Flusso:**
```
YouTube → TranscriptAPI → transcript JSON
                              ↓
                    Python pipeline (PydanticAI + gpt-4o-mini)
                              ↓
                    analysis/<channel>/<video>.json
                              ↓
                    FastAPI server (server/api.py, porta 3001)
                              ↓
                    Vue.js frontend (web/, porta 5173 in dev)
```

## Struttura directory

```
media-advisor/
├── CLAUDE.md                  # Caricato automaticamente da Claude Code
├── docs/                      # Questa documentazione
├── .env                       # TRANSCRIPT_API_KEY + OPENAI_API_KEY (non in git)
├── pyproject.toml             # Config Python package + dipendenze
├── package.json               # Solo frontend + npm run dev/server
│
├── channels/                  # Configurazione canali e liste video
│   ├── channels.json          # Fetch rules per ogni canale
│   ├── azzurro-fluido.json    # Lista URL video (148 video)
│   ├── umberto-chiariello.json
│   ├── neschio.json
│   ├── open-var.json          # Vuoto — canale non ancora configurato
│   └── pending.json           # Video in attesa approvazione (Inbox UI)
│
├── transcripts/               # Transcript scaricati
│   └── <channel_id>/<video_id>.json
│
├── analysis/                  # Output analisi pipeline
│   └── <channel_id>/<video_id>.json
│
├── server/
│   ├── api.py                 # FastAPI server (3 endpoint + static files)
│   └── api.ts                 # OBSOLETO — rimosso, sostituito da api.py
│
├── src/
│   └── media_advisor/         # Package Python principale
│       ├── cli.py             # Typer CLI (media-advisor command)
│       ├── config.py          # Settings via pydantic-settings
│       ├── run_pipeline.py    # Orchestratore run-list
│       ├── fetch.py           # Fetch nuovi video da canali
│       ├── merge.py           # Merge pending → channel lists
│       ├── mcp_server.py      # MCP server (tools per query cross-video)
│       ├── validate.py        # Validazione dati
│       ├── pipeline/
│       │   ├── analyze_v2.py      # Orchestratore analisi singolo video
│       │   ├── cleaner.py         # Pulizia transcript
│       │   ├── segmenter.py       # Segmentazione tematica
│       │   ├── extractor.py       # Estrazione claim via PydanticAI
│       │   ├── aggregator.py      # Dedup + aggregazione temi
│       │   ├── specificity.py     # Filtro claim troppo generici
│       │   ├── entity_normalizer.py
│       │   └── summarizer.py      # AI summary 2-3 frasi
│       ├── models/
│       │   ├── claims.py          # Schema Claim, Theme, VideoAnalysis
│       │   ├── analysis.py        # AnalysisResult (output finale)
│       │   ├── channels.py        # ChannelsConfig, FetchRule
│       │   ├── pending.py         # PendingVideo, PendingResult
│       │   └── transcript.py      # TranscriptResponse, TranscriptSegment
│       ├── io/
│       │   ├── json_io.py         # Lettura/scrittura JSON atomica
│       │   └── paths.py           # Path helpers
│       └── transcript_api/
│           └── client.py          # Client async TranscriptAPI (httpx + retry)
│
├── src/analyzer/              # Channel-level analysis (ancora TypeScript — da portare)
├── src/pipeline/channel-*.ts  # Channel profiler (ancora TypeScript — da portare)
│
├── web/                       # Frontend Vue 3 + Vite (rimane JS/TS)
│   ├── src/
│   │   ├── views/             # HomeView, ChannelView, InboxView, TrendView, SquadreView
│   │   └── composables/       # useChannelsData, useClaimsFilter, ecc.
│   └── public/analysis/       # Copia statica di analysis/ per il frontend
│
├── eval/                      # Framework valutazione (ancora TypeScript)
│   ├── human_gold/            # Ground truth manuale
│   ├── videos_sample.json     # Sample video per eval
│   └── run-baseline.ts / run-eval.ts
│
└── scripts/                   # Utility one-time (ancora TypeScript)
    ├── add-punto-chiaro.ts
    ├── backfill-dates.ts
    └── migrate-transcripts.ts
```

## Canali configurati

| id | nome | fetch_rule | video_list | note |
|----|------|------------|------------|------|
| azzurro-fluido | Azzurro Fluido | transcript_api, last_n:15, exclude reaction/live | azzurro-fluido.json | 148 video, validato |
| umberto-chiariello | Umberto Chiariello | transcript_api, title_contains "Il punto chiaro", last_n:50 | umberto-chiariello.json | |
| neschio | Neschio | transcript_api, last_n:50, exclude reaction | neschio.json | |
| open-var | Open VAR | non configurato | open-var.json | manca URL YouTube |

## Output analisi (schema)

```json
{
  "video_id": "b4bHnIgT_74",
  "analyzed_at": "2026-03-31T15:16:20.781Z",
  "metadata": { "title": "...", "author_name": "...", "published_at": null },
  "summary": "Riassunto AI 2-3 frasi in italiano...",
  "topics": [
    { "name": "infortunio", "relevance": "high" },
    { "name": "media", "relevance": "high" }
  ],
  "claims": [{
    "claim_id": "uuid",
    "target_entity": "Lukaku",
    "entity_type": "player",
    "dimension": "injury",
    "claim_type": "FACT",
    "stance": "NEG",
    "intensity": 1,
    "modality": "CERTAIN",
    "claim_text": "Lukaku ha avuto due problemi fisici da novembre.",
    "evidence_quotes": [{
      "quote_text": "è il secondo problema che ho avuto da inizio novembre.",
      "start_sec": 154.8,
      "end_sec": 198.5
    }]
  }]
}
```
