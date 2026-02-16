/**
 * Full v2 pipeline: transcript → clean → segment → extract → aggregate → filter → output.
 */

import { existsSync } from "node:fs";
import { readFile, writeFile, mkdir } from "node:fs/promises";
import { join, resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import dotenv from "dotenv";
import OpenAI from "openai";

const __dirname = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(__dirname, "..", "..");

if (existsSync(join(ROOT, ".env"))) dotenv.config({ path: join(ROOT, ".env") });

import { cleanTranscript } from "./transcript-cleaner.js";
import { segment } from "./segmenter.js";
import { extractClaimsFromSegment } from "./extractor.js";
import { aggregateVideoClaims } from "./video-aggregator.js";
import { filterBySpecificity } from "./specificity-filter.js";
import { normalizeClaimEntities } from "./entity-normalizer.js";
import { buildChannelProfile } from "./channel-profiler.js";
import { detectInconsistencies } from "./inconsistency-detector.js";
import type { TranscriptResponse } from "../transcript-client.js";
import type { VideoAnalysis } from "../schema/claims.js";

const TRANSCRIPTS_DIR = join(ROOT, "transcripts");
const EVAL_DIR = join(ROOT, "eval");
const VIDEOS_SAMPLE = join(EVAL_DIR, "videos_sample.json");
const OUT_V2 = join(EVAL_DIR, "out_v2");

function sleep(ms: number): Promise<void> {
  return new Promise((r) => setTimeout(r, ms));
}

export async function runV2Pipeline(options?: { force?: boolean }) {
  const apiKey = process.env.OPENAI_API_KEY;
  if (!apiKey) throw new Error("OPENAI_API_KEY required");

  const openai = new OpenAI({ apiKey });
  const raw = await readFile(VIDEOS_SAMPLE, "utf-8");
  const videos = JSON.parse(raw) as Array<{
    video_id: string;
    channel_id: string;
    title: string;
    published_at: string;
  }>;

  const analyses: VideoAnalysis[] = [];
  const videoDates = new Map<string, string>();

  for (const v of videos) {
    const transcriptPath = join(TRANSCRIPTS_DIR, v.channel_id, `${v.video_id}.json`);
    if (!existsSync(transcriptPath)) continue;

    const outPath = join(OUT_V2, v.channel_id, `${v.video_id}.json`);
    if (!options?.force && existsSync(outPath)) {
      const existing = JSON.parse(await readFile(outPath, "utf-8")) as VideoAnalysis;
      analyses.push(existing);
      if (v.published_at) videoDates.set(v.video_id, v.published_at);
      continue;
    }

    try {
      const data = JSON.parse(await readFile(transcriptPath, "utf-8")) as TranscriptResponse;
      if (!data.transcript || (Array.isArray(data.transcript) && data.transcript.length === 0))
        continue;

      const clean = cleanTranscript(data);
      const segments = segment(clean, { mode: "topic_shift", max_segments: 12 });

      const allClaims: VideoAnalysis["claims"] = [];
      const allThemes: VideoAnalysis["themes"] = [];

      for (const seg of segments) {
        const { claims, themes } = await extractClaimsFromSegment(openai, {
          segment: seg,
          video_id: v.video_id,
          context: { title: v.title, published_at: v.published_at, opinionist: v.channel_id },
        });
        for (const c of claims) {
          allClaims.push(normalizeClaimEntities(c));
        }
        allThemes.push(...themes);
      }

      const filtered = filterBySpecificity(allClaims);
      const summaryShort =
        (data.metadata?.title ?? "Video") + " — " + (v.published_at ?? "").slice(0, 10);
      const analysis = aggregateVideoClaims(
        filtered,
        allThemes,
        v.video_id,
        summaryShort,
        { maxClaims: 12 }
      );

      await mkdir(join(OUT_V2, v.channel_id), { recursive: true });
      await writeFile(outPath, JSON.stringify(analysis, null, 2), "utf-8");
      analyses.push(analysis);
      if (v.published_at) videoDates.set(v.video_id, v.published_at);

      console.log(`[${v.video_id}] OK (${analysis.claims.length} claims)`);
    } catch (e) {
      console.error(`[${v.video_id}]`, (e as Error).message);
    }
    await sleep(500);
  }

  // Channel profiles + inconsistencies per channel
  const byChannel = new Map<string, VideoAnalysis[]>();
  for (const a of analyses) {
    const ch = videos.find((v) => v.video_id === a.video_id)?.channel_id ?? "unknown";
    if (!byChannel.has(ch)) byChannel.set(ch, []);
    byChannel.get(ch)!.push(a);
  }

  for (const [chId, chAnalyses] of byChannel) {
    const profile = buildChannelProfile(chId, chAnalyses);
    const claimsWithMeta = chAnalyses.flatMap((a) =>
      (a.claims ?? []).map((c) => ({
        ...c,
        published_at: videoDates.get(a.video_id),
      }))
    );
    const claimsMap = new Map<string, typeof claimsWithMeta>();
    claimsMap.set(chId, claimsWithMeta);
    const inconsistencies = detectInconsistencies(claimsMap, videoDates);

    await mkdir(join(OUT_V2, chId), { recursive: true });
    await writeFile(
      join(OUT_V2, chId, "_profile.json"),
      JSON.stringify(profile, null, 2),
      "utf-8"
    );
    await writeFile(
      join(OUT_V2, chId, "_inconsistencies.json"),
      JSON.stringify(inconsistencies, null, 2),
      "utf-8"
    );
  }

  return analyses;
}

const isMain = process.argv[1]?.replace(/\\/g, "/")?.includes("run-v2");
if (isMain) {
  runV2Pipeline({ force: process.argv.includes("--force") })
    .then(() => console.log("\nDone. Output:", OUT_V2))
    .catch((e) => {
      console.error(e);
      process.exit(1);
    });
}
