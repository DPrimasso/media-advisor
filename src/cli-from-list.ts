import dotenv from "dotenv";
import { existsSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const scriptDir = dirname(fileURLToPath(import.meta.url));
for (const base of [process.cwd(), resolve(scriptDir, "..")]) {
  const p = resolve(base, ".env");
  if (existsSync(p)) {
    dotenv.config({ path: p });
    break;
  }
}
dotenv.config();

import { runFromList } from "./run-from-list.js";

const transcriptKey = process.env.TRANSCRIPT_API_KEY;
const openaiKey = process.env.OPENAI_API_KEY;

if (!transcriptKey) {
  console.error("Missing TRANSCRIPT_API_KEY in .env");
  process.exit(1);
}
if (!openaiKey) {
  console.error("Missing OPENAI_API_KEY in .env");
  process.exit(1);
}

async function main() {
  const args = process.argv.slice(2);
  const forceTranscript = args.includes("--force-transcript");
  const forceAnalyze = args.includes("--force-analyze");
  const skipChannelAnalysis = args.includes("--skip-channel-analysis");
  const channelId = args.find((a) => a.startsWith("--channel="))?.split("=")[1];

  const result = await runFromList(transcriptKey!, openaiKey!, {
    forceTranscript,
    forceAnalyze,
    skipChannelAnalysis,
    channelId,
  });

  for (const ch of result.channels) {
    console.log(`[${ch.id}] Transcripts: ${ch.transcriptsFetched} fetched | Analysis: ${ch.analyzed} done, ${ch.skipped} skipped, ${ch.failed} failed`);
  }
  console.log("Results in transcripts/<channel_id>/ and analysis/<channel_id>/");
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
