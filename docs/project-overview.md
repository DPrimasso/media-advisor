# Project Overview

_Aggiornato: aprile 2026_

## Cos'è Media Advisor

Strumento per analizzare video YouTube di opinionisti di calcio italiano.
Estrae claim strutturati e indiscrezioni di calciomercato dai transcript, li archivia e li visualizza in una dashboard.

**Flusso principale:**
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

**Flusso mercato:**
```
transcript JSON → mercato/analyzer.py → mercato/tips/<channel>/<video>.json
                                              ↓
                                     mercato/index.json (index globale)
                                              ↓
                                     verifier.py vs transfers.json
                                              ↓
                                     /api/mercato/* → MercatoView
```

---

## Struttura directory

```
media-advisor/
├── CLAUDE.md                  # Caricato automaticamente da Claude Code
├── ROADMAP.md                 # Stato progetto e gap aperti
├── docs/                      # Documentazione di progetto
├── .env                       # TRANSCRIPT_API_KEY + OPENAI_API_KEY (non in git)
├── pyproject.toml             # Python package, dipendenze, entry point
├── package.json               # npm run dev/server/prepare-public
│
├── channels/                  # Configurazione canali e liste video
│   ├── channels.json          # Fetch rules per ogni canale (7 canali)
│   ├── <channel_id>.json      # Lista URL video per canale
│   ├── pending.json           # Video in attesa approvazione (Inbox UI)
│   └── video-dates.json       # Cache date pubblicazione
│
├── transcripts/               # Transcript scaricati
│   └── <channel_id>/<video_id>.json
│
├── analysis/                  # Output analisi pipeline claims
│   └── <channel_id>/<video_id>.json
│
├── mercato/                   # Calciomercato
│   ├── index.json             # Index globale tip (1350+)
│   ├── transfers.json         # DB trasferimenti ufficiali
│   ├── player-aliases.json    # Mapping sinonimi giocatori
│   ├── player-tm-ids.json     # ID Transfermarkt per giocatori
│   └── tips/
│       └── <channel_id>/<video_id>.json   # Tip estratte per video
│
├── server/
│   └── api.py                 # FastAPI server (porta 3001)
│
├── src/
│   ├── media_advisor/         # Package Python principale (entry: media-advisor CLI)
│   │   ├── cli.py             # Typer CLI
│   │   ├── config.py          # Settings via pydantic-settings
│   │   ├── fetch.py           # Fetch nuovi video da canali
│   │   ├── merge.py           # Merge pending → channel lists
│   │   ├── run_pipeline.py    # Orchestratore batch run-list
│   │   ├── mcp_server.py      # MCP server tools
│   │   ├── pipeline/          # Analisi singolo video (8 moduli)
│   │   │   ├── analyze_v2.py      # Orchestratore
│   │   │   ├── cleaner.py         # Pulizia transcript
│   │   │   ├── segmenter.py       # Segmentazione tematica
│   │   │   ├── extractor.py       # Estrazione claim (PydanticAI)
│   │   │   ├── aggregator.py      # Dedup + aggregazione temi
│   │   │   ├── specificity.py     # Filtro claim generici
│   │   │   ├── entity_normalizer.py
│   │   │   └── summarizer.py      # AI summary 2-3 frasi
│   │   ├── mercato/           # Modulo calciomercato (7 moduli)
│   │   │   ├── models.py          # MercatoTip, TransferRecord, OutcomeValue
│   │   │   ├── analyzer.py        # Analisi video → tip
│   │   │   ├── aggregator.py      # Aggregazione index globale
│   │   │   ├── extractor.py       # Estrazione tip da transcript
│   │   │   ├── scraper.py         # Scraping Transfermarkt
│   │   │   ├── transfer_db.py     # CRUD DB trasferimenti
│   │   │   ├── verifier.py        # Verifica tip vs DB
│   │   │   └── corroborator.py    # Corroborazione incrociata
│   │   ├── models/            # Pydantic models (Claim, VideoAnalysis, ChannelsConfig, …)
│   │   ├── io/                # JSON I/O atomica, path helpers
│   │   └── transcript_api/    # Client async TranscriptAPI (httpx + retry)
│   │
│   ├── analyzer/              # Analisi aggregata canale (TypeScript — da portare in Python)
│   ├── pipeline/              # Channel profiler, inconsistency detector (TypeScript — da portare)
│   ├── schema/                # claims.ts (TypeScript — da portare)
│   ├── channel-analyze.ts     # (TypeScript — da portare)
│   ├── channel-resolver.ts    # (TypeScript — da portare)
│   └── cli-channel-analyze.ts # Entry point analisi canale (TypeScript — da portare)
│
├── web/                       # Frontend Vue 3 + Vite (rimane JS/TS)
│   └── src/
│       └── views/             # HomeView, ChannelView, InboxView, MercatoView,
│                              # MercatoPlayerView, SquadreView, TrendView, TrendMacroView
│
├── eval/                      # Framework valutazione (parzialmente obsoleto)
│   ├── run_baseline.py        # Baseline eval Python
│   ├── run-eval.ts / run-baseline.ts   # TypeScript eval (non aggiornati)
│   └── videos_sample.json
│
└── scripts/                   # Script one-time (TypeScript)
    ├── add-punto-chiaro.ts
    ├── backfill-dates.ts
    └── migrate-transcripts.ts
```

---

## Canali configurati

| id | Nome | fetch_rule | mercato_channel | Note |
|----|------|------------|-----------------|------|
| fabrizio-romano-italiano | Fabrizio Romano Italiano | transcript_api, last_n:500, exclude_live | ✅ | 1253 tip estratte |
| azzurro-fluido | Azzurro Fluido | transcript_api, last_n:15, exclude_live | — | canale principale claims |
| umberto-chiariello | Umberto Chiariello | transcript_api, title_contains "Il punto chiaro", last_n:50 | — | |
| neschio | Neschio | transcript_api, last_n:50 | — | |
| tuttomercatoweb | TuttoMercatoWeb.com | transcript_api, last_n:400, exclude_live | ✅ | |
| calciomercato-it | Calciomercato.it | transcript_api, last_n:400, exclude_live | ✅ | |
| nico-schira | Nicolò Schira | transcript_api, last_n:400, exclude_live | ✅ | |

---

## Schema output analisi (claims)

```json
{
  "video_id": "b4bHnIgT_74",
  "analyzed_at": "2026-04-15T12:00:00Z",
  "metadata": { "title": "...", "author_name": "...", "published_at": "2026-04-01" },
  "summary": "Riassunto AI 2-3 frasi in italiano...",
  "topics": [
    { "name": "infortunio", "relevance": "high" }
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

## Schema output mercato (tip)

```json
{
  "tip_id": "uuid",
  "video_id": "abc123",
  "channel_id": "fabrizio-romano-italiano",
  "player_name": "Osimhen",
  "player_slug": "osimhen",
  "from_club": "Napoli",
  "to_club": "PSG",
  "fee_mention": "100 milioni",
  "confidence": "high",
  "outcome": "non_verificata",
  "mentioned_at": "2026-01-15T00:00:00Z",
  "quote_text": "Osimhen al PSG, affare vicino alla chiusura",
  "quote_start_sec": 45.2,
  "quote_end_sec": 52.8,
  "corroborated_by": ["nico-schira", "tuttomercatoweb"]
}
```
