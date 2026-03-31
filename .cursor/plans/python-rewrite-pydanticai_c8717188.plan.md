---
name: python-rewrite-pydanticai
overview: Riscrivere Media Advisor in Python 3.12 async con typing rigoroso, Pydantic/PydanticAI per output strutturato, e un MCP server per tool-calling (indicizzazione/query/report), più frontend nuovo al posto di Vue.
todos:
  - id: scaffold-python
    content: Creare struttura Python (`pyproject.toml`, `src/media_advisor/`, settings, modelli Pydantic) + toolchain (ruff/mypy/pytest).
    status: done
  - id: port-io-config
    content: Portare path helpers e I/O JSON atomico; leggere/scrivere `channels/*.json`, `pending.json`, `analysis/`, `transcripts/` con modelli Pydantic.
    status: done
  - id: port-transcript
    content: Implementare client async TranscriptAPI (httpx + retry/backoff) + enrich published_at + fallback transcript.
    status: done
  - id: port-v2-pipeline
    content: Portare cleaner/segmenter/extractor/aggregator/filter; usare PydanticAI per estrazione claim con output validato.
    status: done
  - id: cli-parity
    content: Implementare CLI (Typer) per run-list/auto-update/fetch-now/confirm e replicare comportamento TS.
    status: done
  - id: mcp-server
    content: Implementare MCP server con tools (index/query/channel_report) e storage locale (SQLite FTS5 + opzionale embeddings).
    status: done
  - id: rewrite-frontend
    content: Riscrivere `web/` in React/Vite TS mantenendo Inbox e lettura analisi; consumare API locale e (opzionale) SSE progress.
    status: pending
  - id: validation-migration
    content: Aggiungere script di validazione/migrazione per JSON esistenti e test di regressione su alcuni video/canali.
    status: done
  - id: todo-1774888737132-ifm6xm1ie
    content: Pulire residui del vecchio codice
    status: pending
isProject: false
---

# Python rewrite (PydanticAI + MCP)

## Target di parità funzionale (da repo attuale)

- Input: `channels/channels.json`, `channels/{channel_id}.json`, `channels/pending.json`.
- Output: `transcripts/{channel_id}/{video_id}.json`, `analysis/{channel_id}/{video_id}.json` (stesso shape di `src/analyzer/types.ts` + claims compat).
- Flussi:
  - **Fetch pending**: equivalente `src/fetch-new-videos.ts`.
  - **Confirm**: append URL a liste canale + rimozione da pending (equivalente `server/api.ts` + `src/merge-pending.ts`).
  - **Pipeline**: transcript → enrich published_at → analyze v2 (segment/extract/aggregate/filter) → write analysis (equivalente `src/run-from-list.ts` + `src/analyze-v2.ts`).

## Architettura Python proposta

- Backend Python (monorepo) con package `media_advisor/`:
  - `media_advisor/config.py`: `Settings` via **pydantic-settings** (chiavi API, path root, rate limit, modello LLM, ecc.).
  - `media_advisor/models/`:
    - `channels.py`: `ChannelsConfig`, `ChannelConfig`, `FetchRule` (Union discriminata).
    - `pending.py`: `PendingVideo`, `PendingResult`.
    - `transcript.py`: `TranscriptResponse`, `TranscriptSegment`, `VideoMetadata`.
    - `claims.py`: porting di `src/schema/claims.ts` (Enum/typing + vincoli, max items, ecc.).
    - `analysis.py`: `AnalysisResult` compat con `src/analyzer/types.ts` + claim compat.
  - `media_advisor/io/`:
    - lettura/scrittura JSON atomica (write temp + replace), path helpers (porting di `src/paths.js`).
  - `media_advisor/transcript_api/`:
    - client async `httpx.AsyncClient` con retry/backoff (porting di `src/transcript-client.ts`).
    - fallback transcript (equivalente `youtube-transcript`): scegliere lib Python o fallback a fetch/parse.
  - `media_advisor/pipeline/`:
    - cleaner/segmenter/specificity/entity-normalizer/video-aggregator portati 1:1.
    - extractor con **PydanticAI**: output validato con modelli Pydantic (invece di `json_schema` manuale).
  - `media_advisor/cli.py` (Typer):
    - `run-list`, `auto-update`, `fetch-now`, `confirm`, `transcript`, `analyze`, `channel-analyze`.

## MCP (Model Context Protocol)

- Aggiungere un MCP server Python `media_advisor/mcp_server.py` che espone tools:
  - `index_transcripts`: indicizza transcript/claims su storage locale (default SQLite FTS5; opzionale LanceDB).
  - `query`: query semantica/ibrida (FTS + embedding opzionale) per cross-video.
  - `channel_report`: genera report per canale/data range usando pipeline + indice.
- I tools restituiscono output **Pydantic-validated** (json schema stabile), pronto per consumption UI.

## Frontend (riscrittura)

- Sostituire `web/` (Vue) con React/Vite (TypeScript) mantenendo UX Inbox + dashboard.
- API target (locale):
  - se scegliamo solo CLI, il frontend può leggere direttamente `analysis/` static (file) + usare un piccolo server locale per `/api/pending`, `/api/confirm`, `/api/fetch-now`.
  - proposta: `python -m media_advisor serve` avvia FastAPI su `localhost:3001` (solo locale) per Inbox + SSE progress; static serving del build.

## Packaging + best practices

- `pyproject.toml` (Python 3.12), `ruff`, `mypy`, `pytest`, `pre-commit`.
- Struttura `src/` style: `src/media_advisor/...`.
- Strict typing + `pydantic` v2.

## Migrazione dati

- Non cambia il layout su disco: riusi `channels/`, `analysis/`, `transcripts/`.
- Script di “one-shot validation” che carica e valida tutti i JSON esistenti con Pydantic (utile per ripulire schema drift).

## File chiave da portare (riferimenti)

- Pipeline: `src/run-from-list.ts`, `src/analyze-v2.ts`, `src/pipeline/extractor.ts`, `src/schema/claims.ts`.
- Inbox: `server/api.ts`, `src/merge-pending.ts`, `src/fetch-new-videos.ts`.
- UI inbox: `web/src/views/InboxView.vue`.

