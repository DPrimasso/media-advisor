/**
 * Step 0 — Baseline: produce current pipeline output for eval videos.
 * Output saved to eval/out_baseline/{channel_id}/{video_id}.json
 */
import { existsSync } from "node:fs";
import { readFile, writeFile, mkdir } from "node:fs/promises";
import { join, resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import dotenv from "dotenv";

const __dirname = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(__dirname, "..");

// Load env
const envPath = join(ROOT, ".env");
if (existsSync(envPath)) dotenv.config({ path: envPath });

import { transcriptToPlainText } from "../src/save-transcript.js";
import { createOpenAIClient } from "../src/analyzer/openai-client.js";
import { enrichWithPublishedAt } from "../src/video-metadata.js";
import type { TranscriptResponse } from "../src/transcript-client.js";

const EVAL_DIR = join(ROOT, "eval");
const VIDEOS_SAMPLE = join(EVAL_DIR, "videos_sample.json");
const OUT_BASELINE = join(EVAL_DIR, "out_baseline");
const TRANSCRIPTS_DIR = join(ROOT, "data", "transcripts");

function sleep(ms: number): Promise<void> {
  return new Promise((r) => setTimeout(r, ms));
}

async function main() {
  const apiKey = process.env.OPENAI_API_KEY;
  if (!apiKey) {
    console.error("Missing OPENAI_API_KEY in .env");
    process.exit(1);
  }

  const raw = await readFile(VIDEOS_SAMPLE, "utf-8");
  const videos = JSON.parse(raw) as {
    video_id: string;
    channel_id: string;
    title: string;
    published_at: string;
  }[];

  const client = createOpenAIClient(apiKey);
  let done = 0;
  let skipped = 0;
  let failed = 0;

  for (const v of videos) {
    const transcriptPath = join(TRANSCRIPTS_DIR, v.channel_id, `${v.video_id}.json`);
    if (!existsSync(transcriptPath)) {
      console.warn(`[${v.video_id}] No transcript, skip`);
      skipped++;
      continue;
    }

    const outPath = join(OUT_BASELINE, v.channel_id, `${v.video_id}.json`);
    if (existsSync(outPath)) {
      console.log(`[${v.video_id}] Already exists, skip`);
      skipped++;
      continue;
    }

    try {
      const rawData = await readFile(transcriptPath, "utf-8");
      const data = JSON.parse(rawData) as TranscriptResponse;
      if (!data.transcript || (Array.isArray(data.transcript) && data.transcript.length === 0)) {
        console.warn(`[${v.video_id}] Empty transcript, skip`);
        skipped++;
        continue;
      }

      await enrichWithPublishedAt(data, {});

      const plainText = transcriptToPlainText(data);
      const metadata = data.metadata
        ? {
            title: data.metadata.title,
            author_name: data.metadata.author_name,
            published_at: data.metadata.published_at,
          }
        : undefined;

      const result = await client.analyzeTranscript(
        plainText,
        data.video_id,
        metadata
      );

      await mkdir(join(OUT_BASELINE, v.channel_id), { recursive: true });
      await writeFile(outPath, JSON.stringify(result, null, 2), "utf-8");
      done++;
      console.log(`[${v.video_id}] OK`);
    } catch (e) {
      console.error(`[${v.video_id}] Error:`, (e as Error).message);
      failed++;
    }

    await sleep(500);
  }

  console.log(`\nDone: ${done} | Skipped: ${skipped} | Failed: ${failed}`);
  console.log(`Output: ${OUT_BASELINE}`);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
