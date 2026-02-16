/**
 * Step 2D — Anti-fuffa filter: scarta claim troppo vaghi.
 */

import type { Claim } from "../schema/claims.js";

const VAGUE_WORDS = /\b(importante|merita|meritano|crescita|buon|bene|male|bella|bello|interessante|interessanti|particolare|particolari)\b/i;

const ACTION_VERBS = /\b(pressare|pressing|costruire|rotazione|modulo|formazione|5-3-2|4-3-3|scavare|gestione|allenare)\b/i;

export function specificityScore(c: Claim): number {
  const txt = c.claim_text;
  let s = 0;

  if (/\d+/.test(txt)) s += 2;
  if (ACTION_VERBS.test(txt)) s += 2;
  if (c.target_entity && c.target_entity.length > 2) s += 1;
  if (VAGUE_WORDS.test(txt) && !ACTION_VERBS.test(txt) && !/\d+/.test(txt)) s -= 2;

  const wordCount = txt.split(/\s+/).filter(Boolean).length;
  if (wordCount >= 8 && wordCount <= 25) s += 1;
  if (wordCount < 5) s -= 1;

  return s;
}

export function passesSpecificityFilter(c: Claim, minScore = -1): boolean {
  return specificityScore(c) >= minScore;
}

export function filterBySpecificity(claims: Claim[], minScore = -1): Claim[] {
  return claims.filter((c) => passesSpecificityFilter(c, minScore));
}
