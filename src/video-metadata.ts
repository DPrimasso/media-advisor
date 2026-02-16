/**
 * Fetch video published date (free, no API key).
 * Tries: Piped API → Invidious → yt-dlp (if installed).
 * https://docs.piped.video/docs/api-documentation/
 * https://docs.invidious.io/api/#get-videosid
 */

const PIPED_INSTANCES = (
  process.env.PIPED_BASE
    ? [process.env.PIPED_BASE]
    : [
        "https://pipedapi.kavin.rocks",
        "https://pipedapi.leptons.xyz",
        "https://pipedapi.nosebs.ru",
        "https://pipedapi.adminforge.de",
      ]
);

const INVIDIOUS_INSTANCES = (
  process.env.INVIDIOUS_BASE
    ? [process.env.INVIDIOUS_BASE]
    : ["https://inv.nadeko.net", "https://yewtu.be", "https://invidious.nerdvpn.de"]
);

async function tryPiped(base: string, videoId: string): Promise<string | null> {
  try {
    const res = await fetch(`${base}/streams/${videoId}`, {
      signal: AbortSignal.timeout(10000),
    });
    if (!res.ok) return null;
    const data = (await res.json()) as { uploadDate?: string };
    const d = data?.uploadDate;
    if (!d || typeof d !== "string") return null;
    // uploadDate: "2021-01-01" → ISO
    if (/^\d{4}-\d{2}-\d{2}$/.test(d)) return `${d}T12:00:00.000Z`;
    return null;
  } catch {
    return null;
  }
}

async function tryInvidious(base: string, videoId: string): Promise<string | null> {
  try {
    const res = await fetch(`${base}/api/v1/videos/${videoId}`, {
      signal: AbortSignal.timeout(10000),
    });
    if (!res.ok) return null;
    const data = (await res.json()) as { published?: number };
    const published = data?.published;
    if (typeof published !== "number" || published <= 0) return null;
    return new Date(published * 1000).toISOString();
  } catch {
    return null;
  }
}

async function tryYtDlp(videoId: string): Promise<string | null> {
  if (!/^[a-zA-Z0-9_-]{11}$/.test(videoId)) return null;
  const { exec } = await import("node:child_process");
  const { promisify } = await import("node:util");
  const execAsync = promisify(exec);
  const url = `https://www.youtube.com/watch?v=${videoId}`;
  const args = "--dump-json --no-download";
  // exec con shell usa il PATH di sistema (utile su Windows)
  const cmds = [
    `yt-dlp ${args} "${url}"`,
    `yt-dlp.exe ${args} "${url}"`,
    `python -m yt_dlp ${args} "${url}"`,
    `py -m yt_dlp ${args} "${url}"`,
  ];
  for (const cmd of cmds) {
    try {
      const { stdout } = await execAsync(cmd, { timeout: 20000, maxBuffer: 1024 * 1024 });
      const data = JSON.parse(stdout.trim()) as { upload_date?: string; timestamp?: number };
      if (data.upload_date && /^\d{8}$/.test(data.upload_date)) {
        const s = data.upload_date;
        return `${s.slice(0, 4)}-${s.slice(4, 6)}-${s.slice(6, 8)}T12:00:00.000Z`;
      }
      if (typeof data.timestamp === "number") {
        return new Date(data.timestamp * 1000).toISOString();
      }
    } catch {
      continue;
    }
  }
  return null;
}

/** Estrae data dal titolo. Supporta DD/MM/YY, DD/MM/YYYY, e DD/MM (anno da oggi). */
export function parseDateFromTitle(title: string): string | null {
  let d: string, month: string, year: string;

  const full = title.match(/(\d{1,2})\/(\d{1,2})\/(\d{2,4})(?:\D|$)/);
  if (full) {
    [, d, month, year] = full;
    year = year.length === 2 ? `20${year}` : year;
    return `${year}-${month.padStart(2, "0")}-${d.padStart(2, "0")}T12:00:00+00:00`;
  }

  const short = title.match(/(\d{1,2})\/(\d{1,2})(?:\D|$)/);
  if (short) {
    [, d, month] = short;
    const m = parseInt(month, 10);
    if (m < 1 || m > 12) return null;
    const now = new Date();
    let y = now.getFullYear();
    if (m > now.getMonth() + 1) y--;
    return `${y}-${month.padStart(2, "0")}-${d.padStart(2, "0")}T12:00:00+00:00`;
  }
  return null;
}

/** Data con metadata arricchibile. */
interface Enrichable {
  video_id: string;
  metadata?: { title?: string; author_url?: string; published_at?: string };
}

/**
 * Arricchisce data.metadata.published_at in-place.
 * Ordine: channel latest (via callback) → parseDateFromTitle → fetchVideoPublished.
 */
export async function enrichWithPublishedAt(
  data: Enrichable,
  opts?: {
    getChannelLatest?: (authorUrl: string) => Promise<{ videoId: string; published: string }[]>;
  }
): Promise<string | null> {
  if (data.metadata?.published_at) return data.metadata.published_at;

  let published: string | null = null;

  if (opts?.getChannelLatest && data.metadata?.author_url) {
    try {
      const videos = await opts.getChannelLatest(data.metadata.author_url);
      const found = videos.find((v) => v.videoId === data.video_id);
      if (found) published = found.published;
    } catch {
      // skip
    }
  }

  if (!published && data.metadata?.title) {
    published = parseDateFromTitle(data.metadata.title);
  }

  if (!published) {
    published = await fetchVideoPublished(data.video_id);
  }

  if (published) {
    data.metadata ??= {};
    data.metadata.published_at = published;
  }
  return published;
}

/** Returns ISO date string or null if fetch fails. */
export async function fetchVideoPublished(
  videoId: string
): Promise<string | null> {
  // yt-dlp first: connessione diretta a YouTube, più affidabile con firewall/VPN
  const yt = await tryYtDlp(videoId);
  if (yt) return yt;
  for (const base of PIPED_INSTANCES) {
    const r = await tryPiped(base, videoId);
    if (r) return r;
  }
  for (const base of INVIDIOUS_INSTANCES) {
    const r = await tryInvidious(base, videoId);
    if (r) return r;
  }
  return null;
}
