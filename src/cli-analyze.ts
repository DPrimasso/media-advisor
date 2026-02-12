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
// Fallback: dotenv loads .env from cwd (handles OneDrive/path quirks where existsSync may fail)
dotenv.config();

import { runBatch } from "./analyze-batch.js";

const openaiKey = process.env.OPENAI_API_KEY;
if (!openaiKey) {
  console.error("Missing OPENAI_API_KEY in .env");
  process.exit(1);
}

async function main() {
  const force = process.argv.includes("--force");

  const { analyzed, skipped, failed } = await runBatch(openaiKey!, {
    force,
    transcriptApiKey: process.env.TRANSCRIPT_API_KEY,
  });

  console.log(`Analyzed ${analyzed} videos. Skipped ${skipped} (already done). Failed ${failed}.`);
  console.log("Results in analysis/");
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
