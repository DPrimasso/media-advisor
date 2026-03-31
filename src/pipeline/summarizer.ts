/**
 * Step 2E — AI summary generation from full transcript text + claims.
 * Produces a 2-3 sentence summary in Italian of the video's key points.
 */

import OpenAI from "openai";
import type { Claim } from "../schema/claims.js";

const SUMMARIZE_SYSTEM = `Sei un analista di media sportivi italiani. Ricevi la trascrizione di un video YouTube di un opinionista calcistico e una lista di claim estratti.

Produci un riassunto in italiano di 2-3 frasi che:
1. Descriva il tema centrale del video (cosa viene discusso/analizzato)
2. Sintetizzi la posizione principale dell'autore
3. Menzioni eventuali ipotesi o conclusioni chiave

Il riassunto deve essere:
- Oggettivo e basato sul contenuto
- Concreto (nomi, fatti, posizioni specifiche)
- Max 150 parole
- In italiano`;

export async function generateSummary(
  openai: OpenAI,
  input: {
    title?: string;
    author?: string;
    fullText: string;
    claims: Claim[];
  }
): Promise<string> {
  const claimsText = input.claims
    .slice(0, 8)
    .map((c) => `- ${c.claim_text}`)
    .join("\n");

  const truncatedText = input.fullText.slice(0, 3000);

  let userContent = "";
  if (input.title) userContent += `Titolo: ${input.title}\n`;
  if (input.author) userContent += `Autore: ${input.author}\n\n`;
  userContent += `Trascrizione (estratto):\n${truncatedText}\n\n`;
  if (claimsText) userContent += `Claim estratti:\n${claimsText}\n`;

  const completion = await openai.chat.completions.create({
    model: "gpt-4o-mini",
    messages: [
      { role: "system", content: SUMMARIZE_SYSTEM },
      { role: "user", content: userContent },
    ],
    max_tokens: 200,
    temperature: 0.3,
  });

  return completion.choices[0]?.message?.content?.trim() ?? input.title ?? "Video";
}
