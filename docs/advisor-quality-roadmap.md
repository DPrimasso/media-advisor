# Advisor Quality Improvement - Roadmap di implementazione completa

Stato: `planned`  
Versione: `v1`  
Data: `2026-02-25`

## 1) Obiettivo prodotto

Trasformare Media Advisor da "riassunto + topic + claim" a **Creator Advisor** con:

- score trasparenti e spiegabili;
- evidenza verificabile (quote + timestamp + supporto claim);
- misure di coerenza nel tempo;
- accountability sulle predizioni;
- pagina web dedicata con drill-down.

Output atteso: una pagina `/advisor/:id` che permetta di valutare in modo rapido e verificabile cosa dice un content creator e quanto e affidabile nel tempo.

## 2) Scope e non-scope

### In scope

- Estensione schema analisi con metriche quality/advisor.
- Pipeline quality controls (validator claim↔quote, score aggregati).
- Nuovi artefatti `analysis/<channel>/_advisor.json`.
- Nuova UI advisor con scorecard, timeline coerenza, bias panel, prediction panel.
- Benchmark quality su dataset eval esistente.

### Non-scope (fase iniziale)

- Verita fattuale assoluta su eventi esterni in tempo reale.
- Fact-checking automatico web-wide senza fonti curate.
- Ranking cross-platform multi-social (si resta su YouTube).

## 3) Metriche prodotto (KPI)

KPI principali da mostrare in UI e salvare nel JSON advisor:

1. `evidence_coverage` (0-100)
2. `evidence_fidelity` (0-100)
3. `specificity_score` (0-100)
4. `coherence_score` (0-100)
5. `prediction_accountability` (0-100)
6. `bias_concentration` (0-100, alto = piu sbilanciato)
7. `absolutism_rate` (0-100)
8. `topic_diversity` (0-100, alto = piu vario)
9. `advisor_score` (0-100, composito pesato)

Formula iniziale proposta:

`advisor_score = 0.20*evidence_coverage + 0.20*evidence_fidelity + 0.20*coherence_score + 0.15*specificity_score + 0.10*prediction_accountability + 0.10*(100-bias_concentration) + 0.05*(100-absolutism_rate)`

## 4) Target architecture

Pipeline target:

1. Transcript fetch
2. Segmentazione
3. Extractor claim/theme
4. Specificity filter
5. **Validator claim support**
6. Aggregator video
7. Channel profile + inconsistenze
8. **Advisor scoring aggregation**
9. Scrittura `_advisor.json`
10. Frontend `/advisor/:id`

File principali coinvolti:

- `src/pipeline/extractor.ts`
- `src/pipeline/validator.ts`
- `src/pipeline/video-aggregator.ts`
- `src/pipeline/inconsistency-detector.ts`
- `src/run-from-list.ts`
- `web/src/router/index.js`
- `web/src/composables/useChannelsData.js`
- `web/src/views/AdvisorView.vue` (nuovo)

## 5) Work breakdown (epic -> attivita)

## Epic A - Data model e contratti

### A1. Definire schema advisor
- Creare tipi TS per KPI e breakdown.
- Aggiungere formato output `_advisor.json`.
- Definire retrocompatibilita con output corrente.

### A2. Normalizzare scale
- `intensity` in bucket discreti 0..3.
- Clamp e rounding consistente per tutti i punteggi.

### A3. Versioning output
- Campo `schema_version` in JSON advisor.
- Strategia migrazione per file precedenti.

## Epic B - Quality pipeline

### B1. Attivare validator in pipeline principale
- Integrazione `validateClaims` in `analyze-v2` e run batch.
- Tracciare claim scartati/riparati.

### B2. Migliorare inconsistency signal
- Separare eventi informativi `NOT` da contraddizioni effettive.
- Usare solo `HARD/SOFT/DRIFT` per `coherence_score`.

### B3. KPI calcolati lato backend
- Modulo scoring unico con formule centralizzate.
- Breakdown per entity/topic/time-window.

## Epic C - Prediction accountability

### C1. Registry predizioni
- Estrarre claim `PREDICTION` e salvarli con status `open`.

### C2. Risoluzione predizioni
- Regole di matching ex-post su nuovi transcript/metadata.
- Aggiornare status (`hit`, `miss`, `unresolved`).

### C3. KPI predizione
- `prediction_accountability` su finestra temporale configurabile.

## Epic D - Web Advisor UI

### D1. Nuova route e view
- Route `/advisor/:id`.
- Advisor home card nel canale.

### D2. Scorecard spiegabile
- Punteggio totale + 8 mini metriche.
- Tooltip con formula e contributi.

### D3. Drill-down
- Tab "Coerenza", "Bias", "Predizioni", "Evidence gaps".
- Link diretti a YouTube timestamp.

## Epic E - QA, eval e rollout

### E1. Eval harness quality
- Script valutazione su `eval/` con report KPI before/after.

### E2. Test regressione
- Build TS root e web.
- Smoke test pipeline su 1 canale.

### E3. Rollout progressivo
- Flag feature advisor.
- Rollout per canale pilota -> tutti i canali.

## 6) Sequenza di delivery consigliata

### Milestone M0 - Foundation (1-2 giorni)
- A1, A2, B1.
- DoD: pipeline genera claim validati e metriche base per video.

### Milestone M1 - Channel Advisor Backend (2-3 giorni)
- A3, B2, B3.
- DoD: `_advisor.json` disponibile per ogni canale.

### Milestone M2 - Advisor UI v1 (2 giorni)
- D1, D2.
- DoD: pagina advisor con scorecard e spiegazioni base.

### Milestone M3 - Advisor UI v2 + Predizioni (3-4 giorni)
- C1, C2, C3, D3.
- DoD: pannello predizioni e timeline coerenza complete.

### Milestone M4 - Quality Gate e rollout (1-2 giorni)
- E1, E2, E3.
- DoD: report benchmark allegato + rilascio su tutti i canali.

## 7) Definition of Done globale

Una milestone e completata solo se:

- output JSON documentato e versionato;
- build root + web passano;
- smoke test pipeline reale eseguito su almeno 1 canale;
- UI manual test con evidence link funzionanti;
- note di rilascio aggiornate.

## 8) Rischi e mitigazioni

1. **Rumore LLM nei claim**
   - Mitigazione: validator obbligatorio + soglia minima fidelity.
2. **Score percepiti come black-box**
   - Mitigazione: formula visibile, breakdown, esempi claim.
3. **Falsi positivi su contraddizioni**
   - Mitigazione: distinzione HARD/SOFT/DRIFT, NOT solo informativo.
4. **Predizioni difficili da risolvere**
   - Mitigazione: status `unresolved` esplicito, nessuna sovrainferenza.

## 9) Piano di documentazione

Documenti da mantenere allineati durante l'implementazione:

- `docs/advisor-quality-roadmap.md` (questo file)
- `docs/advisor-quality-task-breakdown.md` (task operativi)
- `README.md` (sezione "Creator Advisor")

## 10) Criterio di successo finale

Il progetto e considerato riuscito quando un utente puo:

1. aprire un creator;
2. vedere score e motivazioni;
3. cliccare evidenze puntuali nei video;
4. capire se il creator e coerente o cambia posizione nel tempo;
5. verificare lo storico predizioni in modo trasparente.
