/**
 * Video-level evaluation: produces a content creator "report card" per video.
 * Scores factuality, objectivity, argumentation quality, etc.
 */

import OpenAI from "openai";
import type { Claim, VideoEvaluation } from "../schema/claims.js";

const EVAL_SCHEMA = {
  type: "object" as const,
  properties: {
    factuality_index: {
      type: "number",
      description: "0-100: % di affermazioni verificabili/fattuali vs opinioni non supportate. 100 = tutto verificabile.",
    },
    objectivity_index: {
      type: "number",
      description: "0-100: equilibrio nella copertura (stance POS/NEG bilanciate, assenza di linguaggio caricato). 100 = perfettamente bilanciato.",
    },
    argumentation_quality: {
      type: "number",
      description: "0-100: rigore logico delle argomentazioni. Penalizza fallacie logiche, salti logici, ragionamenti circolari. 100 = argomentazioni impeccabili.",
    },
    information_density: {
      type: "number",
      description: "0-100: quanta informazione utile/actionable vs riempitivi, divagazioni, ripetizioni. 100 = densissimo di contenuto.",
    },
    sensationalism_index: {
      type: "number",
      description: "0-100: livello di sensazionalismo, esagerazioni, clickbait, toni allarmistici. 0 = sobrio e misurato, 100 = estremamente sensazionalistico.",
    },
    source_reliability: {
      type: "number",
      description: "0-100: quanto il creator cita fonti verificabili, dati concreti, riferimenti precisi. 100 = tutte le affermazioni supportate da fonti.",
    },
    overall_credibility: {
      type: "number",
      description: "0-100: credibilità complessiva ponderata di tutti i fattori. Un punteggio sintetico.",
    },
    emotional_tone: {
      type: "array",
      items: { type: "string" },
      description: "1-3 tag del registro emotivo dominante (es. 'indignazione', 'entusiasmo', 'ironia', 'analitico', 'polemico', 'rassegnato').",
    },
    rhetorical_techniques: {
      type: "array",
      items: {
        type: "object",
        properties: {
          technique: {
            type: "string",
            description: "Nome della tecnica retorica/persuasiva (es. 'appello all'emozione', 'uomo di paglia', 'cherry-picking', 'ad hominem', 'iperbole', 'falso dilemma', 'appello all'autorità', 'generalizzazione', 'whataboutism').",
          },
          example: {
            type: "string",
            description: "Citazione/esempio dal video che dimostra la tecnica.",
          },
          frequency: {
            type: "string",
            enum: ["low", "medium", "high"],
            description: "Quanto spesso viene usata nel video.",
          },
        },
        required: ["technique", "example", "frequency"],
        additionalProperties: false,
      },
      description: "Tecniche retoriche/persuasive rilevate.",
    },
    content_type_breakdown: {
      type: "object",
      properties: {
        facts_pct: { type: "number", description: "% di contenuto fattuale/verificabile" },
        opinions_pct: { type: "number", description: "% di opinioni/giudizi personali" },
        predictions_pct: { type: "number", description: "% di previsioni" },
        prescriptions_pct: { type: "number", description: "% di prescrizioni (cosa dovrebbero fare)" },
      },
      required: ["facts_pct", "opinions_pct", "predictions_pct", "prescriptions_pct"],
      additionalProperties: false,
    },
    key_strengths: {
      type: "array",
      items: { type: "string" },
      description: "2-4 punti di forza del video/creator (es. 'analisi tattica dettagliata', 'cita statistiche reali').",
    },
    key_weaknesses: {
      type: "array",
      items: { type: "string" },
      description: "2-4 punti deboli del video/creator (es. 'generalizzazioni eccessive', 'assenza di fonti').",
    },
  },
  required: [
    "factuality_index",
    "objectivity_index",
    "argumentation_quality",
    "information_density",
    "sensationalism_index",
    "source_reliability",
    "overall_credibility",
    "emotional_tone",
    "rhetorical_techniques",
    "content_type_breakdown",
    "key_strengths",
    "key_weaknesses",
  ],
  additionalProperties: false,
};

const EVAL_SYSTEM = `Sei un analista esperto di media e comunicazione. Valuta la QUALITÀ INFORMATIVA di un video di un content creator sportivo/calcistico.

Ricevi: un riassunto del video, i claim estratti (con tipo, stance, intensità), e i temi trattati.

Produci una valutazione RIGOROSA e OGGETTIVA con i seguenti parametri (tutti 0-100):

CRITERI DI VALUTAZIONE:
- factuality_index: basati sulla distribuzione dei claim_type. FACT/OBSERVATION = alto, JUDGEMENT/PREDICTION senza evidenze = basso. Controlla se i fatti sono specifici (nomi, date, numeri) o vaghi.
- objectivity_index: analizza la distribuzione delle stance (POS/NEG/NEU). Un creator che è sempre NEG su una entità o sempre POS su un'altra è meno oggettivo. Controlla se c'è equilibrio.
- argumentation_quality: valuta la logica delle argomentazioni. Claim con modality CERTAIN ma basati su interpretazioni = bassa qualità. Presenza di fallacie = penalizza.
- information_density: rapporto tra claim specifici/utili e contenuto generico/ripetitivo. Più claim filtrati per specificità = più denso.
- sensationalism_index: linguaggio caricato, iperboli, toni drammatici, generalizzazioni estreme ("sempre", "mai", "tutti"). Più ne trovi, più alto il punteggio.
- source_reliability: il creator cita fonti? Statistiche? Dichiarazioni ufficiali? Documenti? Se non cita nulla = basso.
- overall_credibility: media ponderata: factuality (25%), argumentation (20%), objectivity (20%), source_reliability (15%), (100 - sensationalism) (10%), information_density (10%).

TECNICHE RETORICHE DA CERCARE:
- Appello all'emozione (rabbia, paura, entusiasmo)
- Uomo di paglia (distorcere la posizione avversaria)
- Cherry-picking (selezionare solo i dati che supportano la tesi)
- Ad hominem (attaccare la persona, non l'argomento)
- Iperbole (esagerazioni eccessive)
- Falso dilemma (presentare solo 2 opzioni)
- Appello all'autorità (senza verificare la fonte)
- Generalizzazione (da un caso a tutti)
- Whataboutism (deviare su altri argomenti)
- Confirmation bias (cercare solo conferme)

Sii CRITICO ma GIUSTO. Non gonfiare i punteggi. Un video di pura opinione senza fonti non può avere factuality > 30.
Rispondi in italiano per key_strengths, key_weaknesses ed example nelle rhetorical_techniques.`;

export interface EvaluatorInput {
  summary: string;
  claims: Claim[];
  themes: { theme: string; weight: number }[];
  metadata?: { title?: string; published_at?: string; opinionist?: string };
}

export async function evaluateVideo(
  openai: OpenAI,
  input: EvaluatorInput
): Promise<VideoEvaluation> {
  const claimsSummary = input.claims
    .slice(0, 15)
    .map((c) => {
      const parts = [
        `[${c.claim_type}/${c.stance}/${c.modality}]`,
        c.target_entity ? `→ ${c.target_entity}:` : "",
        c.claim_text,
        c.intensity != null ? `(intensità: ${c.intensity})` : "",
      ];
      return parts.filter(Boolean).join(" ");
    })
    .join("\n");

  const themesSummary = input.themes
    .slice(0, 10)
    .map((t) => `${t.theme} (${t.weight}%)`)
    .join(", ");

  let userContent = "";
  if (input.metadata?.title) userContent += `Titolo: ${input.metadata.title}\n`;
  if (input.metadata?.opinionist) userContent += `Creator: ${input.metadata.opinionist}\n`;
  if (input.metadata?.published_at) userContent += `Data: ${input.metadata.published_at}\n`;
  userContent += `\nRiassunto: ${input.summary}\n`;
  userContent += `\nTemi: ${themesSummary}\n`;
  userContent += `\nClaim estratti (${input.claims.length} totali):\n${claimsSummary}\n`;

  const stanceDist = { POS: 0, NEG: 0, NEU: 0, MIXED: 0 };
  const typeDist: Record<string, number> = {};
  for (const c of input.claims) {
    stanceDist[c.stance] = (stanceDist[c.stance] ?? 0) + 1;
    typeDist[c.claim_type] = (typeDist[c.claim_type] ?? 0) + 1;
  }
  userContent += `\nDistribuzione stance: POS=${stanceDist.POS} NEG=${stanceDist.NEG} NEU=${stanceDist.NEU} MIXED=${stanceDist.MIXED}`;
  userContent += `\nDistribuzione tipo: ${Object.entries(typeDist).map(([k, v]) => `${k}=${v}`).join(" ")}`;

  const completion = await openai.chat.completions.create({
    model: "gpt-4o-mini",
    messages: [
      { role: "system", content: EVAL_SYSTEM },
      { role: "user", content: userContent },
    ],
    response_format: {
      type: "json_schema",
      json_schema: {
        name: "video_evaluation",
        strict: true,
        schema: EVAL_SCHEMA,
      },
    },
  });

  const content = completion.choices[0]?.message?.content;
  if (!content) throw new Error("Empty evaluation response");

  const parsed = JSON.parse(content) as VideoEvaluation;

  return {
    factuality_index: clamp(parsed.factuality_index),
    objectivity_index: clamp(parsed.objectivity_index),
    argumentation_quality: clamp(parsed.argumentation_quality),
    information_density: clamp(parsed.information_density),
    sensationalism_index: clamp(parsed.sensationalism_index),
    source_reliability: clamp(parsed.source_reliability),
    overall_credibility: clamp(parsed.overall_credibility),
    emotional_tone: (parsed.emotional_tone ?? []).slice(0, 3),
    rhetorical_techniques: (parsed.rhetorical_techniques ?? []).slice(0, 8),
    content_type_breakdown: {
      facts_pct: clamp(parsed.content_type_breakdown?.facts_pct ?? 0),
      opinions_pct: clamp(parsed.content_type_breakdown?.opinions_pct ?? 0),
      predictions_pct: clamp(parsed.content_type_breakdown?.predictions_pct ?? 0),
      prescriptions_pct: clamp(parsed.content_type_breakdown?.prescriptions_pct ?? 0),
    },
    key_strengths: (parsed.key_strengths ?? []).slice(0, 4),
    key_weaknesses: (parsed.key_weaknesses ?? []).slice(0, 4),
  };
}

function clamp(v: number, min = 0, max = 100): number {
  return Math.round(Math.min(max, Math.max(min, v ?? 0)));
}
