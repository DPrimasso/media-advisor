# Advisor Scoring - metodologia e limiti

Stato: `active`  
Versione schema: `1.0.0`

## 1) Come viene calcolato il punteggio

Il punteggio composito `advisor_score` e calcolato cosi:

`0.20*evidence_coverage + 0.20*evidence_fidelity + 0.20*coherence_score + 0.15*specificity_score + 0.10*prediction_accountability + 0.10*(100-bias_concentration) + 0.05*(100-absolutism_rate)`

Scala 0-100.

## 2) Significato delle metriche

- `evidence_coverage`: percentuale claim con quote/timestamp validi.
- `evidence_fidelity`: claim supportati o riparati dal validator claim↔quote.
- `specificity_score`: quanto i claim sono concreti (poco vaghi).
- `coherence_score`: penalita su inconsistenze (`HARD` > `SOFT` > `DRIFT`).
- `prediction_accountability`: accuratezza sulle prediction risolte (`hit/miss`).
- `bias_concentration`: concentrazione sbilanciata di stance su entita.
- `absolutism_rate`: frequenza lessico assolutista (es. "sempre/mai").
- `topic_diversity`: varieta topic (entropia normalizzata).

## 3) Prediction tracking

Ogni claim `claim_type=PREDICTION` viene tracciato in:

- `breakdown.predictions.items[]` con `status` (`open|hit|miss`), `confidence`, e metadati di risoluzione.

Regola attuale:

1. Cerca claim futuri sulla stessa `entity + dimension`.
2. Stima majority stance direzionale (`POS` vs `NEG`).
3. Se majority coerente con prediction => `hit`, altrimenti `miss`.
4. Se non ci sono evidenze direzionali sufficienti => `open`.

## 4) Feature flags di rollout

Supportate in pipeline:

- `ADVISOR_ENABLED=true|false`
- `ADVISOR_PREDICTION_ENABLED=true|false`
- `ADVISOR_MIN_FIDELITY=0..100`

Override CLI disponibili:

- `npm run run-list -- --advisor=off`
- `npm run run-list -- --advisor-predictions=off`
- `npm run run-list -- --advisor-min-fidelity=70`

## 5) Benchmark before/after

Script:

- `npm run eval:advisor-quality`
- `npm run eval:advisor-gate -- --channel=<id> --min-fidelity=70`

Con baseline:

- `npm run eval:advisor-quality -- --baseline eval/advisor-quality-baseline.json`
- `npm run eval:advisor-quality -- --save-baseline eval/advisor-quality-baseline.json`

Output default:

- `eval/advisor-quality-report.json`

Gate script:

- valida presenza `_advisor.json`
- valida soglie minime (`--min-fidelity`, `--min-advisor-score`)
- opzionale `--require-predictions-resolved`

## 6) Limiti (importanti)

1. Non e fact-checking esterno: valuta coerenza/evidenza interna ai transcript.
2. Prediction resolution e euristica: puo restare `open` anche con contesto ambiguo.
3. I punteggi dipendono dalla qualita transcript e dal recall dei claim estratti.
4. `NOT` nelle inconsistenze e informativo, non contraddizione logica forte.
