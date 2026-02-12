import { writeFile, mkdir } from "node:fs/promises";
import { join } from "node:path";
import type { TranscriptResponse } from "./transcript-client.js";

/**
 * Save transcript to disk as JSON. Returns the file path.
 * @param data - Transcript data from API
 * @param outputDir - Directory (e.g. transcripts/channel_id or transcripts/_misc)
 */
export async function saveTranscript(
  data: TranscriptResponse,
  outputDir: string
): Promise<string> {
  await mkdir(outputDir, { recursive: true });

  const filename = `${data.video_id}.json`;
  const filepath = join(outputDir, filename);

  await writeFile(filepath, JSON.stringify(data, null, 2), "utf-8");
  return filepath;
}

/**
 * Extract plain text from transcript (for embedding, summarization, etc.)
 */
export function transcriptToPlainText(data: TranscriptResponse): string {
  if (typeof data.transcript === "string") {
    return data.transcript;
  }
  return data.transcript.map((s) => s.text).join("\n");
}
