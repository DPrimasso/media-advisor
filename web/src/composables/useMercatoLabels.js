export const OUTCOME_LABELS = {
  non_verificata: 'Non verificata',
  confermata: 'Confermata',
  parziale: 'Parziale',
  smentita: 'Smentita',
  non_conclusa: 'Non conclusa',
}

export const OUTCOME_SOURCE_LABELS = {
  manual: 'manuale',
  transfermarkt: 'TM',
  auto: 'auto',
}

export const CONFIDENCE_LABELS = {
  rumor: 'Voce',
  likely: 'Probabile',
  confirmed: 'Confermata',
  denied: 'Smentita',
}

export const OUTCOME_CLASSES = {
  non_verificata: 'outcome-pending',
  confermata: 'outcome-true',
  parziale: 'outcome-partial',
  smentita: 'outcome-false',
  non_conclusa: 'outcome-stalled',
}

export const CONFIDENCE_CLASSES = {
  rumor: 'conf-rumor',
  likely: 'conf-likely',
  confirmed: 'conf-confirmed',
  denied: 'conf-denied',
}

/* New chip-based classes for the redesign */
export const CONFIDENCE_CHIP = {
  rumor:     'chip--muted',
  likely:    'chip--gold',
  confirmed: 'chip--green',
  denied:    'chip--red',
}

export const CONFIDENCE_DOT = {
  rumor:     'dot-muted',
  likely:    'dot-gold',
  confirmed: 'dot-green',
  denied:    'dot-red',
}

export const OUTCOME_CHIP = {
  non_verificata: 'chip--muted',
  confermata:     'chip--green',
  parziale:       'chip--amber',
  smentita:       'chip--red',
  non_conclusa:   'chip--amber',
}

export const OUTCOME_DOT = {
  non_verificata: 'dot-muted',
  confermata:     'dot-green',
  parziale:       'dot-amber',
  smentita:       'dot-red',
  non_conclusa:   'dot-amber',
}
