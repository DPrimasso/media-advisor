# Advisor Quality - Rollout e governance operativa

Stato: `planned`  
Data: `2026-02-25`

## 1) Strategia rollout

Rollout graduale in 3 step:

1. **Pilot**: 1 canale (`--channel=<id>`) per 3 run consecutivi.
2. **Limited**: top 3 canali per volume.
3. **Full**: tutti i canali configurati.

Ogni step passa al successivo solo con quality gate verdi.

## 2) Quality gates

Gate minimi per promozione stage:

- Build root TS: pass
- Build web: pass
- `_advisor.json` generato e parsabile
- `evidence_fidelity >= 70` sul pilot
- nessun crash UI advisor in smoke test manuale

## 3) Fallback policy

Se fallisce un gate:

- mantenere output legacy (`_channel.json`, video analysis) attivo;
- nascondere route advisor dietro feature flag;
- loggare run failure con causa e canale;
- aprire task correttivo prima di rieseguire il rollout.

## 4) Feature flags suggerite

Variabili env:

- `ADVISOR_ENABLED=true|false`
- `ADVISOR_PREDICTION_ENABLED=true|false`
- `ADVISOR_MIN_FIDELITY=<number>`

Policy:

- in pilot: advisor abilitato solo per canali whitelist.
- in full: advisor default on, prediction panel opzionale.

## 5) Runbook operativo

## Pre-run

1. verificare chiavi API.
2. aggiornare branch e dipendenze.
3. selezionare target canale/stage.

## Run

1. `npm run run-list -- --channel=<id>`
2. `npm run prepare-public`
3. `cd web && npm run build`

## Post-run

1. validare JSON advisor.
2. aprire UI e testare percorso `/advisor/<id>`.
3. archiviare risultati benchmark.

## 6) Incident response (light)

Se compaiono score anomali:

1. isolare canale impattato.
2. disabilitare advisor solo su canale (se configurato).
3. rieseguire pipeline con log verbose.
4. confrontare output validator prima/dopo.

## 7) Audit trail minimo

Per ogni run advisor salvare:

- timestamp run
- commit hash
- canali processati
- KPI medi stage
- errori riscontrati

Consigliato file append-only: `analysis/_advisor_run_log.jsonl`.

