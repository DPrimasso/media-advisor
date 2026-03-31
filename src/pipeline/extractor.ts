/**
 * Step 2B — Claim extraction from segments.
 * Max 4 claims per segment, each with quote from transcript.
 */

import OpenAI from "openai";
import { randomUUID } from "node:crypto";
import type { Claim, EvidenceQuote, Theme } from "../schema/claims.js";
import type { Segment } from "./segmenter.js";

const EXTRACT_SCHEMA = {
  type: "object" as const,
  properties: {
    claims: {
      type: "array",
      items: {
        type: "object",
        properties: {
          target_entity: { type: "string" },
          entity_type: { type: "string", enum: ["team", "player", "coach", "ref", "club", "other"] },
          dimension: { type: "string", enum: ["performance", "tactics", "market", "finance", "leadership", "injury", "lineup_prediction", "refereeing", "fan_behavior", "standings", "europe", "rivalry", "media"] },
          claim_type: { type: "string", enum: ["FACT", "OBSERVATION", "INTERPRETATION", "JUDGEMENT", "PRESCRIPTION", "PREDICTION", "META_INFO_QUALITY"] },
          stance: { type: "string", enum: ["POS", "NEG", "NEU", "MIXED"] },
          intensity: { type: "number", minimum: 0, maximum: 3 },
          modality: { type: "string", enum: ["CERTAIN", "PROBABLE", "POSSIBLE", "HYPOTHESIS", "PRESCRIPTIVE"] },
          claim_text: { type: "string" },
          quote_text: { type: "string", description: "Verbatim quote from segment that supports the claim" },
          tags: { type: "array", items: { type: "string" }, maxItems: 6 },
        },
        required: ["target_entity", "entity_type", "dimension", "claim_type", "stance", "intensity", "modality", "claim_text", "quote_text", "tags"],
        additionalProperties: false,
      },
      maxItems: 4,
    },
    micro_themes: {
      type: "array",
      items: {
        type: "object",
        properties: {
          theme: { type: "string" },
          weight: { type: "number", minimum: 0, maximum: 100 },
        },
        required: ["theme", "weight"],
        additionalProperties: false,
      },
    },
  },
  required: ["claims", "micro_themes"],
  additionalProperties: false,
};

const EXTRACT_SYSTEM = `Sei un estrattore di claim da transcript di video sportivi/calcio.
Per ogni SEGMENTO di transcript:
1. Estrai al massimo 4 claim atomici (una frase concreta ciascuno, non periodi lunghi)
2. Per OGNI claim DEVI includere quote_text: una citazione VERBATIM dal testo del segmento che supporta il claim
3. La quote DEVE essere copiata esattamente dal transcript (sottostringa del segment)
4. target_entity: squadra, giocatore, allenatore, arbitro, ecc.
5. claim_text: sintesi atomica in 1 frase (max ~20 parole)
6. dimension: performance, tactics, market, finance, leadership, injury, lineup_prediction, refereeing, fan_behavior, standings, europe, rivalry, media
7. claim_type: FACT, OBSERVATION, INTERPRETATION, JUDGEMENT, PRESCRIPTION, PREDICTION, META_INFO_QUALITY
8. micro_themes: 1-3 temi del segmento con weight 0-100 — usa nomi in italiano, al singolare, senza maiuscole (es. "infortunio", "mercato", "tattica")

REGOLE IMPORTANTI:
- NON estrarre claim meta sull'autore/host del video (es. "X è appassionato di Y", "X si chiama Y", "X risponde alle domande", "X vuole analizzare", "l'opinionista fa/dice")
- NON estrarre claim su intro, saluti, call-to-action o parti di auto-presentazione
- NON estrarre claim che descrivono il formato del video invece del contenuto calcistico
- ESTRAI solo posizioni, fatti, interpretazioni, previsioni concreti su giocatori/squadre/eventi specifici
- target_entity deve essere un calciatore, squadra, allenatore, arbitro — NON "opinionista", "autore", "commentatore", "community"

REGOLE DI PRECISIONE:
- Se un'entità viene CITATA come paragone/precedente/esempio (es. "come ha fatto X"), NON costruire un claim del tipo "X ha commentato Y" — costruisci invece "X è citato come precedente per Y"
- Le dichiarazioni di lealtà di un giocatore verso la squadra DEVONO essere estratte come claim separato (claim_type: FACT, dimension: leadership)
- Il SILENZIO o la mancanza di comunicazione di una squadra è dimension "media", NON "performance" o "tactics"
- La perdita di un familiare o evento personale di un giocatore è dimension "leadership" (aspetto morale/motivazionale), NON "injury"
- EVITA di estrarre più claim che affermano la stessa sostanza con parole diverse (es. "ha avuto infortuni" + "ha avuto problemi fisici" + "non si sentiva bene" sullo stesso soggetto nello stesso segmento = estrai UN solo claim, il più specifico con quote migliore)`;

export interface ExtractorInput {
  segment: Segment;
  video_id: string;
  context?: { title?: string; published_at?: string; opinionist?: string };
}

export async function extractClaimsFromSegment(
  openai: OpenAI,
  input: ExtractorInput
): Promise<{ claims: Claim[]; themes: Theme[] }> {
  const { segment, video_id, context } = input;

  if (!segment.text || segment.text.length < 30) {
    return { claims: [], themes: [] };
  }

  let userContent = `Segmento (${segment.segment_id}, ${Math.round(segment.start_sec)}s-${Math.round(segment.end_sec)}s):\n\n`;
  if (context?.title) userContent += `Titolo video: ${context.title}\n`;
  if (context?.opinionist) userContent += `Opinionista: ${context.opinionist}\n`;
  if (context?.published_at) userContent += `Data: ${context.published_at}\n\n`;
  userContent += `Testo:\n${segment.text}`;

  const completion = await openai.chat.completions.create({
    model: "gpt-4o-mini",
    messages: [
      { role: "system", content: EXTRACT_SYSTEM },
      { role: "user", content: userContent },
    ],
    response_format: {
      type: "json_schema",
      json_schema: {
        name: "extract_result",
        strict: true,
        schema: EXTRACT_SCHEMA,
      },
    },
  });

  const content = completion.choices[0]?.message?.content;
  if (!content) return { claims: [], themes: [] };

  const parsed = JSON.parse(content) as {
    claims: Array<{
      target_entity: string;
      entity_type: string;
      dimension: string;
      claim_type: string;
      stance: string;
      intensity: number;
      modality: string;
      claim_text: string;
      quote_text: string;
      tags: string[];
    }>;
    micro_themes: Array<{ theme: string; weight: number }>;
  };

  const claims: Claim[] = [];
  for (const c of parsed.claims ?? []) {
    const quote: EvidenceQuote = {
      quote_text: c.quote_text,
      start_sec: segment.start_sec,
      end_sec: segment.end_sec,
      confidence: 0.9,
    };
    claims.push({
      claim_id: randomUUID(),
      video_id,
      segment_id: segment.segment_id,
      target_entity: c.target_entity,
      entity_type: c.entity_type as Claim["entity_type"],
      dimension: c.dimension as Claim["dimension"],
      claim_type: c.claim_type as Claim["claim_type"],
      stance: c.stance as Claim["stance"],
      intensity: Math.round(Math.min(3, Math.max(0, c.intensity ?? 1))) as 0 | 1 | 2 | 3,
      modality: c.modality as Claim["modality"],
      claim_text: c.claim_text,
      evidence_quotes: [quote],
      tags: (c.tags ?? []).slice(0, 6),
    });
  }

  const themes: Theme[] = (parsed.micro_themes ?? []).map((t) => ({
    theme: t.theme,
    weight: Math.min(100, Math.max(0, t.weight ?? 0)),
  }));

  return { claims, themes };
}
