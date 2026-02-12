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

import { runChannelAnalyze } from "./channel-analyze.js";

const openaiKey = process.env.OPENAI_API_KEY;
if (!openaiKey) {
  console.error("Missing OPENAI_API_KEY in .env");
  process.exit(1);
}

async function main() {
  const args = process.argv.slice(2);
  const channelId = args.find((a) => a.startsWith("--channel="))?.split("=")[1];

  const results = await runChannelAnalyze(openaiKey!, { channelId });

  for (const r of results) {
    if (r.error) {
      console.error(`[${r.channel_id}] Failed:`, r.error);
    } else if (r.skipped) {
      console.log(`[${r.channel_id}] Skipped (cache valid)`);
    } else {
      console.log(`[${r.channel_id}] Channel analysis done`);
    }
  }
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
