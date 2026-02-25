# Advisor Quality - Task breakdown operativo

Stato: `planned`  
Ultimo aggiornamento: `2026-02-25`

Questo backlog e pronto per esecuzione iterativa.  
Ogni task include: impatto, file, dipendenze, DoD e verifica.

## Convenzioni

- Priorita: `P0` critica, `P1` alta, `P2` media.
- Stima: `S` (<=0.5d), `M` (1d), `L` (2-3d).
- Stato: `todo`, `doing`, `done`, `blocked`.

## Sprint 1 - Core quality backend

| ID | Priorita | Stima | Stato | Task | File principali | Dipendenze |
|---|---|---|---|---|---|---|
| AQ-001 | P0 | M | todo | Introdurre schema `AdvisorScore` + tipi TS | `src/schema/claims.ts` (o nuovo `src/schema/advisor.ts`) | - |
| AQ-002 | P0 | M | todo | Agganciare `validateClaims` in `analyze-v2` | `src/analyze-v2.ts`, `src/pipeline/validator.ts` | AQ-001 |
| AQ-003 | P0 | S | todo | Agganciare validator in `run-v2` batch | `src/pipeline/run-v2.ts` | AQ-002 |
| AQ-004 | P0 | S | todo | Stabilizzare `intensity` a bucket 0..3 | `src/pipeline/extractor.ts` | AQ-001 |
| AQ-005 | P0 | M | todo | Creare modulo `advisor-scoring` con KPI base | nuovo `src/pipeline/advisor-scoring.ts` | AQ-001..004 |
| AQ-006 | P0 | M | todo | Persistenza `analysis/<channel>/_advisor.json` | `src/run-from-list.ts`, `web/scripts/prepare-public.js` | AQ-005 |

### DoD Sprint 1

- `_advisor.json` generato per almeno 1 canale.
- Include: `advisor_score`, metriche componenti, `schema_version`.
- Nessun crash su canali con pochi claim.

### Verifica Sprint 1

- `npm run build`
- `npm run run-list -- --channel=<id> --skip-channel-analysis`
- controllo manuale file `analysis/<id>/_advisor.json`

---

## Sprint 2 - Coerenza e bias robusti

| ID | Priorita | Stima | Stato | Task | File principali | Dipendenze |
|---|---|---|---|---|---|---|
| AQ-007 | P0 | M | todo | Pulire inconsistenze: separare `NOT` da score | `src/pipeline/inconsistency-detector.ts` | AQ-005 |
| AQ-008 | P1 | M | todo | Calcolo `coherence_score` pesato HARD/SOFT/DRIFT | `src/pipeline/advisor-scoring.ts` | AQ-007 |
| AQ-009 | P1 | M | todo | `bias_concentration` e `absolutism_rate` affidabili | `src/pipeline/channel-profiler.ts`, `advisor-scoring.ts` | AQ-005 |
| AQ-010 | P1 | S | todo | Breakdown per entity/topic in output advisor | `advisor-scoring.ts` | AQ-008 AQ-009 |

### DoD Sprint 2

- Contraddizioni reali separate da mismatch informativi.
- Score coerenza e bias spiegabili con contributi.

### Verifica Sprint 2

- `npm run build`
- smoke pipeline su canale con storico >10 video
- confronto before/after su sample `eval/out_v2/*/_inconsistencies.json`

---

## Sprint 3 - Prediction accountability

| ID | Priorita | Stima | Stato | Task | File principali | Dipendenze |
|---|---|---|---|---|---|---|
| AQ-011 | P1 | M | todo | Registry predizioni (`open/hit/miss/unresolved`) | nuovo `src/pipeline/prediction-registry.ts` | AQ-005 |
| AQ-012 | P1 | L | todo | Resolver predizioni ex-post (matching semplice) | `prediction-registry.ts`, `run-from-list.ts` | AQ-011 |
| AQ-013 | P1 | M | todo | KPI prediction accountability + explainers | `advisor-scoring.ts` | AQ-012 |

### DoD Sprint 3

- Predizioni tracciate per canale.
- KPI predizioni visibile in `_advisor.json`.

### Verifica Sprint 3

- `npm run build`
- run incrementale su stesso canale in due passaggi temporali
- verifica transizione status predizioni

---

## Sprint 4 - Web Advisor UI

| ID | Priorita | Stima | Stato | Task | File principali | Dipendenze |
|---|---|---|---|---|---|---|
| AQ-014 | P0 | S | todo | Nuova route `/advisor/:id` | `web/src/router/index.js` | AQ-006 |
| AQ-015 | P0 | M | todo | Caricamento advisor data nel data layer | `web/src/composables/useChannelsData.js` | AQ-006 |
| AQ-016 | P0 | L | todo | `AdvisorView.vue` con scorecard e formula | nuovo `web/src/views/AdvisorView.vue` | AQ-014 AQ-015 |
| AQ-017 | P1 | M | todo | Tab coerenza/bias/evidence gaps | `AdvisorView.vue` | AQ-016 |
| AQ-018 | P1 | M | todo | Pannello predizioni e stato verifica | `AdvisorView.vue` | AQ-013 AQ-016 |
| AQ-019 | P1 | S | todo | Link dalla pagina canale a Advisor | `web/src/views/ChannelView.vue`, `web/src/App.vue` | AQ-016 |

### DoD Sprint 4

- Pagina advisor funzionante su almeno 1 canale.
- Score, breakdown e link evidenze navigabili.

### Verifica Sprint 4

- `cd web && npm run build`
- test manuale browser: apertura `/advisor/<id>`, click timestamp, tab data.

---

## Sprint 5 - QA, benchmark e rollout

| ID | Priorita | Stima | Stato | Task | File principali | Dipendenze |
|---|---|---|---|---|---|---|
| AQ-020 | P0 | M | todo | Script benchmark quality before/after | nuovo `scripts/eval-advisor-quality.ts` | AQ-018 |
| AQ-021 | P1 | S | todo | Documento metodo scoring + limiti | `README.md`, `docs/` | AQ-020 |
| AQ-022 | P1 | S | todo | Feature flag advisor e rollout graduale | `src/run-from-list.ts`, config env | AQ-020 |
| AQ-023 | P1 | S | todo | Playbook regressioni e fallback | `docs/advisor-quality-rollout.md` (nuovo) | AQ-022 |

### DoD Sprint 5

- Report benchmark allegato.
- Rollout pilot -> full con checklist completata.

### Verifica Sprint 5

- `npm run build`
- `cd web && npm run build`
- smoke end-to-end su canale pilota

---

## Dipendenze critiche (grafo breve)

`AQ-001 -> AQ-002 -> AQ-003 -> AQ-005 -> AQ-006 -> AQ-014/015/016`  
`AQ-007 -> AQ-008 -> AQ-010`  
`AQ-011 -> AQ-012 -> AQ-013 -> AQ-018`

## Checklist rilascio per milestone

### Backend release checklist

- [ ] JSON advisor valido e versionato.
- [ ] fallback su canali senza predizioni.
- [ ] build TS green.
- [ ] output copiato in `web/public/analysis`.

### Frontend release checklist

- [ ] route advisor raggiungibile da UI.
- [ ] score card responsive (desktop/mobile).
- [ ] timestamp links aprono YouTube corretto.
- [ ] stato vuoto gestito (nessun crash).

## Definizione "bloccante"

Task in stato `blocked` se:

- API key mancanti per test reali;
- output storico incompatibile senza migration rule;
- tempi pipeline > limite operativo (deve restare usabile per run giornaliero).

## Piano di tracking consigliato

Se vuoi gestirlo stile issue board:

- Epic label: `advisor-quality`
- Labels task: `backend`, `frontend`, `eval`, `pipeline`, `scoring`
- Milestones: `M0`, `M1`, `M2`, `M3`, `M4`

