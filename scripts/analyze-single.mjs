/**
 * Run v2 analysis on a single video, forcing re-analysis.
 * Usage: node scripts/analyze-single.mjs <channelId> <videoId>
 */
import { readFile, writeFile } from "node:fs/promises";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { existsSync } from "node:fs";
import dotenv from "dotenv";

const __dirname = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(__dirname, "..");

// Load .env
for (const base of [process.cwd(), ROOT]) {
  const p = resolve(base, ".env");
  if (existsSync(p)) { dotenv.config({ path: p }); break; }
}

const [,, channelId, videoId] = process.argv;
if (!channelId || !videoId) {
  console.error("Usage: node scripts/analyze-single.mjs <channelId> <videoId>");
  process.exit(1);
}

const { analyzeVideoV2 } = await import("../dist/analyze-v2.js");
import OpenAI from "openai";

const openai = new OpenAI({ apiKey: process.env.OPENAI_API_KEY });

const transcriptFile = resolve(ROOT, "transcripts", channelId, `${videoId}.json`);
if (!existsSync(transcriptFile)) {
  console.error(`Transcript not found: ${transcriptFile}`);
  process.exit(1);
}

console.log(`Analyzing ${videoId} (channel: ${channelId})...`);
const data = JSON.parse(await readFile(transcriptFile, "utf-8"));

const result = await analyzeVideoV2({
  openai,
  data,
  videoId,
  channelId,
  metadata: {
    title: data.metadata?.title,
    published_at: data.metadata?.published_at,
  },
});

const outFile = resolve(ROOT, "analysis", channelId, `${videoId}.json`);
await writeFile(outFile, JSON.stringify(result, null, 2), "utf-8");
console.log(`\nSalvato in: ${outFile}`);
console.log(`\nSummary:\n${result.summary}`);
console.log(`\nTopics (${result.topics?.length ?? 0}):`);
for (const t of result.topics ?? []) {
  console.log(`  [${t.relevance}] ${t.name}`);
}
console.log(`\nClaims (${result.claims?.length ?? 0}):`);
for (const c of result.claims ?? []) {
  console.log(`  [${c.dimension ?? c.topic}/${c.stance ?? c.polarity}] ${c.claim_text ?? c.position}`);
}
