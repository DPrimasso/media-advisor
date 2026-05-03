# Media Advisor

Analisi AI di video YouTube: estrae trascrizioni, identifica temi, claim e bias per canali monitorati. Vedi [ROADMAP.md](ROADMAP.md) per stato e piano modifiche.

## Setup

```bash
npm install
cp .env.example .env
# Modifica .env: TRANSCRIPT_API_KEY, OPENAI_API_KEY
# Opzionale Telegram: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, TELEGRAM_THREAD_ID
# Opzionale DB: MEDIA_ADVISOR_DATABASE_URL (default: ./data/media_advisor.sqlite, non in git)
```

## Database locale (SQLite) — store operativo unico

A runtime, **lettura e scrittura** passano solo da SQLite (`data/media_advisor.sqlite`, WAL): trascrizioni, digest giornaliero (`daily_reports`), analisi video, dati mercato, registro canali e liste video (pending, date, ecc.).

Cartelle JSON già presenti (`data/transcripts/`, `data/analysis/`, `mercato/`, file sotto `channels/`) possono restare su disco come **archivio**: l’app **non** le aggiorna nel flusso normale e **non** le cancella automaticamente. Per popolare il DB da quel materiale:

- **Migrazione una tantum**: `python -m media_advisor.cli db-migrate-from-json` (o `python -m media_advisor.tools.migrate_json_to_sqlite`).

- **Variabile**: `MEDIA_ADVISOR_DATABASE_URL` — se assente, il path è `<MEDIA_ADVISOR_ROOT>/data/media_advisor.sqlite`. Su OneDrive conviene spesso un path assoluto fuori dalla cartella sincronizzata.

- **Export opzionale**: `MEDIA_ADVISOR_EXPORT_REPORT_FILES` (default `true`) — se `true`, il digest scrive anche file in `reports/` oltre al DB.

- **Spostare il progetto su un altro PC**: clone + `.env` + **copia di `media_advisor.sqlite`** (processi fermi o backup coerente). Non contare sui JSON nel repo come fonte di verità dopo la migrazione.

## Pubblicazione Telegram (daily report)

Con Telegram configurato, ogni `POST /api/sync/daily-report` pubblica automaticamente il digest in chat/canale.
Se Telegram fallisce, il daily report resta completato: errore tracciato nello stato di sync (comportamento non bloccante).

### 1) Crea bot e recupera token

- Apri `@BotFather` su Telegram.
- Esegui `/newbot` e copia il token.
- Salva il token in `.env` come `TELEGRAM_BOT_TOKEN`.

### 2) Recupera `chat_id`

- Aggiungi il bot alla chat/canale target (e promuovilo admin se canale).
- Invia almeno un messaggio nella chat, oppure pubblica un post nel canale (o nel topic, se usi i forum topic).
- Leggi gli update:

```bash
curl "https://api.telegram.org/bot<TELEGRAM_BOT_TOKEN>/getUpdates"
```

- Usa il valore `message.chat.id` come `TELEGRAM_CHAT_ID`.
- Se pubblichi su topic/thread, usa anche `message.message_thread_id` come `TELEGRAM_THREAD_ID`.

Config minima in `.env`:

```bash
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...
# TELEGRAM_THREAD_ID=123456   # opzionale
```

### 3) Trigger automatico

- API: `POST /api/sync/daily-report`
- UI: bottone Daily Report in dashboard (`Rassegna`)
- Con variabili Telegram valide, il report viene inviato automaticamente a fine run.
- Senza variabili Telegram, il daily report viene comunque generato localmente (nessuna pubblicazione).
- In caso di errore Telegram, il run resta `done`; dettagli in `GET /api/sync/status`.

## Struttura progetto

```
media-advisor/
├── channels/           # Opzionale: seed / storico (registro + liste); runtime = SQLite
│   ├── channels.json   # Registro canali (versionato; può alimentare migrazione iniziale)
│   └── {id}.json       # URL video (storico / seed; spesso non in git)
├── data/
│   ├── media_advisor.sqlite   # Store operativo (WAL/SHM); non in git
│   ├── transcripts/    # Archivio JSON legacy (non scritto dalla pipeline)
│   └── analysis/       # Archivio JSON legacy (non scritto dalla pipeline)
├── web/                # Dashboard Vue.js; `public/analysis` generato da dump dal DB
├── mercato/            # Archivio JSON legacy mercato (non fonte runtime dopo migrazione)
└── scripts/            # Utility
```

**Backup:** copia `data/media_advisor.sqlite` (e `.env`). I path sopra “legacy” servono solo se non hai ancora migrato o per confronto manuale.

## Comandi

| Comando | Descrizione |
|---------|-------------|
| `npm run run-list` | Pipeline principale: scarica transcript, analizza video, analisi canale |
| `npm run run-list -- --channel=id` | Solo un canale |
| `npm run transcript <url>` | Transcript singolo -> `data/transcripts/_misc/` |
| `npm run transcript <url> --channel=id` | Transcript singolo -> `data/transcripts/{id}/` |
| `npm run add-punto-chiaro` | Aggiunge "Il punto chiaro" da @radiocrc2023 a Umberto Chiariello |
| `npm run migrate-transcripts` | Migra transcript flat → per-canale (una tantum) |
| `python -m media_advisor.cli db-migrate-from-json` | Importa da JSON su disco (transcript, digest, analysis, mercato, channels) nel SQLite locale |
| `python -m media_advisor.tools.dump_analysis_public` | Rigenera `web/public/analysis` dal DB (chiamato anche da `prepare-public`) |
| `python -m media_advisor.validate --sqlite` | Valida payload transcript nel DB |
| `npm run backfill-dates` | Recupera solo le date mancanti (TranscriptAPI/yt-dlp/Piped/Invidious) |
| `npm run backfill-dates -- --channel=id` | Solo un canale |
| `npm run auto-update` | Fetch nuovi video (regole) → merge → transcript + analisi (automatico) |
| `npm run auto-update -- --channel=id` | Solo un canale |
| `npm run dev` | Server + dashboard (Inbox funziona) |
| `npm run server:prod` | Uvicorn **senza** `--reload` (produzione); porta da env `PORT` (default `3002`) |
| `cd web && npm run build` | Build statica: esegue `prepare-public` (dump analisi da SQLite) poi `vite build` |

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

La dashboard:
- in **dev**: `prepare-public` popola `web/public/analysis` dal DB; Vite serve e proxy `/api` → `3002`.
- in **produzione**: `web` `npm run build` include lo stesso dump; i file finiscono in `web/dist/analysis/`. Il server FastAPI serve `web/dist` come statici.
- dati **mercato** via API `/api/mercato/*`.

Nota: `npm run dev` in root esegue `dev:kill` per liberare le porte `3001/3002/5173/5174`.

## Server Windows (produzione)

1. **Path e env**: imposta `MEDIA_ADVISOR_ROOT` al path assoluto del repo sul server; opzionale `MEDIA_ADVISOR_DATABASE_URL` (es. SQLite fuori da OneDrive). Installa dipendenze: `python -m pip install -e ".[dev]"`, `npm install`, `cd web && npm install && npm run build`.
2. **Avvio**: `npm run server:prod` (un solo processo Uvicorn; **non** usare più worker su uno stesso file SQLite). Variabile **`PORT`** (opzionale) per la porta, default `3002`. Health check: `GET http://127.0.0.1:3002/api/health`. Per verificare anche SQLite: `GET .../api/health/ready` oppure `GET .../api/health?ready=1` (503 se il DB non risponde).
3. **CORS**: di default l’API accetta qualsiasi origin (`*`). Se esponi il servizio su LAN/Internet, imposta `MEDIA_ADVISOR_CORS_ORIGINS` con una lista separata da virgole (es. `http://localhost:5173,https://miodominio.example`). Valore vuoto = stesso comportamento di `*`. In dev con Vite su `5173` e API su `3002`, includi `http://localhost:5173` se servono richieste cross-origin dal browser. Combinare con firewall/VPN o reverse proxy con allowlist IP dove possibile.
4. **Protezione job costosi**: se imposti `MEDIA_ADVISOR_SYNC_SECRET` in `.env`, le richieste `POST /api/sync`, `/api/sync/recent`, `/api/sync/daily-report` e `POST /api/fetch-now` richiedono header `X-Media-Advisor-Sync: <stesso valore>`. Se la variabile è vuota, il comportamento resta come in sviluppo locale (nessun header). Le altre `POST` mutanti (Inbox, mercato, ecc.) restano senza Bearer dedicato: in esposizione rete conviene affidarle a reverse proxy, rete privata o eventuale token applicativo futuro lato API+frontend.
5. **Sempre acceso**: [NSSM](https://nssm.cc/) per registrare come servizio Windows (es. applicazione `node`, argomenti `scripts/run-uvicorn-prod.mjs`, directory di avvio = root del repo) oppure **Utilità di pianificazione** all’avvio — NSSM è preferibile per ripartenza automatica.
6. **Automazione sync / daily report**: task giornaliero che chiama ad es. `curl -X POST http://127.0.0.1:3002/api/sync/daily-report -H "X-Media-Advisor-Sync: ..."` se il secret è attivo. Evita due task sovrapposti (l’API risponde `409` se un sync è già in esecuzione).
7. **Firewall**: apri in ingresso solo la porta scelta (es. `3002`) e solo LAN/VPN se non serve esporre su Internet.
8. **Backup SQLite**: con il servizio fermo (o copia coerente), copia `media_advisor.sqlite` e, se presenti, `-wal` / `-shm` dalla stessa cartella; oppure script schedulato con backup su percorso dedicato.

## Piano Creator Advisor (quality upgrade)

Per la pianificazione completa delle migliorie quality/advisor:

- `docs/advisor-quality-roadmap.md` - roadmap, architettura target, milestone, rischi.
- `docs/advisor-quality-task-breakdown.md` - task operativi per sprint con DoD e verifiche.

## API

- **TranscriptAPI.com** – trascrizioni YouTube (credit-based)
- **OpenAI** – analisi tramite GPT

## Licenza

MIT
