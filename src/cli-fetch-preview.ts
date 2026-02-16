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

import { runFetchNewVideos } from "./fetch-new-videos.js";

async function main() {
  await runFetchNewVideos({
    transcriptApiKey: process.env.TRANSCRIPT_API_KEY,
  });
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
