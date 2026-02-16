/**
 * Mini API server: pending videos, confirm, fetch-now.
 * Serves static from web/dist when built.
 */

import express from "express";
import { readFile, writeFile } from "node:fs/promises";
import { existsSync } from "node:fs";
import { join, resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { spawn } from "node:child_process";

const __dirname = dirname(fileURLToPath(import.meta.url));
const root = resolve(__dirname, "..");
const channelsDir = join(root, "channels");
const pendingPath = join(channelsDir, "pending.json");

const app = express();
app.use(express.json());

// CORS for dev (Vite on different port)
app.use((_req, res, next) => {
  res.setHeader("Access-Control-Allow-Origin", "*");
  res.setHeader("Access-Control-Allow-Methods", "GET, POST, OPTIONS");
  res.setHeader("Access-Control-Allow-Headers", "Content-Type");
  if (_req.method === "OPTIONS") return res.sendStatus(204);
  next();
});

/** GET /api/pending - current pending videos */
app.get("/api/pending", async (_req, res) => {
  try {
    if (!existsSync(pendingPath)) {
      return res.json({ fetched_at: null, items: [] });
    }
    const raw = await readFile(pendingPath, "utf-8");
    const data = JSON.parse(raw);
    res.json(data);
  } catch (e) {
    res.status(500).json({ error: (e as Error).message });
  }
});

/** POST /api/confirm - append selected videos to channel lists, optional trigger pipeline */
app.post("/api/confirm", async (req, res) => {
  try {
    const body = req.body as {
      items?: { channel_id: string; video_id: string }[];
      channel_id?: string;
      video_ids?: string[];
      trigger_pipeline?: boolean;
    };

    let items: { channel_id: string; video_id: string }[] = [];
    if (body.items && Array.isArray(body.items)) {
      items = body.items;
    } else if (body.channel_id && Array.isArray(body.video_ids)) {
      items = body.video_ids.map((video_id) => ({
        channel_id: body.channel_id!,
        video_id,
      }));
    }

    if (items.length === 0) {
      return res.status(400).json({ error: "No items to confirm" });
    }

    const channelsConfigPath = join(channelsDir, "channels.json");
    const rawConfig = await readFile(channelsConfigPath, "utf-8");
    const config = JSON.parse(rawConfig) as {
      channels: { id: string; video_list: string }[];
    };
    const channelMap = new Map(
      config.channels.map((c) => [c.id, c.video_list])
    );

    const toAppend = new Map<string, string[]>();
    for (const { channel_id, video_id } of items) {
      const listFile = channelMap.get(channel_id);
      if (!listFile) continue;
      const listPath = join(channelsDir, listFile);
      if (!existsSync(listPath)) continue;
      if (!toAppend.has(listPath)) toAppend.set(listPath, []);
      toAppend.get(listPath)!.push(`https://www.youtube.com/watch?v=${video_id}`);
    }

    for (const [listPath, urls] of toAppend) {
      const raw = await readFile(listPath, "utf-8");
      const existing = JSON.parse(raw) as string[];
      const combined = [...existing];
      const existingIds = new Set(
        existing.map((u) => u.match(/v=([a-zA-Z0-9_-]{11})/)?.[1]).filter(Boolean)
      );
      for (const url of urls) {
        const id = url.match(/v=([a-zA-Z0-9_-]{11})/)?.[1];
        if (id && !existingIds.has(id)) {
          combined.push(url);
          existingIds.add(id);
        }
      }
      await writeFile(listPath, JSON.stringify(combined, null, 2), "utf-8");
    }

    // Remove confirmed from pending
    const confirmedIds = new Set(items.map((i) => `${i.channel_id}:${i.video_id}`));
    if (existsSync(pendingPath)) {
      const raw = await readFile(pendingPath, "utf-8");
      const pending = JSON.parse(raw) as { fetched_at: string; items: { channel_id: string; video_id: string }[] };
      pending.items = pending.items.filter(
        (i) => !confirmedIds.has(`${i.channel_id}:${i.video_id}`)
      );
      await writeFile(pendingPath, JSON.stringify(pending, null, 2), "utf-8");
    }

    if (body.trigger_pipeline) {
      spawn("npx", ["tsx", "src/cli-from-list.ts"], {
        cwd: root,
        detached: true,
        stdio: "ignore",
      }).unref();
    }

    res.json({ ok: true, confirmed: items.length });
  } catch (e) {
    res.status(500).json({ error: (e as Error).message });
  }
});

/** POST /api/fetch-now - run fetch-new-videos, return updated pending */
app.post("/api/fetch-now", async (_req, res) => {
  try {
    const { runFetchNewVideos } = await import("../src/fetch-new-videos.js");
    const result = await runFetchNewVideos({
      channelsConfigPath: join(channelsDir, "channels.json"),
      transcriptApiKey: process.env.TRANSCRIPT_API_KEY,
    });
    res.json(result);
  } catch (e) {
    res.status(500).json({ error: (e as Error).message });
  }
});

// Static files + SPA fallback (for production, when web/dist exists)
const webDist = join(root, "web", "dist");
const indexHtml = join(webDist, "index.html");
if (existsSync(webDist) && existsSync(indexHtml)) {
  app.use(express.static(webDist));
  app.get("*", (_req, res) => {
    res.sendFile(indexHtml);
  });
}

const PORT = process.env.PORT ?? 3001;
app.listen(PORT, () => {
  console.log(`API server http://localhost:${PORT}`);
  console.log(`  GET  /api/pending`);
  console.log(`  POST /api/confirm`);
  console.log(`  POST /api/fetch-now`);
});
