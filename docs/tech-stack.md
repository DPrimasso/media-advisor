# Tech Stack — Media Advisor

_Aggiornato: aprile 2026_

---

## Stack

| Layer | Tecnologia | Versione |
|-------|-----------|---------|
| Pipeline + CLI | Python | 3.12+ (sviluppato su 3.13) |
| AI extraction | PydanticAI + OpenAI gpt-4o-mini | pydantic-ai>=0.0.14 |
| API server | FastAPI + uvicorn | fastapi>=0.135.0 |
| Frontend | Vue 3 + Vite | vue ^3.x |
| Dev runner | concurrently (npm) | ^9.2.1 |

---

## Dipendenze Python (pyproject.toml)

### Runtime

| Pacchetto | Versione | Uso |
|-----------|---------|-----|
| pydantic | >=2.7.0 | Models, validation |
| pydantic-settings | latest | Config da .env |
| pydantic-ai | >=0.0.14 | AI extraction pipeline |
| typer | >=0.12.3 | CLI |
| httpx | >=0.27.0 | Client async (TranscriptAPI) |
| openai | >=1.30.0 | API OpenAI (gpt-4o-mini) |
| fastapi | >=0.135.0 | API server |
| uvicorn | >=0.29.0 | ASGI server |
| beautifulsoup4 | >=4.12.0 | Scraping Transfermarkt |
| curl_cffi | >=0.7.0 | HTTP con TLS fingerprint (Transfermarkt) |
| mcp | >=1.0.0 | MCP server |

### Dev

| Pacchetto | Uso |
|-----------|-----|
| mypy | Type checking |
| pytest | Test suite (non ancora popolata) |
| ruff | Linter |
| types-requests | Type stubs |

---

## Dipendenze npm (package.json root)

Solo per orchestrare dev server. Il frontend ha il suo `web/package.json`.

| Pacchetto | Uso |
|-----------|-----|
| concurrently | Avvia server + web in parallelo con `npm run dev` |
| typescript | Compila i file TS ancora presenti in src/ (analisi canale) |
| tsx | Esegue TS on-the-fly per i file in src/ |
| @types/node | Type stubs Node |

---

## Variabili d'ambiente (.env)

```bash
TRANSCRIPT_API_KEY=<key>   # API key per TranscriptAPI (scarica transcript YouTube)
OPENAI_API_KEY=<key>       # API key OpenAI (gpt-4o-mini per estrazione claim e mercato)
```

---

## Vincoli ambiente (Windows)

- **Due ambienti Python su Windows**: usare sempre `python -m pip install` (non `pip` standalone)
- **Entry point**: dopo `python -m pip install -e ".[dev]"`, il comando `media-advisor` è disponibile nel PATH del venv
- **Porte**: server FastAPI su 3001, Vite su 5173 (o 5174 se 5173 occupata)
- **npm run dev:kill**: script PowerShell che killa i processi sulle porte 3001/5173/5174

---

## Struttura file di configurazione

| File | Scopo |
|------|-------|
| `.env` | API keys (non in git) |
| `.env.example` | Template configurazione |
| `pyproject.toml` | Package Python, dipendenze, entry point |
| `package.json` | npm scripts (dev runner) |
| `tsconfig.json` | TypeScript config (src/ TS residuo) |
| `web/package.json` | Dipendenze frontend Vue |
| `web/vite.config.js` | Proxy `/api` → :3001, port 5173 |
| `channels/channels.json` | Configurazione canali e fetch rules |
| `.env` | TRANSCRIPT_API_KEY, OPENAI_API_KEY |

---

## Note problemi noti

- `curl_cffi` può richiedere una versione specifica su alcune piattaforme Windows: `python -m pip install curl_cffi>=0.7.0`
- Il server FastAPI serve anche i file statici da `web/dist/` se la build esiste (SPA fallback)
- In dev, Vite non usa `web/dist/` ma proxia direttamente le API
- Transfermarkt scraping è fragile: se il sito cambia HTML, `mercato/scraper.py` va aggiornato
