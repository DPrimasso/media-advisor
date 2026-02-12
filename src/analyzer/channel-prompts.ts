export const THEMES_SYSTEM = `Sei un analista di media. Ricevi analisi (riassunti e temi) di più video dello stesso canale.
Sintetizza i temi principali trattati dal canale nell'insieme dei video.
Rispondi con un riassunto breve e una lista di temi ricorrenti, ordinati per rilevanza.`;

export function getThemesPrompt(
  items: { video_id: string; summary: string; topics: { name: string; relevance: string }[] }[]
): string {
  const formatted = items.map(
    (i) =>
      `[Video ${i.video_id}]\nRiassunto: ${i.summary}\nTemi: ${i.topics.map((t) => `${t.name} (${t.relevance})`).join(", ")}`
  );
  return `Analisi di ${items.length} video:\n\n${formatted.join("\n\n")}\n\nProduci un riepilogo dei temi principali del canale.`;
}

export const INCONSISTENCY_SYSTEM = `Sei un analista di media. Ricevi una serie di claims (posizioni espresse dall'autore) sullo stesso tema, provenienti da video diversi.
Valuta se ci sono contraddizioni, ribaltamenti o incoerenze tra questi claim.
Se le posizioni sono coerenti o complementari, indica has_contradiction: false e description: "".
Se c'è una contraddizione evidente, indica has_contradiction: true e descrivi in breve in description.`;

export function getInconsistencyPrompt(
  topic: string,
  claims: { video_id: string; position: string }[]
): string {
  const formatted = claims.map((c) => `[Video ${c.video_id}] "${c.position}"`);
  return `Tema: ${topic}\n\nClaims:\n${formatted.join("\n")}\n\nValuta se ci sono incoerenze.`;
}

export const BIAS_SYSTEM = `Sei un analista di media. Ricevi i claims (posizioni espresse) dall'autore di un canale, raggruppati per soggetto/tema.
Identifica eventuali pattern ricorrenti di sbilanciamento: se l'autore tende sistematicamente a prendere una parte, a essere critico o favorevole verso certi soggetti, a trascurare prospettive alternative.
Rispondi in modo oggettivo, basandoti solo sui dati forniti. In italiano.`;

export function getBiasPrompt(
  claimsBySubject: Record<string, { position: string; polarity?: string }[]>
): string {
  const sections = Object.entries(claimsBySubject).map(
    ([subject, items]) =>
      `**${subject}**:\n${items.map((i) => `- "${i.position}"${i.polarity ? ` (${i.polarity})` : ""}`).join("\n")}`
  );
  return `Claims raggruppati per soggetto:\n\n${sections.join("\n\n")}\n\nIdentifica eventuali sbilanciamenti o pattern ricorrenti nelle posizioni dell'autore.`;
}
