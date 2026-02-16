/**
 * TranscriptAPI.com client - fetch YouTube video transcripts
 * https://transcriptapi.com/docs/api/
 */

const BASE_URL = "https://transcriptapi.com/api/v2";
const RETRYABLE_CODES = [408, 429, 503];

export interface TranscriptSegment {
  text: string;
  start?: number;
  duration?: number;
}

export interface VideoMetadata {
  title: string;
  author_name: string;
  author_url: string;
  thumbnail_url: string;
  /** Added locally when fetching published date (Transcript API does not return it) */
  published_at?: string;
}

export interface TranscriptResponse {
  video_id: string;
  language: string;
  transcript: TranscriptSegment[] | string;
  metadata?: VideoMetadata;
}

export interface TranscriptOptions {
  format?: "json" | "text";
  include_timestamp?: boolean;
  send_metadata?: boolean;
}

export class TranscriptAPIError extends Error {
  constructor(
    message: string,
    public statusCode?: number,
    public code?: string,
    public actionUrl?: string
  ) {
    super(message);
    this.name = "TranscriptAPIError";
  }
}

async function sleep(ms: number): Promise<void> {
  return new Promise((r) => setTimeout(r, ms));
}

async function fetchWithRetry(
  url: string,
  options: RequestInit,
  maxRetries = 3
): Promise<Response> {
  for (let i = 0; i < maxRetries; i++) {
    const response = await fetch(url, options);

    if (!RETRYABLE_CODES.includes(response.status)) {
      return response;
    }

    if (i === maxRetries - 1) return response;

    const retryAfter =
      Number(response.headers.get("Retry-After")) || Math.pow(2, i);
    await sleep(retryAfter * 1000);
  }
  throw new TranscriptAPIError("Max retries exceeded");
}

export function createTranscriptClient(apiKey: string) {
  const headers: Record<string, string> = {
    Authorization: `Bearer ${apiKey}`,
  };

  return {
    async getTranscript(
      videoUrlOrId: string,
      options: TranscriptOptions = {}
    ): Promise<TranscriptResponse> {
      const params = new URLSearchParams({
        video_url: videoUrlOrId,
        format: options.format ?? "json",
        include_timestamp: String(options.include_timestamp ?? true),
        send_metadata: String(options.send_metadata ?? true),
      });

      const response = await fetchWithRetry(
        `${BASE_URL}/youtube/transcript?${params}`,
        { headers }
      );

      if (!response.ok) {
        const err = (await response.json().catch(() => ({}))) as {
          detail?: string | { message?: string; action_url?: string };
          code?: string;
        };
        const msg =
          typeof err.detail === "object"
            ? err.detail.message ?? JSON.stringify(err.detail)
            : err.detail ?? response.statusText;
        const actionUrl =
          typeof err.detail === "object" ? err.detail.action_url : undefined;

        throw new TranscriptAPIError(msg, response.status, err.code, actionUrl);
      }

      return response.json() as Promise<TranscriptResponse>;
    },

    /** List channel videos, paginated (~100 per page). */
    async getChannelVideos(opts: {
      channel?: string;
      continuation?: string;
    }): Promise<ChannelVideosResponse> {
      const { channel, continuation } = opts;
      if (!channel && !continuation) {
        throw new TranscriptAPIError("Provide channel or continuation");
      }
      const params = new URLSearchParams(
        channel ? { channel } : { continuation: continuation! }
      );
      const response = await fetchWithRetry(
        `${BASE_URL}/youtube/channel/videos?${params}`,
        { headers }
      );

      if (!response.ok) {
        const err = (await response.json().catch(() => ({}))) as {
          detail?: string | { message?: string };
        };
        const msg =
          typeof err.detail === "object"
            ? err.detail.message ?? JSON.stringify(err.detail)
            : err.detail ?? response.statusText;
        throw new TranscriptAPIError(msg, response.status);
      }

      return response.json() as Promise<ChannelVideosResponse>;
    },

    /** Search for videos within a channel. Max 50 results. */
    async getChannelSearch(
      channelInput: string,
      query: string,
      limit = 50
    ): Promise<ChannelSearchResponse> {
      const params = new URLSearchParams({
        channel: channelInput,
        q: query,
        limit: String(Math.min(50, limit)),
      });
      const response = await fetchWithRetry(
        `${BASE_URL}/youtube/channel/search?${params}`,
        { headers }
      );

      if (!response.ok) {
        const err = (await response.json().catch(() => ({}))) as {
          detail?: string | { message?: string };
        };
        const msg =
          typeof err.detail === "object"
            ? err.detail.message ?? JSON.stringify(err.detail)
            : err.detail ?? response.statusText;
        throw new TranscriptAPIError(msg, response.status);
      }

      return response.json() as Promise<ChannelSearchResponse>;
    },

    /** Get latest 15 videos from a channel (FREE, no credits). Returns published dates. */
    async getChannelLatest(channelInput: string): Promise<ChannelLatestResponse> {
      const params = new URLSearchParams({ channel: channelInput });
      const response = await fetchWithRetry(
        `${BASE_URL}/youtube/channel/latest?${params}`,
        { headers }
      );

      if (!response.ok) {
        const err = (await response.json().catch(() => ({}))) as {
          detail?: string | { message?: string };
        };
        const msg =
          typeof err.detail === "object"
            ? err.detail.message ?? JSON.stringify(err.detail)
            : err.detail ?? response.statusText;
        throw new TranscriptAPIError(msg, response.status);
      }

      return response.json() as Promise<ChannelLatestResponse>;
    },
  };
}

export interface ChannelLatestVideo {
  videoId: string;
  title: string;
  published: string;
  [key: string]: unknown;
}

export interface ChannelLatestResponse {
  results: ChannelLatestVideo[];
  result_count: number;
}

export interface ChannelVideosVideo {
  videoId: string;
  title: string;
  [key: string]: unknown;
}

export interface ChannelVideosResponse {
  results: ChannelVideosVideo[];
  continuation_token?: string | null;
  has_more?: boolean;
}

export interface ChannelSearchVideo {
  type: string;
  videoId: string;
  title: string;
  channelId: string;
  channelTitle: string;
  [key: string]: unknown;
}

export interface ChannelSearchResponse {
  results: ChannelSearchVideo[];
  result_count: number;
}
