/**
 * Step 6 — Inconsistency detection: HARD/SOFT/DRIFT/NOT.
 */

import type { Claim } from "../schema/claims.js";

export type InconsistencyType = "HARD" | "SOFT" | "DRIFT" | "NOT";

export interface InconsistencyEvent {
  type: InconsistencyType;
  entity: string;
  dimension: string;
  claim_a: { video_id: string; date?: string; quote: string; claim_text: string };
  claim_b: { video_id: string; date?: string; quote: string; claim_text: string };
  explanation: string;
}

function stanceOpposite(sa: string, sb: string): boolean {
  const pair = [sa, sb].sort().join("|");
  return pair === "NEG|POS" || pair === "MIXED|NEG" || pair === "MIXED|POS";
}

function sameDimension(dim: string, other: string): boolean {
  return dim === other;
}

export interface ClaimWithMeta extends Claim {
  published_at?: string;
}

export function detectInconsistencies(
  claimsByChannel: Map<string, ClaimWithMeta[]>,
  videoDates?: Map<string, string>
): InconsistencyEvent[] {
  const events: InconsistencyEvent[] = [];

  const allClaims: ClaimWithMeta[] = [];
  for (const arr of claimsByChannel.values()) allClaims.push(...arr);

  for (let i = 0; i < allClaims.length; i++) {
    for (let j = i + 1; j < allClaims.length; j++) {
      const a = allClaims[i];
      const b = allClaims[j];

      if (a.video_id === b.video_id) continue;

      const entityA = a.target_entity?.toLowerCase() ?? "";
      const entityB = b.target_entity?.toLowerCase() ?? "";
      if (!entityA || !entityB || entityA !== entityB) continue;

      if (!sameDimension(a.dimension, b.dimension)) {
        events.push({
          type: "NOT",
          entity: a.target_entity,
          dimension: `${a.dimension} vs ${b.dimension}`,
          claim_a: {
            video_id: a.video_id,
            date: a.published_at ?? videoDates?.get(a.video_id),
            quote: a.evidence_quotes?.[0]?.quote_text ?? "",
            claim_text: a.claim_text,
          },
          claim_b: {
            video_id: b.video_id,
            date: b.published_at ?? videoDates?.get(b.video_id),
            quote: b.evidence_quotes?.[0]?.quote_text ?? "",
            claim_text: b.claim_text,
          },
          explanation: "Dimensioni diverse: non contraddizione diretta",
        });
        continue;
      }

      if (!stanceOpposite(a.stance, b.stance)) continue;

      const dateA = a.published_at ?? videoDates?.get(a.video_id) ?? "";
      const dateB = b.published_at ?? videoDates?.get(b.video_id) ?? "";
      const samePeriod = dateA && dateB && Math.abs(new Date(dateA).getTime() - new Date(dateB).getTime()) < 30 * 24 * 3600 * 1000;

      if (
        a.modality === "CERTAIN" &&
        b.modality === "CERTAIN" &&
        samePeriod
      ) {
        events.push({
          type: "HARD",
          entity: a.target_entity,
          dimension: a.dimension,
          claim_a: {
            video_id: a.video_id,
            date: dateA,
            quote: a.evidence_quotes?.[0]?.quote_text ?? "",
            claim_text: a.claim_text,
          },
          claim_b: {
            video_id: b.video_id,
            date: dateB,
            quote: b.evidence_quotes?.[0]?.quote_text ?? "",
            claim_text: b.claim_text,
          },
          explanation: "Stance opposta, modality CERTAIN, stesso periodo",
        });
      } else if (dateA && dateB && dateA !== dateB) {
        events.push({
          type: "DRIFT",
          entity: a.target_entity,
          dimension: a.dimension,
          claim_a: {
            video_id: a.video_id,
            date: dateA,
            quote: a.evidence_quotes?.[0]?.quote_text ?? "",
            claim_text: a.claim_text,
          },
          claim_b: {
            video_id: b.video_id,
            date: dateB,
            quote: b.evidence_quotes?.[0]?.quote_text ?? "",
            claim_text: b.claim_text,
          },
          explanation: "Cambio stance nel tempo (timeline)",
        });
      } else {
        events.push({
          type: "SOFT",
          entity: a.target_entity,
          dimension: a.dimension,
          claim_a: {
            video_id: a.video_id,
            date: dateA,
            quote: a.evidence_quotes?.[0]?.quote_text ?? "",
            claim_text: a.claim_text,
          },
          claim_b: {
            video_id: b.video_id,
            date: dateB,
            quote: b.evidence_quotes?.[0]?.quote_text ?? "",
            claim_text: b.claim_text,
          },
          explanation: "Stance opposta ma modality/contesto diverso",
        });
      }
    }
  }

  return events;
}
