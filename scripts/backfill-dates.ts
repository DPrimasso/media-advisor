/**
 * Aggiunge published_at alle analisi che non ce l'hanno.
 * Ordine: TranscriptAPI channel/latest (gratis) → yt-dlp → Piped → Invidious.
 * Richiede TRANSCRIPT_API_KEY e/o yt-dlp installato.
 * npm run backfill-dates
 */

import dotenv from "dotenv";
import { existsSync } from "node:fs";
import { join, resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const __scriptDir = dirname(fileURLToPath(import.meta.url));
for (const base of [process.cwd(), resolve(__scriptDir, "..")]) {
  const p = resolve(base, ".env");
  if (existsSync(p)) {
    dotenv.config({ path: p });
    break;
  }
}
dotenv.config();

import { readdir, readFile, writeFile } from "node:fs/promises";
import { createTranscriptClient } from "../src/transcript-client.js";
import { fetchVideoPublished, parseDateFromTitle } from "../src/video-metadata.js";

const root = resolve(__scriptDir, "..");
const analysisDir = join(root, "analysis");
const transcriptsDir = join(root, "transcripts");
const RATE_LIMIT_MS = 300;

function sleep(ms: number): Promise<void> {
  return new Promise((r) => setTimeout(r, ms));
}

async function getChannelLatestCache(
  channelId: string,
  transcriptApiKey: string
): Promise<Map<string, string>> {
  const map = new Map<string, string>();
  const transcriptPath = join(transcriptsDir, channelId);
  if (!existsSync(transcriptPath)) return map;
  const files = await readdir(transcriptPath);
  const jsonFiles = files.filter((f) => f.endsWith(".json"));
  let authorUrl: string | null = null;
  for (const f of jsonFiles) {
    const raw = await readFile(join(transcriptPath, f), "utf-8");
    const data = JSON.parse(raw) as { metadata?: { author_url?: string } };
    if (data.metadata?.author_url) {
      authorUrl = data.metadata.author_url;
      break;
    }
  }
  if (!authorUrl) return map;
  try {
    const client = createTranscriptClient(transcriptApiKey);
    const latest = await client.getChannelLatest(authorUrl);
    for (const v of latest.results) {
      map.set(v.videoId, v.published);
    }
  } catch {
    // ignore
  }
  return map;
}

async function main() {
  const channelFilter = process.argv.find((a) => a.startsWith("--channel="))?.split("=")[1];
  const transcriptKey = process.env.TRANSCRIPT_API_KEY;
  const channelLatestCache = new Map<string, Map<string, string>>();

  let channelDirs = (await readdir(analysisDir, { withFileTypes: true })).filter(
    (e) => e.isDirectory() && (!channelFilter || e.name === channelFilter)
  );
  if (channelFilter && channelDirs.length === 0) {
    console.error(`Canale non trovato: ${channelFilter}`);
    process.exit(1);
  }
  let updated = 0;
  let skipped = 0;
  let failed = 0;

  for (const ent of channelDirs) {
    if (transcriptKey) {
      const cache = await getChannelLatestCache(ent.name, transcriptKey);
      channelLatestCache.set(ent.name, cache);
      await sleep(200);
    }
  }

  for (const ent of channelDirs) {
    const channelPath = join(analysisDir, ent.name);
    const files = await readdir(channelPath);
    const jsonFiles = files.filter((f) => f.endsWith(".json") && f !== "_channel.json");
    const transcriptCache = channelLatestCache.get(ent.name);

    for (const f of jsonFiles) {
      const videoId = f.replace(".json", "");
      const filepath = join(channelPath, f);

      const raw = await readFile(filepath, "utf-8");
      const data = JSON.parse(raw) as {
        metadata?: { published_at?: string; title?: string };
        video_id?: string;
      };
      const vid = data.video_id ?? videoId;

      if (data.metadata?.published_at) {
        skipped++;
        continue;
      }

      let published: string | null = transcriptCache?.get(vid) ?? null;
      if (!published && data.metadata?.title) {
        published = parseDateFromTitle(data.metadata.title);
      }
      if (!published) {
        published = await fetchVideoPublished(vid);
        await sleep(RATE_LIMIT_MS);
      }

      if (!published) {
        console.error(`[${ent.name}/${vid}] Data non trovata`);
        failed++;
        continue;
      }

      data.metadata ??= {};
      data.metadata.published_at = published;
      await writeFile(filepath, JSON.stringify(data, null, 2), "utf-8");
      updated++;
      console.log(`[${ent.name}/${vid}] ${published}`);
    }
  }

  console.log(`\nAggiornati: ${updated}, già ok: ${skipped}, falliti: ${failed}`);
  if (failed > 0) {
    console.log("\nSe tutti falliscono:");
    console.log("  - Installa yt-dlp: pip install yt-dlp, oppure winget install yt-dlp");
    console.log("  - Verifica TRANSCRIPT_API_KEY in .env per i 15 video più recenti per canale");
    console.log("  - Piped/Invidious potrebbero essere bloccati da firewall/VPN");
  }
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
