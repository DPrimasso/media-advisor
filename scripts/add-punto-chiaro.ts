/**
 * Aggiunge alla lista Umberto Chiariello i video da @radiocrc2023
 * che contengono "Il punto chiaro" nel titolo.
 * Uso: npm run add-punto-chiaro
 */

import dotenv from "dotenv";
import { existsSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const __scriptDir = dirname(fileURLToPath(import.meta.url));
for (const base of [process.cwd(), resolve(__scriptDir, "..")]) {
  const p = resolve(base, ".env");
  if (existsSync(p)) {
    dotenv.config({ path: p });
    break;
  }
}

import { createTranscriptClient } from "../src/transcript-client";
import { readFileSync, writeFileSync } from "node:fs";

const CHANNEL = "@radiocrc2023";
const TITLE_MATCH = "il punto chiaro";
const LIST_PATH = resolve(__scriptDir, "..", "channels", "umberto-chiariello.json");

function extractVideoId(urlOrId: string): string {
  const m = urlOrId.match(/(?:v=|\/)([a-zA-Z0-9_-]{11})/);
  return m ? m[1] : urlOrId;
}

function getExistingIds(list: string[]): Set<string> {
  return new Set(list.map(extractVideoId));
}

async function main() {
  const apiKey = process.env.TRANSCRIPT_API_KEY;
  if (!apiKey) {
    console.error("Imposta TRANSCRIPT_API_KEY in .env");
    process.exit(1);
  }

  const listRaw = readFileSync(LIST_PATH, "utf-8");
  const list: string[] = JSON.parse(listRaw);
  const existingIds = getExistingIds(list);

  const client = createTranscriptClient(apiKey);
  console.log(`Scorro i video di ${CHANNEL} cercando "Il punto chiaro" nel titolo...`);

  const matching: { videoId: string; title: string }[] = [];
  let continuation: string | null = null;
  const MAX_MATCHES = 50;

  while (matching.length < MAX_MATCHES) {
    const res = continuation
      ? await client.getChannelVideos({ continuation })
      : await client.getChannelVideos({ channel: CHANNEL });

    for (const v of res.results) {
      if ((v.title || "").toLowerCase().includes(TITLE_MATCH)) {
        matching.push({ videoId: v.videoId, title: v.title });
        if (matching.length >= MAX_MATCHES) break;
      }
    }

    if (!res.continuation_token || !res.has_more || matching.length >= MAX_MATCHES) {
      break;
    }
    continuation = res.continuation_token;
  }

  const toAdd = matching.filter((v) => !existingIds.has(v.videoId));
  const skipped = matching.length - toAdd.length;

  if (matching.length === 0) {
    console.log(`Nessun video con "Il punto chiaro" nel titolo trovato.`);
    return;
  }

  if (toAdd.length === 0) {
    console.log(
      `Trovati ${matching.length} video con "Il punto chiaro", tutti già in lista (${skipped} duplicati saltati).`
    );
    return;
  }

  const newUrls = toAdd.map((v) => `https://www.youtube.com/watch?v=${v.videoId}`);
  const updated = [...list, ...newUrls];

  writeFileSync(LIST_PATH, JSON.stringify(updated, null, 2), "utf-8");

  console.log(`Aggiunti ${toAdd.length} video:`);
  toAdd.forEach((v) => console.log(`  - ${v.videoId} | ${v.title}`));
  if (skipped > 0) console.log(`${skipped} già presenti, saltati.`);
  console.log(`Lista aggiornata: ${LIST_PATH}`);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
