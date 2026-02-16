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

Distingui tra:
1. CONTRADDIZIONE LOGICA: stessa entità, affermazioni incompatibili (es. "X è titolare" vs "X non gioca mai")
2. EVOLUZIONE: opinione cambiata nel tempo dopo nuove partite/eventi → NON contare come incoerenza
3. ENTI DIVERSI: claim su persone/squadre diverse (controlla subject) → NON incoerenza
4. CONTESTO DIVERSO: partite/momenti diversi ("prossima partita" in video diversi) → NON incoerenza

Indica has_contradiction: true SOLO per casi di tipo 1. Altrimenti has_contradiction: false e description: "".`;

export function getInconsistencyPrompt(
  topic: string,
  subject: string | undefined,
  claims: {
    video_id: string;
    position: string;
    subject?: string;
    published_at?: string;
    summary?: string;
  }[]
): string {
  const formatted = claims.map((c) => {
    const parts = [`[Video ${c.video_id}]`, `"${c.position}"`];
    if (c.subject) parts.push(`(soggetto: ${c.subject})`);
    if (c.published_at) parts.push(`[${c.published_at}]`);
    if (c.summary) parts.push(`Contesto video: ${c.summary.slice(0, 150)}${c.summary.length > 150 ? "..." : ""}`);
    return parts.join(" ");
  });
  const subjectLine = subject ? `Soggetto: ${subject}\n\n` : "";
  return `Tema: ${topic}\n${subjectLine}Claims:\n${formatted.join("\n")}\n\nValuta se c'è una contraddizione logica (stessa entità, affermazioni incompatibili). Ignora evoluzioni temporali, enti diversi o contesti diversi.`;
}

export const BIAS_SYSTEM = `Sei un analista di media. Ricevi i claims (posizioni espresse) dall'autore di un canale, raggruppati per soggetto/tema, con statistiche di polarità (positivo/negativo/neutro).

Per ogni pattern identificato:
1. Indica il soggetto
2. Descrivi il pattern (es. "critica costante", "bilanciato", "supporto condizionato")
3. Cita 2-3 claim esemplari che lo supportano (copia il testo esatto)
4. Usa le statistiche polarità (N pos/neg/neut) se rilevanti
Rispondi in modo oggettivo, basandoti solo sui dati forniti. In italiano.`;

export type ClaimsWithStats = {
  items: { position: string; polarity?: string }[];
  stats: { positive: number; negative: number; neutral: number };
};

export function getBiasPrompt(claimsBySubject: Record<string, ClaimsWithStats>): string {
  const sections = Object.entries(claimsBySubject).map(([subject, { items, stats }]) => {
    const statsStr = `(${stats.negative} neg, ${stats.positive} pos, ${stats.neutral} neut)`;
    return `**${subject}** ${statsStr}:\n${items.map((i) => `- "${i.position}"${i.polarity ? ` (${i.polarity})` : ""}`).join("\n")}`;
  });
  return `Claims raggruppati per soggetto con statistiche polarità:\n\n${sections.join("\n\n")}\n\nIdentifica eventuali sbilanciamenti o pattern ricorrenti nelle posizioni dell'autore. Per ogni pattern, cita 2-3 claim esemplari (copia il testo) che lo supportano. Usa le statistiche per quantificare quando rilevante.`;
}
