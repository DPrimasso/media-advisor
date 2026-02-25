/**
 * Step 3 — Validator: la quote supporta il claim?
 * YES/NO + repair se possibile.
 */

import OpenAI from "openai";
import type { Claim } from "../schema/claims.js";

const VALIDATE_SCHEMA = {
  type: "object" as const,
  properties: {
    supported: { type: "boolean" },
    reason: { type: "string" },
    repaired_claim_text: { type: "string", description: "Only if supported=false, suggest rewrite using only the quote" },
  },
  required: ["supported", "reason"],
  additionalProperties: false,
};

const VALIDATE_SYSTEM = `Verifica se la QUOTE (citazione verbatim dal transcript) supporta davvero il CLAIM.
- supported: true solo se la quote dimostra/suggerisce direttamente il claim
- supported: false se il claim è un'interpretazione eccessiva, un salto logico, o non è nel testo
- repaired_claim_text: solo se supported=false, riscrivi il claim_text usando SOLO parole presenti nella quote (1 frase atomica)`;

export interface ValidationResult {
  claim: Claim;
  supported: boolean;
  reason: string;
  repaired_claim_text?: string;
}

export interface ValidationStats {
  total: number;
  supported: number;
  repaired: number;
  dropped: number;
}

export async function validateClaim(
  openai: OpenAI,
  claim: Claim
): Promise<ValidationResult> {
  const quote = claim.evidence_quotes?.[0];
  if (!quote) {
    return {
      claim,
      supported: false,
      reason: "No evidence quote",
    };
  }

  const userContent = `Claim: ${claim.claim_text}\nQuote: "${quote.quote_text}"`;

  const completion = await openai.chat.completions.create({
    model: "gpt-4o-mini",
    messages: [
      { role: "system", content: VALIDATE_SYSTEM },
      { role: "user", content: userContent },
    ],
    response_format: {
      type: "json_schema",
      json_schema: {
        name: "validate_result",
        strict: true,
        schema: VALIDATE_SCHEMA,
      },
    },
  });

  const content = completion.choices[0]?.message?.content;
  if (!content) {
    return { claim, supported: false, reason: "Empty response" };
  }

  const parsed = JSON.parse(content) as {
    supported: boolean;
    reason: string;
    repaired_claim_text?: string;
  };

  const repaired =
    !parsed.supported && parsed.repaired_claim_text
      ? { ...claim, claim_text: parsed.repaired_claim_text }
      : claim;

  return {
    claim: repaired,
    supported: parsed.supported,
    reason: parsed.reason,
    repaired_claim_text: parsed.repaired_claim_text,
  };
}

export async function validateClaims(
  openai: OpenAI,
  claims: Claim[],
  opts?: { dropUnsupported?: boolean }
): Promise<{ validated: Claim[]; dropped: Claim[]; stats: ValidationStats }> {
  const dropUnsupported = opts?.dropUnsupported ?? true;
  const validated: Claim[] = [];
  const dropped: Claim[] = [];
  let supported = 0;
  let repaired = 0;

  for (const c of claims) {
    const res = await validateClaim(openai, c);
    if (res.supported) {
      validated.push(res.claim);
      supported++;
    } else if (res.repaired_claim_text && res.repaired_claim_text.length >= 10) {
      validated.push({ ...res.claim, claim_text: res.repaired_claim_text });
      repaired++;
    } else if (dropUnsupported) {
      dropped.push(res.claim);
    } else {
      validated.push(res.claim);
    }
  }

  return {
    validated,
    dropped,
    stats: {
      total: claims.length,
      supported,
      repaired,
      dropped: dropped.length,
    },
  };
}
