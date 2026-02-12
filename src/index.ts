/**
 * Media Advisor - Transcript API integration
 * Export the client and helpers for programmatic use
 */

export {
  createTranscriptClient,
  type TranscriptResponse,
  type TranscriptSegment,
  type TranscriptOptions,
  type VideoMetadata,
  TranscriptAPIError,
} from "./transcript-client.js";

export { saveTranscript, transcriptToPlainText } from "./save-transcript.js";
