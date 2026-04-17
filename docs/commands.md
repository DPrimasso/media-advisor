# Comandi — Media Advisor

_Aggiornato: aprile 2026_

---

## Dev

```bash
npm run dev          # Kill porte 3001/5173 + avvia uvicorn (3001) + Vite (5173) in parallelo
npm run server       # Solo FastAPI uvicorn su porta 3001
npm run dev:web      # Solo Vite (web/) su porta 5173
npm run dev:kill     # Kill porte 3001, 5173, 5174
npm run prepare-public  # Copia analysis/ → web/public/analysis/ (per build statica)
```

---

## CLI Python (`media-advisor`)

Installazione: `python -m pip install -e ".[dev]"` (da root del progetto)

### Pipeline principale

```bash
# Analizza un singolo video (transcript deve già esistere)
media-advisor analyze <video_id> --channel <channel_id>
media-advisor analyze <video_id> --channel <channel_id> --force   # ri-analizza anche se già analizzato

# Scarica transcript di un singolo video
media-advisor transcript <video_id> --channel <channel_id>

# Batch: scarica transcript + analizza tutti i video in una video list
media-advisor run-list
media-advisor run-list --channel <channel_id>     # solo un canale
media-advisor run-list --force-analyze            # ri-analizza anche già analizzati
media-advisor run-list --force-transcript         # ri-scarica transcript

# Fetch nuovi video dai canali → pending.json
media-advisor fetch-now
media-advisor fetch-now --channel <channel_id>   # solo un canale

# Approva un video da pending.json (aggiunge alla video list del canale)
media-advisor confirm <video_id> --channel <channel_id>

# Tutto in automatico: fetch → merge pending → run-list
media-advisor auto-update
```

### Mercato — estrazione tip

```bash
# Analizza un singolo video per tip mercato (transcript già scaricato)
media-advisor mercato-analyze <video_id> --channel <channel_id>

# Scansiona tutti i transcript già scaricati con titolo mercato e analizza quelli nuovi
media-advisor mercato-scan
media-advisor mercato-scan --channel <channel_id>
media-advisor mercato-scan --force   # ri-analizza anche già analizzati

# Ricostruisce mercato/index.json da mercato/tips/** (dopo modifiche manuali)
media-advisor mercato-rebuild-index
```

### Mercato — gestione trasferimenti e outcome

```bash
# Marca manualmente l'esito di una tip
media-advisor mercato-outcome <tip_id> --outcome confermata|smentita|parziale|non_verificata

# Aggiunge un trasferimento ufficiale al DB (inserimento manuale)
media-advisor mercato-add-transfer --player <nome> --from <club> --to <club> --date <YYYY-MM-DD>

# Scarica i trasferimenti di un giocatore da Transfermarkt
media-advisor mercato-fetch-transfers <player_name>

# Importa trasferimenti stagione da Transfermarkt per tutti i giocatori nelle tip
media-advisor mercato-import-season --season <YYYY>

# Verifica tutte le tip non_verificata contro il DB trasferimenti
media-advisor mercato-verify

# Stampa report veridicità per canale
media-advisor mercato-report
```

---

## Note

- Su Windows usare sempre `python -m pip install` (non `pip` standalone)
- Il comando `media-advisor` è disponibile solo dopo `python -m pip install -e ".[dev]"`
- In alternativa: `python -m media_advisor.cli <comando> [args]`
- `--force` e `--force-analyze` sono equivalenti per `run-list`
- `run-list` salta automaticamente i video già analizzati (vedi `analysis/<channel>/<video>.json`)
- `mercato-scan` salta automaticamente i video già analizzati per mercato (vedi `mercato/tips/`)
