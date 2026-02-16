/**
 * Fetch video IDs and metadata from YouTube RSS feed.
 * Formats: channel_id=UCxxxx | playlist_id=PLxxxx
 */

const RSS_URL = "https://www.youtube.com/feeds/videos.xml";

export interface RssFetchRule {
  type: "rss";
  channel_id: string; // or resolve from channel_url via Piped
  channel_url?: string;
  last_n?: number;
}

export interface PlaylistFetchRule {
  type: "playlist";
  playlist_id: string;
  last_n?: number;
}

export interface PendingVideo {
  channel_id: string;
  channel_name: string;
  video_id: string;
  url: string;
  title: string;
  published: string;
}

export async function fetchFromRss(
  channelId: string,
  channelName: string,
  rule: RssFetchRule
): Promise<PendingVideo[]> {
  const { channel_id: rssChannelId, last_n = 15 } = rule;
  if (!rssChannelId || !rssChannelId.startsWith("UC")) {
    return [];
  }

  const url = `${RSS_URL}?channel_id=${rssChannelId}`;
  const res = await fetch(url);
  if (!res.ok) {
    throw new Error(`RSS fetch failed: ${res.status} ${res.statusText}`);
  }

  const xml = await res.text();
  const items = parseRssXml(xml);
  // Sort by published desc (newest first) - RSS order can vary
  items.sort((a, b) => {
    if (!a.published && !b.published) return 0;
    if (!a.published) return 1;
    if (!b.published) return -1;
    return b.published > a.published ? 1 : a.published > b.published ? -1 : 0;
  });
  const limit = Math.min(last_n, items.length);
  const sliced = items.slice(0, limit);

  return sliced.map((item) => ({
    channel_id: channelId,
    channel_name: channelName,
    video_id: item.videoId,
    url: `https://www.youtube.com/watch?v=${item.videoId}`,
    title: item.title,
    published: item.published || "",
  }));
}

export async function fetchFromPlaylist(
  channelId: string,
  channelName: string,
  rule: PlaylistFetchRule
): Promise<PendingVideo[]> {
  const { playlist_id, last_n } = rule;
  if (!playlist_id || playlist_id.length < 2) {
    return [];
  }

  const url = `${RSS_URL}?playlist_id=${playlist_id}`;
  const res = await fetch(url);
  if (!res.ok) {
    throw new Error(`Playlist RSS fetch failed: ${res.status} ${res.statusText}`);
  }

  const xml = await res.text();
  const items = parseRssXml(xml);
  items.sort((a, b) => {
    if (!a.published && !b.published) return 0;
    if (!a.published) return 1;
    if (!b.published) return -1;
    return b.published > a.published ? 1 : a.published > b.published ? -1 : 0;
  });
  const limit = last_n != null ? Math.min(last_n, items.length) : items.length;
  const sliced = items.slice(0, limit);

  return sliced.map((item) => ({
    channel_id: channelId,
    channel_name: channelName,
    video_id: item.videoId,
    url: `https://www.youtube.com/watch?v=${item.videoId}`,
    title: item.title,
    published: item.published || "",
  }));
}

interface RssItem {
  videoId: string;
  title: string;
  published: string;
}

function parseRssXml(xml: string): RssItem[] {
  const items: RssItem[] = [];
  const entryBlocks = xml.split(/<\/entry>/).filter((b) => b.includes("<entry"));
  for (const block of entryBlocks) {
    const videoIdMatch = block.match(/<yt:videoId>([a-zA-Z0-9_-]{11})<\/yt:videoId>/);
    const titleMatch = block.match(/<title[^>]*>([\s\S]*?)<\/title>/);
    const publishedMatch = block.match(/<published>([^<]+)<\/published>/);
    if (!videoIdMatch) continue;
    items.push({
      videoId: videoIdMatch[1],
      title: titleMatch ? decodeHtmlEntities(titleMatch[1].trim()) : "",
      published: publishedMatch ? publishedMatch[1].trim().slice(0, 10) : "",
    });
  }
  return items;
}

function decodeHtmlEntities(s: string): string {
  return s
    .replace(/&amp;/g, "&")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    .replace(/&apos;/g, "'");
}
