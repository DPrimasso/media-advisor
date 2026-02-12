import OpenAI from "openai";
import type { AnalysisResult } from "./types.js";
import { getAnalysisPrompt } from "./prompts.js";

const ANALYSIS_SCHEMA = {
  type: "object" as const,
  properties: {
    summary: { type: "string", description: "Riassunto sintetico dei punti principali del video" },
    topics: {
      type: "array",
      description: "Temi trattati nel video",
      items: {
        type: "object",
        properties: {
          name: { type: "string", description: "Nome del tema" },
          relevance: {
            type: "string",
            enum: ["high", "medium", "low"],
            description: "Rilevanza del tema nel video",
          },
        },
        required: ["name", "relevance"],
        additionalProperties: false,
      },
    },
    claims: {
      type: "array",
      description: "Posizioni/opinioni chiave espresse dall'autore",
      items: {
        type: "object",
        properties: {
          topic: { type: "string", description: "Il tema del claim" },
          subject: { type: "string", description: "Entità citata (squadra, persona, istituzione)" },
          position: { type: "string", description: "Cosa sostiene" },
          polarity: {
            type: "string",
            enum: ["positive", "negative", "neutral"],
            description: "Valutazione espressa",
          },
        },
        required: ["topic", "subject", "position", "polarity"],
        additionalProperties: false,
      },
    },
  },
  required: ["summary", "topics", "claims"],
  additionalProperties: false,
};

export function createOpenAIClient(apiKey: string) {
  const openai = new OpenAI({ apiKey });

  return {
    async analyzeTranscript(
      plainText: string,
      videoId: string,
      metadata?: { title?: string; author_name?: string; published_at?: string }
    ): Promise<AnalysisResult> {
      const { system, user } = getAnalysisPrompt(plainText, metadata);

      const completion = await openai.chat.completions.create({
        model: "gpt-4o-mini",
        messages: [
          { role: "system", content: system },
          { role: "user", content: user },
        ],
        response_format: {
          type: "json_schema",
          json_schema: {
            name: "analysis_result",
            strict: true,
            schema: ANALYSIS_SCHEMA,
          },
        },
      });

      const content = completion.choices[0]?.message?.content;
      if (!content) {
        throw new Error("Empty response from OpenAI");
      }

      const parsed = JSON.parse(content) as {
        summary: string;
        topics: { name: string; relevance: "high" | "medium" | "low" }[];
        claims?: { topic: string; subject?: string; position: string; polarity?: "positive" | "negative" | "neutral" }[];
      };

      return {
        video_id: videoId,
        analyzed_at: new Date().toISOString(),
        metadata: metadata
          ? {
              title: metadata.title,
              author_name: metadata.author_name,
              published_at: metadata.published_at,
            }
          : undefined,
        summary: parsed.summary,
        topics: parsed.topics,
        claims: parsed.claims ?? [],
      };
    },
  };
}
