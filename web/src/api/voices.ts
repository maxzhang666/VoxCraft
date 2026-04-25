import { api } from "./client";
import type { Voice } from "@/types/api";

export interface VoiceExtractResponse {
  voice_id: string;
  speaker_name: string | null;
  provider_name: string;
  reference_audio_path: string;
  duration_seconds: number | null;
}

export interface ExtractVoiceParams {
  reference: File;
  speaker_name?: string;
  provider?: string;
}

export const listVoices = () =>
  api.get<{ voices: Voice[] }>("/tts/voices").then((r) => r.data.voices);

export const extractVoice = (params: ExtractVoiceParams) => {
  const fd = new FormData();
  fd.append("reference", params.reference);
  if (params.speaker_name) fd.append("speaker_name", params.speaker_name);
  if (params.provider) fd.append("provider", params.provider);
  return api
    .post<VoiceExtractResponse>("/tts/voices/extract", fd)
    .then((r) => r.data);
};

export const deleteVoice = (voiceId: string) =>
  api.delete(`/tts/voices/${encodeURIComponent(voiceId)}`);
