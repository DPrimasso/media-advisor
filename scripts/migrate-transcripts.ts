/**
 * Migra i transcript dalla struttura flat (data/transcripts/*.json)
 * alla struttura per canale (data/transcripts/channel_id/*.json).
 * Esegui una sola volta: npm run migrate-transcripts
 */

import { readFileSync, readdirSync, mkdirSync, renameSync, existsSync } from "node:fs";
import { join, resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const root = resolve(__dirname, "..");
const channelsPath = join(root, "channels", "channels.json");
const transcriptsDir = join(root, "data", "transcripts");

function extractVideoId(url: string): string {
  const m = url.match(/(?:v=|\/)([a-zA-Z0-9_-]{11})/);
  return m ? m[1] : url;
}

function main() {
  if (!existsSync(transcriptsDir)) {
    console.log("Nessuna cartella data/transcripts/ da migrare.");
    return;
  }

  const config = JSON.parse(readFileSync(channelsPath, "utf-8"));
  const channels = config.channels as { id: string; video_list: string }[];

  const videoToChannel = new Map<string, string>();
  for (const ch of channels) {
    const listPath = join(root, "channels", ch.video_list);
    if (!existsSync(listPath)) continue;
    const urls = JSON.parse(readFileSync(listPath, "utf-8")) as string[];
    for (const url of urls) {
      const id = extractVideoId(url);
      if (!videoToChannel.has(id)) videoToChannel.set(id, ch.id);
    }
  }

  const files = readdirSync(transcriptsDir, { withFileTypes: true })
    .filter((e) => e.isFile() && e.name.endsWith(".json"))
    .map((e) => e.name);

  let migrated = 0;
  let skipped = 0;

  for (const file of files) {
    const videoId = file.replace(".json", "");
    const channelId = videoToChannel.get(videoId);

    if (!channelId) {
      console.log(`[skip] ${file} - nessun canale associato, sposto in _misc`);
      const miscDir = join(transcriptsDir, "_misc");
      mkdirSync(miscDir, { recursive: true });
      renameSync(join(transcriptsDir, file), join(miscDir, file));
      skipped++;
      continue;
    }

    const channelDir = join(transcriptsDir, channelId);
    mkdirSync(channelDir, { recursive: true });
    const dest = join(channelDir, file);
    if (existsSync(dest)) {
      console.log(`[skip] ${file} - già presente in ${channelId}/`);
      skipped++;
      continue;
    }
    renameSync(join(transcriptsDir, file), dest);
    migrated++;
  }

  console.log(`Migrati ${migrated} transcript, ${skipped} saltati.`);
  console.log("Struttura: data/transcripts/<channel_id>/<video_id>.json");
}

main();
