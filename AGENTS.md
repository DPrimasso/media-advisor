# Media Advisor

AI-powered YouTube video analysis tool for Italian sports media. Monitors YouTube channels, extracts transcripts, and uses OpenAI to identify themes, claims, and biases.

## Cursor Cloud specific instructions

### Services

| Service | Command | Port | Notes |
|---|---|---|---|
| FastAPI (dev) | `npm run server` | 3002 | `--reload`; inbox + API |
| FastAPI (prod) | `npm run server:prod` | 3002 (or `PORT`) | No reload; serve `web/dist` if built |
| Vue.js Dashboard | `cd web && npm run dev` (or `npm run dev` from root) | 5173 | Vite dev server; proxies `/api` to `:3002` |
| CLI pipeline | `npm run run-list` | N/A | Requires `TRANSCRIPT_API_KEY` + `OPENAI_API_KEY` |

### Key notes

- **SQLite is the runtime store** (`data/media_advisor.sqlite` by default): transcripts, daily reports, video analysis, mercato data, and channel registry/lists. Legacy trees (`data/transcripts/`, `data/analysis/`, `mercato/`, `channels/*.json`) may exist as a static archive; the app does not treat them as the source of truth after migration. Use `python -m media_advisor.cli db-migrate-from-json` to import legacy JSON once.
- **No lint/test commands defined**: there are no ESLint config, test framework, or lint npm scripts in this repo. `npm run build` at repo root (if present) / `cd web && npm run build` for the Vue app; Python tests: `python -m pytest tests/`.
- **Production Windows**: see `README.md` (NSSM, Task Scheduler, `MEDIA_ADVISOR_SYNC_SECRET` + header `X-Media-Advisor-Sync` for `POST /api/sync*` and `/api/fetch-now`, `GET /api/health` / `GET /api/health/ready`). Restrict `MEDIA_ADVISOR_CORS_ORIGINS` when exposing the API beyond same-origin; many `POST` routes are not protected by the sync secret — use network controls or a reverse proxy (see README).
- The Tutti/Trend/Squadre dashboard reads analysis from `web/public/analysis/`, materialized from the DB by `prepare-public` (via `python -m media_advisor.tools.dump_analysis_public`). Empty DB yields minimal/empty public JSON — expected without pipeline data or keys.
- `web/scripts/prepare-public.js` runs automatically before `vite` (as part of `npm run dev` in `web/`). It invokes the Python dump to refresh `web/public/analysis/` from SQLite (not a copy of `data/analysis/`).
- The Vite dev server proxies `/api` requests to `http://localhost:3002` — start the API server first if you need the Inbox workflow.
- Environment variables: copy `.env.example` to `.env` and set `TRANSCRIPT_API_KEY` and `OPENAI_API_KEY` to run the CLI pipeline.
- The CLI pipeline is slow (~1 min per video due to transcript + OpenAI API calls). Use `--channel=<id>` to scope to a single channel and `--skip-channel-analysis` to skip the summary step.
- See `README.md` for the full list of CLI commands.
