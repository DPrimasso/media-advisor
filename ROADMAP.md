# Media Advisor — ROADMAP

## Stato attuale (da ultimi commit main)

### Fatto ✅

#### Pipeline principale (commit 72ec954)
- **Video discovery**: `fetch-new-videos.ts` con fetch rules (transcript_api, rss, playlist)
- **Channel resolver**: `channel-resolver.ts` per ottenere channel_id da URL YouTube
- **Inbox flow**: pending.json → UI InboxView → /api/confirm → merge in video_list
- **API server** (`server/api.ts`): GET /api/pending, POST /api/confirm, POST /api/fetch-now
- **run-from-list**: `--from-pending` merge pending nelle liste canali, poi pipeline
- **auto-update**: `npm run auto-update` — fetch → merge → pipeline (nessun passo manuale)
- **Dashboard Vue**: HomeView, ChannelView, InboxView, TrendView, SquadreView, TrendMacroView
- **Vite proxy**: `/api` → localhost:3001

#### Pipeline v2 (commit 8063890 + integrazione)
- **analyze-v2.ts**: transcript → clean → segment → extract → aggregate → filter
- **runFromList** usa analyzeVideoV2 per default (`--no-v2` per baseline)
- **Output**: analysis/\<channel_id\>/\<video_id\>.json con claims + evidence_quotes

#### Eval framework
- **eval/run-baseline.ts**: baseline (vecchia pipeline)
- **eval/run-eval.ts**: confronta baseline vs v2 su human_gold
- **eval/videos_sample.json**: sample per azzurro-fluido, umberto-chiariello, open-var

#### Canali configurati
| id | fetch_rule | video_list |
|----|------------|------------|
| azzurro-fluido | transcript_api, last_n:15 | azzurro-fluido.json |
| umberto-chiariello | transcript_api, title_contains "Il punto chiaro" | umberto-chiariello.json |
| neschio | transcript_api, last_n:50 | neschio.json |

---

### Dove si è interrotto / gap (aggiornato)

1. **open-var** — saltato per ora. Eval lo usa; pipeline principale no.

2. **Dev workflow** — ✅ fatto: `npm run dev` avvia server + web con concurrently.

3. **prepare-public** — eseguito da run-list alla fine; web dev fa `prepare-public && vite` all'avvio.

---

## Piano modifiche

### 1. Open-var in channels.json (sospeso)
Aggiungere open-var a channels.json con fetch_rule. Serve l’URL del canale YouTube di Open VAR per configurarlo.

```json
{
  "id": "open-var",
  "name": "Open VAR",
  "order": 4,
  "video_list": "open-var.json",
  "fetch_rule": {
    "type": "transcript_api",
    "channel_url": "https://www.youtube.com/...",
    "last_n": 20
  }
}
```

### 2. Script dev unificato — ✅ fatto

### 3. README — ✅ aggiornato
- Per usare Inbox: `npm run dev` (avvia server + dashboard)
- In alternativa: due terminali (`npm run server` + `cd web && npm run dev`)

### 3. Optional: evalsample da channels
`eval/videos_sample.json` è mantenuto a mano. Opzionale: script che lo genera da channels + analysis esistenti per refresh periodico.

### 4. Optional: feed RSS per canali senza TranscriptAPI
Alcuni canali possono fallire con TranscriptAPI; c’è già fallback a RSS in `fetch-new-videos`. Verificare che i canali abbiano channel_url valido per il fallback.

---

## Comandi utili

| Comando | Descrizione |
|---------|-------------|
| `npm run run-list` | Pipeline completa (transcript + analisi v2) |
| `npm run run-list -- --from-pending` | Merge pending → pipeline |
| `npm run auto-update` | Fetch → merge → pipeline (tutto automatico) |
| `npm run run-list -- --channel=open-var` | Solo un canale |
| `npm run server` | API server (3001) |
| `npm run dev` | Server + dashboard |
| `npm run eval:baseline` | Eval baseline |
| `npm run eval:v2` | Pipeline v2 su videos_sample → eval/out_v2 |
| `npm run eval:run -- --system=v2` | Metriche eval |
