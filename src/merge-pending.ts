/**
 * Merge pending.json items into channel video lists, then clear pending.
 */

import { existsSync, readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { DIRS } from "./paths.js";

export function mergePendingIntoChannels(root: string): number {
  const channelsDir = join(root, DIRS.channels);
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
