const SYSTEM_PROMPT = `Sei un analista di media. Analizza transcript di video YouTube di giornalisti e opinionisti.

Produci:
1. Un riassunto sintetico dei punti principali del video
2. Una lista di temi trattati con rilevanza (high, medium, low)
3. Una lista di claims: posizioni/opinioni chiave espresse dall'autore su temi specifici. Per ogni claim indica:
   - topic: il tema (es. "arbitri", "formazione Napoli")
   - subject: l'entità citata se applicabile (es. "Napoli", "ADL", "VAR"); usa "" se nessuna
   - position: cosa sostiene in sintesi
   - polarity: positive/negative/neutral; usa "neutral" se non esplicitamente espressa

Le tue analisi devono essere:
- Oggettive e basate solo sul contenuto del transcript
- Sintetiche ma complete
- In italiano`;

export function getAnalysisPrompt(
  plainText: string,
  metadata?: { title?: string; author_name?: string }
): { system: string; user: string } {
  let userContent = "";

  if (metadata?.title || metadata?.author_name) {
    userContent += "Metadata del video:\n";
    if (metadata.title) userContent += `- Titolo: ${metadata.title}\n`;
    if (metadata.author_name) userContent += `- Autore: ${metadata.author_name}\n`;
    userContent += "\n";
  }

  userContent += "Trascrizione:\n\n" + plainText;

  return {
    system: SYSTEM_PROMPT,
    user: userContent,
  };
}
