import { existsSync } from "node:fs";
import { readFile, readdir } from "node:fs/promises";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(__dirname, "..");
const ANALYSIS_DIR = join(ROOT, "analysis");

type GateResult = {
  channel_id: string;
  ok: boolean;
  reason?: string;
  advisor_score?: number;
  evidence_fidelity?: number;
};

function parseNumberArg(args: string[], key: string, fallback: number): number {
  const raw = args.find((a) => a.startsWith(`--${key}=`))?.split("=")[1];
  if (!raw) return fallback;
  const n = Number(raw);
  if (!Number.isFinite(n)) return fallback;
  return n;
}

function parseStringArg(args: string[], key: string): string | undefined {
  return args.find((a) => a.startsWith(`--${key}=`))?.split("=")[1];
}

function clampPct(value: unknown): number {
  const n = typeof value === "number" && Number.isFinite(value) ? value : 0;
  return Math.max(0, Math.min(100, Math.round(n)));
}

async function listChannels(targetChannel?: string): Promise<string[]> {
  if (targetChannel) return [targetChannel];
  if (!existsSync(ANALYSIS_DIR)) return [];
  const entries = await readdir(ANALYSIS_DIR, { withFileTypes: true });
  return entries
    .filter((e) => e.isDirectory())
    .map((e) => e.name)
    .sort((a, b) => a.localeCompare(b));
}

async function checkChannel(
  channelId: string,
  opts: { minFidelity: number; minAdvisorScore: number; requirePredictionsResolved: boolean }
): Promise<GateResult> {
  const advisorPath = join(ANALYSIS_DIR, channelId, "_advisor.json");
  if (!existsSync(advisorPath)) {
    return { channel_id: channelId, ok: false, reason: "missing _advisor.json" };
  }

  try {
    const parsed = JSON.parse(await readFile(advisorPath, "utf-8")) as Record<string, unknown>;
    const scores =
      parsed.scores && typeof parsed.scores === "object"
        ? (parsed.scores as Record<string, unknown>)
        : {};
    const breakdown =
      parsed.breakdown && typeof parsed.breakdown === "object"
        ? (parsed.breakdown as Record<string, unknown>)
        : {};
    const predictions =
      breakdown.predictions && typeof breakdown.predictions === "object"
        ? (breakdown.predictions as Record<string, unknown>)
        : {};

    const fidelity = clampPct(scores.evidence_fidelity);
    const advisorScore = clampPct(scores.advisor_score);
    const resolvedPredictions = Math.max(
      0,
      Math.round(
        typeof predictions.resolved === "number" && Number.isFinite(predictions.resolved)
          ? predictions.resolved
          : 0
      )
    );

    if (fidelity < opts.minFidelity) {
      return {
        channel_id: channelId,
        ok: false,
        reason: `evidence_fidelity ${fidelity} < min_fidelity ${opts.minFidelity}`,
        advisor_score: advisorScore,
        evidence_fidelity: fidelity,
      };
    }

    if (advisorScore < opts.minAdvisorScore) {
      return {
        channel_id: channelId,
        ok: false,
        reason: `advisor_score ${advisorScore} < min_advisor_score ${opts.minAdvisorScore}`,
        advisor_score: advisorScore,
        evidence_fidelity: fidelity,
      };
    }

    if (opts.requirePredictionsResolved && resolvedPredictions <= 0) {
      return {
        channel_id: channelId,
        ok: false,
        reason: "no resolved predictions found",
        advisor_score: advisorScore,
        evidence_fidelity: fidelity,
      };
    }

    return {
      channel_id: channelId,
      ok: true,
      advisor_score: advisorScore,
      evidence_fidelity: fidelity,
    };
  } catch (e) {
    return {
      channel_id: channelId,
      ok: false,
      reason: `invalid advisor json: ${(e as Error).message}`,
    };
  }
}

async function main() {
  const args = process.argv.slice(2);
  const channel = parseStringArg(args, "channel");
  const minFidelity = Math.max(0, Math.min(100, Math.round(parseNumberArg(args, "min-fidelity", 70))));
  const minAdvisorScore = Math.max(0, Math.min(100, Math.round(parseNumberArg(args, "min-advisor-score", 0))));
  const requirePredictionsResolved = args.includes("--require-predictions-resolved");

  const channels = await listChannels(channel);
  if (channels.length === 0) {
    console.error("advisor-gate: no channels found to evaluate");
    process.exit(1);
  }

  const results: GateResult[] = [];
  for (const ch of channels) {
    const res = await checkChannel(ch, {
      minFidelity,
      minAdvisorScore,
      requirePredictionsResolved,
    });
    results.push(res);
  }

  const failed = results.filter((r) => !r.ok);
  for (const r of results) {
    if (r.ok) {
      console.log(
        `[PASS] ${r.channel_id} fidelity=${r.evidence_fidelity} score=${r.advisor_score}`
      );
    } else {
      console.log(`[FAIL] ${r.channel_id} ${r.reason}`);
    }
  }

  if (failed.length > 0) {
    console.error(`advisor-gate: ${failed.length}/${results.length} channels failed`);
    process.exit(1);
  }
  console.log(`advisor-gate: all ${results.length} channels passed`);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
