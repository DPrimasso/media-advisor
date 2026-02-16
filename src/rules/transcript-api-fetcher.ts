/**
 * Fetch video IDs from TranscriptAPI.com channel endpoints.
 * Uses getChannelLatest (15 free) or getChannelVideos (paginated).
 */

import {
  createTranscriptClient,
  type ChannelVideosResponse,
} from "../transcript-client.js";
import type { PendingVideo } from "./rss-fetcher.js";

export interface TranscriptApiFetchRule {
  type: "transcript_api";
  channel_url?: string;
  channel_id?: string;
  last_n?: number;
  title_contains?: string;
}

export async function fetchFromTranscriptApi(
  channelId: string,
  channelName: string,
  rule: TranscriptApiFetchRule,
  apiKey: string
): Promise<PendingVideo[]> {
  const channelInput = rule.channel_url || rule.channel_id;
  if (!channelInput) {
    return [];
  }

  const client = createTranscriptClient(apiKey);
  const lastN = rule.last_n ?? 15;
  const titleQuery = rule.title_contains?.trim();

  let results: Array<{ videoId: string; title: string; published?: string }>;

  if (titleQuery) {
    // getChannelSearch: up to 50 videos matching the query (uses API credits)
    const search = await client.getChannelSearch(channelInput, titleQuery, lastN);
    results = (search.results || []).slice(0, lastN).map((r) => ({
      videoId: r.videoId,
      title: r.title || "",
      published: "",
    }));
  } else if (lastN <= 15) {
    // getChannelLatest: max 15, free (no API credits)
    const latest = await client.getChannelLatest(channelInput);
    const raw = (latest.results || []).slice(0, lastN);
    results = raw.map((r) => ({
      videoId: r.videoId,
      title: r.title || "",
      published: (r as { published?: string }).published || "",
    }));
  } else {
    // getChannelVideos: paginated, ~100 per page (uses credits)
    const all: Array<{ videoId: string; title: string; published?: string }> = [];
    let continuation: string | null = null;
    while (all.length < lastN) {
      const page: ChannelVideosResponse = continuation
        ? await client.getChannelVideos({ continuation })
        : await client.getChannelVideos({ channel: channelInput });
      const items = (page.results || []).map((r) => ({
        videoId: r.videoId,
        title: r.title || "",
        published: "",
      }));
      all.push(...items);
      if (all.length >= lastN || !page.continuation_token || !page.has_more) break;
      continuation = page.continuation_token;
    }
    results = all.slice(0, lastN);
  }

  return results.map((r) => ({
    channel_id: channelId,
    channel_name: channelName,
    video_id: r.videoId,
    url: `https://www.youtube.com/watch?v=${r.videoId}`,
    title: r.title,
    published: r.published || "",
  }));
}
