/**
 * Fetch new videos from channels according to fetch_rule config.
 * Outputs channels/pending.json with videos not yet in video_list.
 */

import { readFile, writeFile } from "node:fs/promises";
import { existsSync } from "node:fs";
import { join, resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { resolveChannelId } from "./channel-resolver.js";
import { fetchFromRss, fetchFromPlaylist } from "./rules/rss-fetcher.js";
import { fetchFromTranscriptApi } from "./rules/transcript-api-fetcher.js";
import type { PendingVideo } from "./rules/rss-fetcher.js";
import { DIRS } from "./paths.js";

const __dirname = dirname(fileURLToPath(import.meta.url));
const root = resolve(__dirname, "..");
const CHANNELS_DIR = join(root, DIRS.channels);

type FetchRule =
  | {
      type: "rss";
      channel_id?: string;
      channel_url?: string;
      last_n?: number;
      exclude_title_contains?: string;
      exclude_live?: boolean;
    }
  | {
      type: "playlist";
      playlist_id: string;
      last_n?: number;
      exclude_title_contains?: string;
      exclude_live?: boolean;
    }
  | {
      type: "transcript_api";
      channel_url?: string;
      channel_id?: string;
      last_n?: number;
      title_contains?: string;
      exclude_title_contains?: string;
      exclude_live?: boolean;
    }
  | { type: "manual" };

interface ChannelConfig {
  id: string;
  name: string;
  order: number;
  video_list: string;
  fetch_rule?: FetchRule;
}

interface ChannelsConfig {
  channels: ChannelConfig[];
}

export interface PendingResult {
  fetched_at: string;
  items: PendingVideo[];
}

function extractVideoId(urlOrId: string): string | null {
  const match = urlOrId.match(/(?:v=)([a-zA-Z0-9_-]{11})/);
  return match ? match[1] : urlOrId.length === 11 ? urlOrId : null;
}

async function getExistingVideoIds(channel: ChannelConfig): Promise<Set<string>> {
  const listPath = join(CHANNELS_DIR, channel.video_list);
  if (!existsSync(listPath)) return new Set();
  try {
    const raw = await readFile(listPath, "utf-8");
    const urls = JSON.parse(raw) as string[];
    if (!Array.isArray(urls)) return new Set();
    const ids = new Set<string>();
    for (const u of urls) {
      const id = extractVideoId(u);
      if (id) ids.add(id);
    }
    return ids;
  } catch {
    return new Set();
  }
}

export async function runFetchNewVideos(
  options: { channelsConfigPath?: string; transcriptApiKey?: string } = {}
): Promise<PendingResult> {
  const channelsPath =
    options.channelsConfigPath ?? join(CHANNELS_DIR, "channels.json");
  const transcriptApiKey = options.transcriptApiKey ?? process.env.TRANSCRIPT_API_KEY;

  const rawConfig = await readFile(channelsPath, "utf-8");
  const config = JSON.parse(rawConfig) as ChannelsConfig;
  if (!config.channels || !Array.isArray(config.channels)) {
    throw new Error("channels.json must have a 'channels' array");
  }

  const channels = config.channels
    .filter((c) => c.fetch_rule && c.fetch_rule.type !== "manual")
    .sort((a, b) => (a.order ?? 999) - (b.order ?? 999));

  const allNew: PendingVideo[] = [];

  for (const channel of channels) {
    const rule = channel.fetch_rule!;
    const existing = await getExistingVideoIds(channel);

    let fetched: PendingVideo[] = [];

    if (rule.type === "rss") {
      let channelIdResolved = rule.channel_id;
      if (!channelIdResolved?.startsWith("UC") && rule.channel_url) {
        channelIdResolved = (await resolveChannelId(rule.channel_url)) ?? undefined;
      }
      if (!channelIdResolved || !channelIdResolved.startsWith("UC")) {
        console.warn(
          `[${channel.id}] RSS rule: channel_id/channel_url missing or invalid, skip`
        );
        continue;
      }
      fetched = await fetchFromRss(channel.id, channel.name, {
        ...rule,
        channel_id: channelIdResolved,
      });
    } else if (rule.type === "playlist") {
      if (!rule.playlist_id) {
        console.warn(`[${channel.id}] Playlist rule: playlist_id missing, skip`);
        continue;
      }
      fetched = await fetchFromPlaylist(channel.id, channel.name, rule);
    } else if (rule.type === "transcript_api") {
      if (!transcriptApiKey) {
        console.warn(`[${channel.id}] TRANSCRIPT_API_KEY not set, skip transcript_api rule`);
        continue;
      }
      try {
        fetched = await fetchFromTranscriptApi(
          channel.id,
          channel.name,
          rule,
          transcriptApiKey
        );
      } catch (e) {
        const hasChannelUrl = "channel_url" in rule && rule.channel_url;
        if (hasChannelUrl) {
          const channelIdResolved = await resolveChannelId(rule.channel_url!);
          if (channelIdResolved?.startsWith("UC")) {
            console.warn(
              `[${channel.id}] TranscriptAPI failed (${(e as Error).message}), fallback to RSS`
            );
            fetched = await fetchFromRss(channel.id, channel.name, {
              type: "rss",
              channel_id: channelIdResolved,
              last_n: Math.min(rule.last_n ?? 15, 15),
            });
          } else {
            console.warn(`[${channel.id}] TranscriptAPI failed, skip:`, (e as Error).message);
            continue;
          }
        } else {
          console.warn(`[${channel.id}] TranscriptAPI failed, skip:`, (e as Error).message);
          continue;
        }
      }
    } else {
      continue;
    }

    if ("exclude_title_contains" in rule && rule.exclude_title_contains) {
      const excl = rule.exclude_title_contains.toLowerCase();
      fetched = fetched.filter((v) => !v.title.toLowerCase().includes(excl));
    }
    if ("exclude_live" in rule && rule.exclude_live) {
      const liveRe = /\b(live|livestream|streaming|diretta)\b|🔴/i;
      fetched = fetched.filter((v) => !liveRe.test(v.title));
    }

    const newVideos = fetched.filter((v) => !existing.has(v.video_id));
    allNew.push(...newVideos);
    console.log(`[${channel.id}] ${fetched.length} fetched, ${newVideos.length} new`);
  }

  const result: PendingResult = {
    fetched_at: new Date().toISOString(),
    items: allNew,
  };

  const pendingPath = join(CHANNELS_DIR, "pending.json");
  await writeFile(pendingPath, JSON.stringify(result, null, 2), "utf-8");
  console.log(`Wrote ${pendingPath} with ${allNew.length} pending videos`);

  return result;
}
