# Canali

Aggiungi qui i canali YouTube da analizzare.

**Nota repo:** i file `{id}.json` (liste URL) e `pending.json` **non sono versionati** in git (vedi `.gitignore`). Restano solo sul tuo disco; dopo un clone vanno ricreati o copiati da backup. In repo c’è solo `channels.json` come registro canali.

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

## Struttura dati

- **Transcript**: `transcripts/{channel_id}/{video_id}.json`
- **Analisi**: `analysis/{channel_id}/{video_id}.json`
