/**
 * Paths and directory structure for media-advisor
 */

import { join } from "node:path";

export const DIRS = {
  transcripts: "transcripts",
  analysis: "analysis",
  channels: "channels",
} as const;

/** transcripts/channel_id/video_id.json */
export function transcriptPath(
  root: string,
  channelId: string,
  videoId: string
): string {
  return join(root, DIRS.transcripts, channelId, `${videoId}.json`);
}

/** analysis/channel_id/video_id.json */
export function analysisPath(
  root: string,
  channelId: string,
  videoId: string
): string {
  return join(root, DIRS.analysis, channelId, `${videoId}.json`);
}

/** transcripts/_misc for one-off fetches without channel context */
export function miscTranscriptPath(root: string, videoId: string): string {
  return join(root, DIRS.transcripts, "_misc", `${videoId}.json`);
}
