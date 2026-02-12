import OpenAI from "openai";
import {
  THEMES_SYSTEM,
  getThemesPrompt,
  INCONSISTENCY_SYSTEM,
  getInconsistencyPrompt,
  BIAS_SYSTEM,
  getBiasPrompt,
} from "./channel-prompts.js";

const THEMES_SCHEMA = {
  type: "object" as const,
  properties: {
    summary: { type: "string", description: "Riepilogo sintetico dei temi principali" },
    main_topics: {
      type: "array",
      items: { type: "string" },
    },
  },
  required: ["summary", "main_topics"],
  additionalProperties: false,
};

const INCONSISTENCY_SCHEMA = {
  type: "object" as const,
  properties: {
    has_contradiction: { type: "boolean" },
    description: { type: "string" },
  },
  required: ["has_contradiction", "description"],
  additionalProperties: false,
};

const BIAS_SCHEMA = {
  type: "object" as const,
  properties: {
    summary: { type: "string" },
    patterns: {
      type: "array",
      items: {
        type: "object",
        properties: {
          subject: { type: "string" },
          description: { type: "string" },
        },
        required: ["subject", "description"],
        additionalProperties: false,
      },
    },
  },
  required: ["summary", "patterns"],
  additionalProperties: false,
};

export interface ChannelThemes {
  summary: string;
  main_topics: string[];
}

export interface ChannelInconsistency {
  topic: string;
  description: string;
  videos: string[];
}

export interface ChannelBias {
  summary: string;
  patterns: { subject: string; description: string }[];
}

export function createChannelOpenAIClient(apiKey: string) {
  const openai = new OpenAI({ apiKey });

  return {
    async analyzeThemes(
      items: { video_id: string; summary: string; topics: { name: string; relevance: string }[] }[]
    ): Promise<ChannelThemes> {
      const completion = await openai.chat.completions.create({
        model: "gpt-4o-mini",
        messages: [
          { role: "system", content: THEMES_SYSTEM },
          { role: "user", content: getThemesPrompt(items) },
        ],
        response_format: {
          type: "json_schema",
          json_schema: {
            name: "themes_result",
            strict: true,
            schema: THEMES_SCHEMA,
          },
        },
      });
      const content = completion.choices[0]?.message?.content;
      if (!content) throw new Error("Empty themes response");
      return JSON.parse(content) as ChannelThemes;
    },

    async checkInconsistency(
      topic: string,
      claims: { video_id: string; position: string }[]
    ): Promise<{ has_contradiction: boolean; description?: string }> {
      const completion = await openai.chat.completions.create({
        model: "gpt-4o-mini",
        messages: [
          { role: "system", content: INCONSISTENCY_SYSTEM },
          { role: "user", content: getInconsistencyPrompt(topic, claims) },
        ],
        response_format: {
          type: "json_schema",
          json_schema: {
            name: "inconsistency_result",
            strict: true,
            schema: INCONSISTENCY_SCHEMA,
          },
        },
      });
      const content = completion.choices[0]?.message?.content;
      if (!content) throw new Error("Empty inconsistency response");
      return JSON.parse(content);
    },

    async analyzeBias(
      claimsBySubject: Record<string, { position: string; polarity?: string }[]>
    ): Promise<ChannelBias> {
      const completion = await openai.chat.completions.create({
        model: "gpt-4o-mini",
        messages: [
          { role: "system", content: BIAS_SYSTEM },
          { role: "user", content: getBiasPrompt(claimsBySubject) },
        ],
        response_format: {
          type: "json_schema",
          json_schema: {
            name: "bias_result",
            strict: true,
            schema: BIAS_SCHEMA,
          },
        },
      });
      const content = completion.choices[0]?.message?.content;
      if (!content) throw new Error("Empty bias response");
      return JSON.parse(content) as ChannelBias;
    },
  };
}
