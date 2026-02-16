/**
 * Resolve YouTube @handle or channel URL to channel_id (UC...).
 * Tries: Piped /user/:handle → YouTube page scrape.
 */

const PIPED_BASES = [
  "https://pipedapi.kavin.rocks",
  "https://pipedapi.leptons.xyz",
  "https://pipedapi.nosebs.ru",
  "https://pipedapi.adminforge.de",
];

function extractHandle(urlOrHandle: string): string | null {
  const trimmed = urlOrHandle.trim();
  const handleMatch = trimmed.match(/@([a-zA-Z0-9_-]+)/);
  if (handleMatch) return handleMatch[1];
  const urlMatch = trimmed.match(/youtube\.com\/@([a-zA-Z0-9_-]+)/);
  if (urlMatch) return urlMatch[1];
  if (/^[a-zA-Z0-9_-]+$/.test(trimmed) && !trimmed.startsWith("UC")) return trimmed;
  return null;
}

async function tryPiped(handle: string): Promise<string | null> {
  for (const base of PIPED_BASES) {
    try {
      const res = await fetch(`${base}/user/${handle}`, {
        signal: AbortSignal.timeout(8000),
      });
      if (!res.ok) continue;
      const data = (await res.json()) as { id?: string };
      if (data?.id && data.id.startsWith("UC")) return data.id;
    } catch {
      continue;
    }
  }
  return null;
}

/** Extract channel ID from YouTube @handle page. Uses channelMetadataRenderer.externalId (canonical). */
async function tryYouTubePage(handle: string): Promise<string | null> {
  try {
    const url = `https://www.youtube.com/@${handle}`;
    const res = await fetch(url, {
      redirect: "follow",
      headers: {
        "User-Agent":
          "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept-Language": "it-IT,it;q=0.9,en;q=0.8",
      },
      signal: AbortSignal.timeout(12000),
    });
    const finalUrl = res.url;
    const channelIdFromUrl = finalUrl.match(/youtube\.com\/channel\/(UC[a-zA-Z0-9_-]{22})/);
    if (channelIdFromUrl) return channelIdFromUrl[1];

    if (!res.ok) return null;
    const html = await res.text();

    const cid = extractChannelIdFromYtInitialData(html);
    if (cid) return cid;

    const canonMatch = html.match(
      /<link rel="canonical" href="https:\/\/www\.youtube\.com\/channel\/(UC[a-zA-Z0-9_-]{22})"/
    );
    if (canonMatch) return canonMatch[1];
    return null;
  } catch {
    return null;
  }
}

function extractChannelIdFromYtInitialData(html: string): string | null {
  const startMarker = "var ytInitialData = ";
  const idx = html.indexOf(startMarker);
  if (idx === -1) return null;
  let depth = 0;
  let inString = false;
  let escape = false;
  let start = idx + startMarker.length;
  for (let i = start; i < html.length; i++) {
    const c = html[i];
    if (escape) {
      escape = false;
      continue;
    }
    if (c === "\\" && inString) {
      escape = true;
      continue;
    }
    if (inString) {
      if (c === '"') inString = false;
      continue;
    }
    if (c === '"') {
      inString = true;
      continue;
    }
    if (c === "{") {
      depth++;
      continue;
    }
    if (c === "}") {
      depth--;
      if (depth === 0) {
        try {
          const json = JSON.parse(html.slice(start, i + 1)) as Record<string, unknown>;
          const meta = json?.metadata as Record<string, unknown> | undefined;
          const renderer = meta?.channelMetadataRenderer as Record<string, unknown> | undefined;
          const extId = renderer?.externalId ?? renderer?.external_id;
          if (typeof extId === "string" && extId.startsWith("UC")) return extId;
        } catch {
          /* ignore */
        }
        return null;
      }
      continue;
    }
  }
  return null;
}

export async function resolveChannelId(urlOrHandle: string): Promise<string | null> {
  const handle = extractHandle(urlOrHandle);
  if (!handle) return null;

  // YouTube page first: canonical source for exact @handle URL
  const fromYoutube = await tryYouTubePage(handle);
  if (fromYoutube) return fromYoutube;

  return tryPiped(handle);
}
