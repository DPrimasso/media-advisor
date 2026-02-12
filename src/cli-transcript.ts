import dotenv from "dotenv";
import { existsSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { createTranscriptClient } from "./transcript-client.js";
import { saveTranscript } from "./save-transcript.js";

const __dirname = dirname(fileURLToPath(import.meta.url));
const root = resolve(__dirname, "..");

for (const base of [process.cwd(), root]) {
  const p = resolve(base, ".env");
  if (existsSync(p)) {
    dotenv.config({ path: p });
    break;
  }
}

const apiKey = process.env.TRANSCRIPT_API_KEY;
if (!apiKey) {
  console.error("Missing TRANSCRIPT_API_KEY in .env");
  process.exit(1);
}

const client = createTranscriptClient(apiKey);

async function main() {
  const videoInput = process.argv[2];
  const channelOpt = process.argv.find((a) => a.startsWith("--channel="));
  const channelId = channelOpt?.split("=")[1];

  if (!videoInput) {
    console.log("Usage: npm run transcript <youtube-url-or-video-id> [--channel=channel_id]");
    console.log("Example: npm run transcript dQw4w9WgXcQ");
    console.log("Example: npm run transcript https://www.youtube.com/watch?v=xxx --channel=umberto-chiariello");
    process.exit(1);
  }

  try {
    const data = await client.getTranscript(videoInput, {
      format: "json",
      include_timestamp: true,
      send_metadata: true,
    });

    const outputDir = channelId
      ? resolve(root, "transcripts", channelId)
      : resolve(root, "transcripts", "_misc");
    const path = await saveTranscript(data, outputDir);
    console.log(`Saved transcript to ${path}`);
    if (data.metadata) {
      console.log(`Title: ${data.metadata.title}`);
      console.log(`Author: ${data.metadata.author_name}`);
    }
    console.log(
      `Segments: ${Array.isArray(data.transcript) ? data.transcript.length : "N/A"}`
    );
  } catch (e) {
    const err = e as { message?: string; statusCode?: number };
    console.error(`Error: ${err.message}`);
    if (err.statusCode === 402) console.error("→ Check your credits at https://transcriptapi.com/billing");
    if (err.statusCode === 404) console.error("→ Video not found or transcript unavailable");
    process.exit(1);
  }
}

main();
