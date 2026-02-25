import { existsSync } from "node:fs";
import { mkdir, readFile, readdir, writeFile } from "node:fs/promises";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(__dirname, "..");
const ANALYSIS_DIR = join(ROOT, "analysis");
const CHANNELS_CONFIG = join(ROOT, "channels", "channels.json");
const DEFAULT_OUT = join(ROOT, "eval", "advisor-quality-report.json");
const METRIC_KEYS = [
  "advisor_score",
  "evidence_coverage",
  "evidence_fidelity",
  "specificity_score",
  "coherence_score",
  "prediction_accountability",
  "bias_concentration",
  "absolutism_rate",
  "topic_diversity",
] as const;

type MetricKey = (typeof METRIC_KEYS)[number];
type ScoreMap = Record<MetricKey, number>;

interface ChannelAdvisorRow {
  channel_id: string;
  channel_name?: string;
  videos_analyzed: number;
  claims_analyzed: number;
  scores: ScoreMap;
}

interface AdvisorEvalReport {
  generated_at: string;
  source: { analysis_dir: string; baseline_path?: string };
  aggregate: {
    channels_total: number;
    channels_with_advisor: number;
    simple_mean: ScoreMap;
    weighted_by_claims: ScoreMap;
  };
  channels: ChannelAdvisorRow[];
  comparison?: {
    baseline_generated_at?: string;
    aggregate_delta_simple_mean: ScoreMap;
    aggregate_delta_weighted_by_claims: ScoreMap;
    channel_delta_advisor_score: Array<{
      channel_id: string;
      before: number;
      after: number;
      delta: number;
    }>;
  };
}

function parseArgs(args: string[]): {
  outPath: string;
  baselinePath?: string;
  saveBaselinePath?: string;
  requireBaseline: boolean;
  minDeltaSimpleAdvisorScore?: number;
  minDeltaWeightedAdvisorScore?: number;
} {
  const getArg = (key: string): string | undefined =>
    args.find((a) => a.startsWith(`--${key}=`))?.split("=")[1];
  const getNumber = (key: string): number | undefined => {
    const raw = getArg(key);
    if (!raw) return undefined;
    const n = Number(raw);
    return Number.isFinite(n) ? n : undefined;
  };
  const getBoolean = (key: string, fallback = false): boolean => {
    const raw = getArg(key);
    if (!raw) return fallback;
    const norm = raw.trim().toLowerCase();
    if (["1", "true", "yes", "on"].includes(norm)) return true;
    if (["0", "false", "no", "off"].includes(norm)) return false;
    return fallback;
  };

  const out = getArg("out");
  const baseline = getArg("baseline");
  const saveBaseline = getArg("save-baseline");

  return {
    outPath: out ? resolve(process.cwd(), out) : DEFAULT_OUT,
    baselinePath: baseline ? resolve(process.cwd(), baseline) : undefined,
    saveBaselinePath: saveBaseline ? resolve(process.cwd(), saveBaseline) : undefined,
    requireBaseline: getBoolean("require-baseline", false),
    minDeltaSimpleAdvisorScore: getNumber("min-delta-simple-advisor-score"),
    minDeltaWeightedAdvisorScore: getNumber("min-delta-weighted-advisor-score"),
  };
}

function zeroScores(): ScoreMap {
  return {
    advisor_score: 0,
    evidence_coverage: 0,
    evidence_fidelity: 0,
    specificity_score: 0,
    coherence_score: 0,
    prediction_accountability: 0,
    bias_concentration: 0,
    absolutism_rate: 0,
    topic_diversity: 0,
  };
}

function clampPct(n: unknown): number {
  const value = typeof n === "number" && Number.isFinite(n) ? n : 0;
  return Math.max(0, Math.min(100, Math.round(value)));
}

function asScores(input: unknown): ScoreMap {
  const obj = input && typeof input === "object" ? (input as Record<string, unknown>) : {};
  const scores = zeroScores();
  for (const k of METRIC_KEYS) scores[k] = clampPct(obj[k]);
  return scores;
}

function addScores(target: ScoreMap, input: ScoreMap, weight = 1): void {
  for (const k of METRIC_KEYS) {
    target[k] += input[k] * weight;
  }
}

function divideScores(input: ScoreMap, den: number): ScoreMap {
  if (den <= 0) return zeroScores();
  const out = zeroScores();
  for (const k of METRIC_KEYS) out[k] = Math.round((input[k] / den) * 100) / 100;
  return out;
}

async function loadChannelMeta(): Promise<Map<string, string>> {
  const map = new Map<string, string>();
  if (!existsSync(CHANNELS_CONFIG)) return map;
  try {
    const parsed = JSON.parse(await readFile(CHANNELS_CONFIG, "utf-8")) as {
      channels?: Array<{ id: string; name?: string }>;
    };
    for (const c of parsed.channels ?? []) {
      if (c?.id) map.set(c.id, c.name ?? c.id);
    }
  } catch {
    // ignore malformed channels config
  }
  return map;
}

async function collectAdvisorRows(): Promise<ChannelAdvisorRow[]> {
  if (!existsSync(ANALYSIS_DIR)) return [];
  const entries = await readdir(ANALYSIS_DIR, { withFileTypes: true });
  const channelMeta = await loadChannelMeta();
  const rows: ChannelAdvisorRow[] = [];

  for (const entry of entries) {
    if (!entry.isDirectory()) continue;
    const channelId = entry.name;
    const advisorPath = join(ANALYSIS_DIR, channelId, "_advisor.json");
    if (!existsSync(advisorPath)) continue;
    try {
      const parsed = JSON.parse(await readFile(advisorPath, "utf-8")) as Record<string, unknown>;
      rows.push({
        channel_id: channelId,
        channel_name: channelMeta.get(channelId),
        videos_analyzed:
          typeof parsed.videos_analyzed === "number" ? Math.max(0, Math.round(parsed.videos_analyzed)) : 0,
        claims_analyzed:
          typeof parsed.claims_analyzed === "number" ? Math.max(0, Math.round(parsed.claims_analyzed)) : 0,
        scores: asScores(parsed.scores),
      });
    } catch {
      // skip malformed advisor file
    }
  }

  return rows.sort((a, b) => a.channel_id.localeCompare(b.channel_id));
}

async function loadBaseline(path?: string): Promise<AdvisorEvalReport | null> {
  if (!path || !existsSync(path)) return null;
  try {
    return JSON.parse(await readFile(path, "utf-8")) as AdvisorEvalReport;
  } catch {
    return null;
  }
}

function computeAggregate(rows: ChannelAdvisorRow[], channelsTotal: number): AdvisorEvalReport["aggregate"] {
  const simpleAcc = zeroScores();
  const weightedAcc = zeroScores();
  let claimsWeight = 0;
  for (const row of rows) {
    addScores(simpleAcc, row.scores, 1);
    const w = Math.max(1, row.claims_analyzed);
    addScores(weightedAcc, row.scores, w);
    claimsWeight += w;
  }
  return {
    channels_total: channelsTotal,
    channels_with_advisor: rows.length,
    simple_mean: divideScores(simpleAcc, rows.length || 1),
    weighted_by_claims: divideScores(weightedAcc, claimsWeight || 1),
  };
}

function scoreDelta(after: ScoreMap, before: ScoreMap): ScoreMap {
  const d = zeroScores();
  for (const k of METRIC_KEYS) d[k] = Math.round((after[k] - before[k]) * 100) / 100;
  return d;
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  const rows = await collectAdvisorRows();

  const channelEntries = existsSync(ANALYSIS_DIR)
    ? (await readdir(ANALYSIS_DIR, { withFileTypes: true })).filter((e) => e.isDirectory()).length
    : 0;

  const report: AdvisorEvalReport = {
    generated_at: new Date().toISOString(),
    source: {
      analysis_dir: ANALYSIS_DIR,
      baseline_path: args.baselinePath,
    },
    aggregate: computeAggregate(rows, channelEntries),
    channels: rows,
  };

  const baseline = await loadBaseline(args.baselinePath);
  if (baseline?.aggregate && baseline?.channels) {
    const baselineSimple = asScores(baseline.aggregate.simple_mean);
    const baselineWeighted = asScores(baseline.aggregate.weighted_by_claims);
    const channelBefore = new Map(
      baseline.channels.map((c) => [c.channel_id, clampPct(c.scores?.advisor_score)])
    );
    const channelDelta = rows.map((r) => {
      const before = channelBefore.get(r.channel_id) ?? 0;
      return {
        channel_id: r.channel_id,
        before,
        after: r.scores.advisor_score,
        delta: Math.round((r.scores.advisor_score - before) * 100) / 100,
      };
    });

    report.comparison = {
      baseline_generated_at: baseline.generated_at,
      aggregate_delta_simple_mean: scoreDelta(report.aggregate.simple_mean, baselineSimple),
      aggregate_delta_weighted_by_claims: scoreDelta(report.aggregate.weighted_by_claims, baselineWeighted),
      channel_delta_advisor_score: channelDelta.sort((a, b) => b.delta - a.delta),
    };
  }

  await mkdir(dirname(args.outPath), { recursive: true });
  await writeFile(args.outPath, JSON.stringify(report, null, 2), "utf-8");

  if (args.saveBaselinePath) {
    await mkdir(dirname(args.saveBaselinePath), { recursive: true });
    await writeFile(args.saveBaselinePath, JSON.stringify(report, null, 2), "utf-8");
  }

  console.log(`advisor-eval: wrote ${args.outPath}`);
  console.log(
    `channels_with_advisor=${report.aggregate.channels_with_advisor}/${report.aggregate.channels_total} ` +
      `mean_score=${report.aggregate.simple_mean.advisor_score}`
  );
  if (report.comparison) {
    console.log(
      `delta(mean_score)=${report.comparison.aggregate_delta_simple_mean.advisor_score} ` +
        `delta(weighted_mean_score)=${report.comparison.aggregate_delta_weighted_by_claims.advisor_score}`
    );
  } else if (args.baselinePath) {
    console.log(`baseline not found or invalid: ${args.baselinePath}`);
  }

  if (args.requireBaseline && !report.comparison) {
    console.error("advisor-eval: baseline required but missing/invalid");
    process.exit(1);
  }

  if (
    report.comparison &&
    typeof args.minDeltaSimpleAdvisorScore === "number" &&
    report.comparison.aggregate_delta_simple_mean.advisor_score <
      args.minDeltaSimpleAdvisorScore
  ) {
    console.error(
      `advisor-eval: delta simple advisor_score ${report.comparison.aggregate_delta_simple_mean.advisor_score} ` +
        `< min ${args.minDeltaSimpleAdvisorScore}`
    );
    process.exit(1);
  }

  if (
    report.comparison &&
    typeof args.minDeltaWeightedAdvisorScore === "number" &&
    report.comparison.aggregate_delta_weighted_by_claims.advisor_score <
      args.minDeltaWeightedAdvisorScore
  ) {
    console.error(
      `advisor-eval: delta weighted advisor_score ${report.comparison.aggregate_delta_weighted_by_claims.advisor_score} ` +
        `< min ${args.minDeltaWeightedAdvisorScore}`
    );
    process.exit(1);
  }
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
