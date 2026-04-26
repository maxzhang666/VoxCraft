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
  /** 可选：从原始媒体的第几秒开始切取声纹片段 */
  start_seconds?: number;
  /** 可选：声纹片段时长（秒）。建议 3-10s 匹配 VoxCPM / GPT-SoVITS 推理约束 */
  duration_seconds?: number;
}

export const listVoices = () =>
  api.get<{ voices: Voice[] }>("/tts/voices").then((r) => r.data.voices);

export const extractVoice = (params: ExtractVoiceParams) => {
  const fd = new FormData();
  fd.append("reference", params.reference);
  if (params.speaker_name) fd.append("speaker_name", params.speaker_name);
  if (params.provider) fd.append("provider", params.provider);
  if (params.start_seconds !== undefined) {
    fd.append("start_seconds", String(params.start_seconds));
  }
  if (params.duration_seconds !== undefined) {
    fd.append("duration_seconds", String(params.duration_seconds));
  }
  return api
    .post<VoiceExtractResponse>("/tts/voices/extract", fd)
    .then((r) => r.data);
};

export const deleteVoice = (voiceId: string) =>
  api.delete(`/tts/voices/${encodeURIComponent(voiceId)}`);
