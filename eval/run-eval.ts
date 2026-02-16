/**
 * Step 7 — Eval harness: run baseline vs v2, compare metrics.
 * Usage: npx tsx eval/run-eval.ts --system baseline|v2
 */

import { readdir, readFile } from "node:fs/promises";
import { join } from "node:path";
import {
  quoteSupportRate,
  redundancyRate,
  avgClaimSpecificity,
  coverageThemesAt6,
  claimsF1,
  loadGold,
  loadBaselineOutput,
} from "./metrics.js";

const EVAL_DIR = join(process.cwd(), "eval");
const GOLD_DIR = join(EVAL_DIR, "human_gold");
const OUT_BASELINE = join(EVAL_DIR, "out_baseline");
const OUT_V2 = join(EVAL_DIR, "out_v2");

async function main() {
  const args = process.argv.slice(2);
  const system = args.find((a) => a.startsWith("--system="))?.split("=")[1] ?? args[0] ?? "baseline";

  if (system !== "baseline" && system !== "v2") {
    console.error("Usage: npx tsx eval/run-eval.ts --system=baseline|v2");
    process.exit(1);
  }

  const goldFiles = (await readdir(GOLD_DIR))
    .filter((f) => f.endsWith(".gold.json"))
    .map((f) => f.replace(".gold.json", ""));

  if (goldFiles.length === 0) {
    console.log("No gold files in eval/human_gold/");
    process.exit(0);
  }

  const metrics = {
    quote_support_rate: 0,
    redundancy_rate: 0,
    avg_claim_specificity: 0,
    coverage_themes_at6: 0,
    claims_f1: 0,
  };

  let nWithData = 0;
  const channels = ["azzurro-fluido", "umberto-chiariello", "open-var"];

  for (const videoId of goldFiles) {
    const gold = await loadGold(videoId);
    if (!gold) continue;

    let channelId: string | null = null;
    const outDir = system === "v2" ? OUT_V2 : OUT_BASELINE;
    for (const ch of channels) {
      try {
        await readFile(join(outDir, ch, `${videoId}.json`), "utf-8");
        channelId = ch;
        break;
      } catch {
        // try next
      }
    }
    if (!channelId) continue;
    let data: { claims?: unknown[]; topics?: { name: string }[]; themes?: { theme: string }[] } | null = null;
    try {
      const raw = await readFile(join(outDir, channelId, `${videoId}.json`), "utf-8");
      data = JSON.parse(raw);
    } catch {
      continue;
    }

    if (!data) continue;
    nWithData++;

    const claims = (data.claims ?? []) as Array<{
      evidence_quotes?: unknown[];
      claim_text?: string;
      position?: string;
      target_entity?: string;
    }>;

    metrics.quote_support_rate += quoteSupportRate(claims);
    metrics.redundancy_rate += redundancyRate(
      claims.map((c) => ({ claim_text: c.claim_text, position: c.position }))
    );
    metrics.avg_claim_specificity += avgClaimSpecificity(claims as import("../src/schema/claims.js").Claim[]);

    const predThemes = data.themes ?? data.topics ?? [];
    metrics.coverage_themes_at6 += coverageThemesAt6(predThemes, gold.themes ?? []);

    const predClaims = claims.map((c) => ({
      claim_text: c.claim_text ?? c.position,
      position: c.position ?? c.claim_text,
    }));
    const { f1 } = claimsF1(predClaims, gold.claims ?? []);
    metrics.claims_f1 += f1;
  }

  if (nWithData === 0) {
    console.log("No matching baseline/v2 output for gold videos. Run npm run eval:baseline first.");
    process.exit(1);
  }

  const n = nWithData;
  console.log(`\n=== Eval [${system}] (${n} gold videos) ===\n`);
  console.log("quote_support_rate:    ", (metrics.quote_support_rate / n).toFixed(3));
  console.log("redundancy_rate:      ", (metrics.redundancy_rate / n).toFixed(3));
  console.log("avg_claim_specificity: ", (metrics.avg_claim_specificity / n).toFixed(3));
  console.log("coverage_themes@6:     ", (metrics.coverage_themes_at6 / n).toFixed(3));
  console.log("claims_f1:            ", (metrics.claims_f1 / n).toFixed(3));
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
