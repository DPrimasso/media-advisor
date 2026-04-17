# Media Advisor

AI-powered YouTube video analysis tool for Italian sports media. Monitors YouTube channels, extracts transcripts, and uses OpenAI to identify themes, claims, and biases.

## Cursor Cloud specific instructions

### Services

| Service | Command | Port | Notes |
|---|---|---|---|
| Express API server | `npm run server` | 3002 | Manages pending video inbox workflow |
| Vue.js Dashboard | `cd web && npm run dev` (or `npm run dev` from root) | 5173 | Vite dev server; proxies `/api` to `:3002` |
| CLI pipeline | `npm run run-list` | N/A | Requires `TRANSCRIPT_API_KEY` + `OPENAI_API_KEY` |

### Key notes

- **No database**: all data is flat JSON files in `channels/`, `transcripts/`, `analysis/`.
- **No lint/test commands defined**: there are no ESLint config, test framework, or lint npm scripts in this repo. `npm run build` (runs `tsc`) is the closest check.
- The Tutti/Trend/Squadre dashboard pages show a JSON parse error when `analysis/` directory is empty (no pipeline data). This is expected without API keys — the Inbox page works independently via the Express API.
- `web/scripts/prepare-public.js` runs automatically before `vite` (as part of `npm run dev` in `web/`). It copies analysis data into `web/public/analysis/`. If no analysis data exists, it creates an empty `index.json`.
- The Vite dev server proxies `/api` requests to `http://localhost:3002` — start the API server first if you need the Inbox workflow.
- Environment variables: copy `.env.example` to `.env` and set `TRANSCRIPT_API_KEY` and `OPENAI_API_KEY` to run the CLI pipeline.
- The CLI pipeline is slow (~1 min per video due to transcript + OpenAI API calls). Use `--channel=<id>` to scope to a single channel and `--skip-channel-analysis` to skip the summary step.
- See `README.md` for the full list of CLI commands.
