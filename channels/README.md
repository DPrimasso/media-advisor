# Canali

Aggiungi qui i canali YouTube da analizzare.

**Runtime:** registro canali, liste URL, pending e date video vivono in **SQLite** (`data/media_advisor.sqlite`). All’avvio, se il DB è vuoto per quei dati, l’app può **importare una tantum** dai file qui sotto (seed). **Backup dello stato operativo** = copia del file `.sqlite` (non solo questi JSON).

**Nota repo:** molti `{id}.json`, `pending.json`, ecc. **non sono versionati** in git. Dopo un clone, ripristina il DB da backup oppure esegui `db-migrate-from-json` se hai ancora i JSON. `channels.json` in repo è soprattutto riferimento/seed.

## Struttura

- `channels.json` — elenco canali (id, nome, ordine, lista video)
- `{channel-id}.json` — array di URL video per quel canale

## Aggiungere un canale

1. Crea `channels/{id}.json` con l’array di URL:
   ```json
   [
     "https://www.youtube.com/watch?v=VIDEO_ID_1",
     "https://www.youtube.com/watch?v=VIDEO_ID_2"
   ]
   ```

2. Registra il canale in `channels.json`:
   ```json
   {
     "channels": [
       { "id": "azzurro-fluido", "name": "Azzurro Fluido", "order": 1, "video_list": "azzurro-fluido.json" },
       { "id": "nuovo-canal", "name": "Nome Canale", "order": 2, "video_list": "nuovo-canal.json" }
     ]
   }
   ```

3. Esegui `npm run run-list` per scaricare trascrizioni e analisi.

L’`order` definisce l’ordine di visualizzazione nella dashboard.

## Dove finiscono i dati (dopo migrazione)

- **Transcript / analisi / mercato / canali**: tabelle in `data/media_advisor.sqlite` (vedi README principale).
- Cartelle `data/transcripts/`, `data/analysis/`, `mercato/` possono contenere solo **copie storiche** non aggiornate dall’app.
