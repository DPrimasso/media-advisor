import dotenv from "dotenv";
import { existsSync, readFileSync, writeFileSync } from "node:fs";
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

/** Merge pending into channel lists, then clear pending */
function mergePendingIntoChannels() {
  const channelsDir = join(root, "channels");
  const pendingPath = join(channelsDir, "pending.json");
  if (!existsSync(pendingPath)) return 0;
  const raw = readFileSync(pendingPath, "utf-8");
  const pending = JSON.parse(raw) as { items: { channel_id: string; video_id: string }[] };
  if (!pending.items?.length) return 0;

  const channelsPath = join(channelsDir, "channels.json");
  const config = JSON.parse(readFileSync(channelsPath, "utf-8")) as {
    channels: { id: string; video_list: string }[];
  };
  const channelMap = new Map(config.channels.map((c) => [c.id, c.video_list]));
  const toAppend = new Map<string, string[]>();

  for (const { channel_id, video_id } of pending.items) {
    const listFile = channelMap.get(channel_id);
    if (!listFile) continue;
    const listPath = join(channelsDir, listFile);
    if (!existsSync(listPath)) continue;
    if (!toAppend.has(listPath)) toAppend.set(listPath, []);
    toAppend.get(listPath)!.push(`https://www.youtube.com/watch?v=${video_id}`);
  }

  let added = 0;
  for (const [listPath, urls] of toAppend) {
    const existing = JSON.parse(readFileSync(listPath, "utf-8")) as string[];
    const existingIds = new Set(
      existing.map((u) => u.match(/v=([a-zA-Z0-9_-]{11})/)?.[1]).filter(Boolean)
    );
    const combined = [...existing];
    for (const url of urls) {
      const id = url.match(/v=([a-zA-Z0-9_-]{11})/)?.[1];
      if (id && !existingIds.has(id)) {
        combined.push(url);
        existingIds.add(id);
        added++;
      }
    }
    writeFileSync(listPath, JSON.stringify(combined, null, 2), "utf-8");
  }

  writeFileSync(pendingPath, JSON.stringify({ fetched_at: null, items: [] }, null, 2), "utf-8");
  return added;
}

function parseBooleanArg(
  args: string[],
  key: string
): boolean | undefined {
  const arg = args.find((a) => a.startsWith(`--${key}=`));
  if (!arg) return undefined;
  const raw = arg.split("=")[1]?.trim().toLowerCase();
  if (!raw) return undefined;
  if (["1", "true", "yes", "on"].includes(raw)) return true;
  if (["0", "false", "no", "off"].includes(raw)) return false;
  return undefined;
}

function parseNumberArg(args: string[], key: string): number | undefined {
  const arg = args.find((a) => a.startsWith(`--${key}=`));
  if (!arg) return undefined;
  const raw = arg.split("=")[1];
  if (!raw) return undefined;
  const n = Number(raw);
  if (!Number.isFinite(n)) return undefined;
  return Math.max(0, Math.min(100, Math.round(n)));
}

async function main() {
  const args = process.argv.slice(2);
  const forceTranscript = args.includes("--force-transcript");
  const forceAnalyze = args.includes("--force-analyze");
  const skipChannelAnalysis = args.includes("--skip-channel-analysis");
  const useV2 = !args.includes("--no-v2");
  const fromPending = args.includes("--from-pending");
  const channelId = args.find((a) => a.startsWith("--channel="))?.split("=")[1];
  const advisorEnabled = parseBooleanArg(args, "advisor");
  const advisorPredictionEnabled = parseBooleanArg(args, "advisor-predictions");
  const advisorMinFidelity = parseNumberArg(args, "advisor-min-fidelity");

  if (fromPending) {
    const added = mergePendingIntoChannels();
    console.log(`[from-pending] Added ${added} videos to channel lists, cleared pending`);
  }

  const result = await runFromList(transcriptKey!, openaiKey!, {
    forceTranscript,
    forceAnalyze,
    skipChannelAnalysis,
    useV2,
    channelId,
    advisorEnabled,
    advisorPredictionEnabled,
    advisorMinFidelity,
  });

  for (const ch of result.channels) {
    console.log(`[${ch.id}] Transcripts: ${ch.transcriptsFetched} fetched | Analysis: ${ch.analyzed} done, ${ch.skipped} skipped, ${ch.failed} failed`);
  }
  console.log("Results in transcripts/<channel_id>/ and analysis/<channel_id>/");

  const prep = spawnSync("node", ["web/scripts/prepare-public.js"], { cwd: root, stdio: "inherit" });
  if (prep.status !== 0) {
    console.error("prepare-public failed");
    process.exit(1);
  }
  console.log("→ web/public/analysis/ updated for frontend");
  process.exit(0);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
