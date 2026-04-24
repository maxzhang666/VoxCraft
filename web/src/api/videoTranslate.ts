import { api } from "./client";
import type { JobSubmitResponse, VideoTranslateSubmitParams } from "@/types/api";

export async function submitVideoTranslate(
  params: VideoTranslateSubmitParams,
): Promise<JobSubmitResponse> {
  const fd = new FormData();
  fd.append("source_file", params.source_file);
  fd.append("target_lang", params.target_lang);
  if (params.source_lang) fd.append("source_lang", params.source_lang);
  if (params.subtitle_mode) fd.append("subtitle_mode", params.subtitle_mode);
  if (params.clone_voice !== undefined)
    fd.append("clone_voice", String(params.clone_voice));
  if (params.align_mode) fd.append("align_mode", params.align_mode);
  if (params.align_max_speedup !== undefined)
    fd.append("align_max_speedup", String(params.align_max_speedup));
  if (params.asr_provider_id !== undefined)
    fd.append("asr_provider_id", String(params.asr_provider_id));
  if (params.tts_provider_id !== undefined)
    fd.append("tts_provider_id", String(params.tts_provider_id));
  if (params.llm_provider_id !== undefined)
    fd.append("llm_provider_id", String(params.llm_provider_id));
  if (params.system_prompt) fd.append("system_prompt", params.system_prompt);

  const r = await api.post<JobSubmitResponse>("/video-translate", fd);
  return r.data;
}
