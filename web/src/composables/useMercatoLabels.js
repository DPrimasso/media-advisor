export const OUTCOME_LABELS = {
  non_verificata: 'Non verificata',
  confermata: 'Confermata',
  parziale: 'Parziale',
  smentita: 'Smentita',
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
}

export const CONFIDENCE_CLASSES = {
  rumor: 'conf-rumor',
  likely: 'conf-likely',
  confirmed: 'conf-confirmed',
  denied: 'conf-denied',
}
