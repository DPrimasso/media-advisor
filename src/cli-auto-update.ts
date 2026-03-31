/**
 * Auto-update: fetch new videos from channels (fetch rules) → merge into lists → transcript + analyze.
 * Fully automated, no manual Inbox confirmation. Schedule with cron/Task Scheduler.
 */

import dotenv from "dotenv";
import { existsSync } from "node:fs";
import { resolve, dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { spawnSync } from "node:child_process";

const scriptDir = dirname(fileURLToPath(import.meta.url));
const root = resolve(scriptDir, "..");
for (const base of [process.cwd(), root]) {
  const p = resolve(base, ".env");
  if (existsSync(p)) {
    dotenv.config({ path: p });
    break;
  }
}
dotenv.config();

import { runFetchNewVideos } from "./fetch-new-videos.js";
import { runFromList } from "./run-from-list.js";
import { mergePendingIntoChannels } from "./merge-pending.js";

async function main() {
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

  const args = process.argv.slice(2);
  const channelId = args.find((a) => a.startsWith("--channel="))?.split("=")[1];

  console.log("[auto-update] Step 1: Fetching new videos from channels...");
  const pending = await runFetchNewVideos({
    channelsConfigPath: join(root, "channels", "channels.json"),
    transcriptApiKey: transcriptKey,
  });

  if (!pending.items?.length) {
    console.log("[auto-update] No new videos. Skipping merge and pipeline.");
    process.exit(0);
  }

  console.log(`[auto-update] Step 2: Merging ${pending.items.length} videos into channel lists...`);
  const added = mergePendingIntoChannels(root);
  console.log(`[auto-update] Added ${added} videos to lists`);

  console.log("[auto-update] Step 3: Running pipeline (transcript + analyze)...");
  const result = await runFromList(transcriptKey, openaiKey, {
    useV2: true,
    channelId,
  });

  for (const ch of result.channels) {
    console.log(
      `[${ch.id}] Transcripts: ${ch.transcriptsFetched} fetched | Analysis: ${ch.analyzed} done, ${ch.skipped} skipped, ${ch.failed} failed`
    );
  }

  const prep = spawnSync("node", ["web/scripts/prepare-public.js"], { cwd: root, stdio: "inherit" });
  if (prep.status !== 0) {
    console.error("prepare-public failed");
    process.exit(1);
  }
  console.log("[auto-update] Done. web/public/analysis/ updated.");
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
