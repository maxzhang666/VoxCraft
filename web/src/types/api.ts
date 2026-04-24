// 与后端 Pydantic schemas 对齐。未来可用 openapi-typescript 自动生成。

export type ProviderKind = "asr" | "tts" | "cloning" | "separator";

export interface Provider {
  id: number;
  kind: ProviderKind;
  name: string;
  class_name: string;
  config: Record<string, unknown>;
  is_default: boolean;
  enabled: boolean;
  created_at: string;
  updated_at: string;
}

export interface ProviderCreate {
  kind: ProviderKind;
  name: string;
  class_name: string;
  config: Record<string, unknown>;
  is_default?: boolean;
  enabled?: boolean;
}

export type ProviderUpdate = Partial<
  Pick<Provider, "config" | "is_default" | "enabled">
>;

export type JobKind =
  | "asr"
  | "tts"
  | "clone"
  | "separate"
  | "video_translate";

export type JobStatus =
  | "pending"
  | "running"
  | "succeeded"
  | "failed"
  | "cancelled";

export interface Job {
  id: string;
  kind: JobKind;
  status: JobStatus;
  provider_name: string | null;
  request: Record<string, unknown>;
  result: Record<string, unknown> | null;
  output_path: string | null;
  output_extras: Record<string, string> | null;
  error_code: string | null;
  error_message: string | null;
  progress: number;
  queue_position: number | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  warnings?: string[] | null;
}

// ---------- 视频语音级翻译（v0.4.0 / ADR-014） ----------

export type SubtitleMode = "soft" | "hard" | "none";
export type AlignMode = "elastic" | "natural" | "strict";

export interface VideoTranslateSubmitParams {
  source_file: File;
  target_lang: string;
  source_lang?: string;
  subtitle_mode?: SubtitleMode;
  clone_voice?: boolean;
  align_mode?: AlignMode;
  align_max_speedup?: number;
  asr_provider_id?: number;
  tts_provider_id?: number;
  llm_provider_id?: number;
  system_prompt?: string;
}

export interface JobSubmitResponse {
  job_id: string;
  status: JobStatus;
}

export interface AsrSegment {
  start: number;
  end: number;
  text: string;
}

export interface AsrResponse {
  segments: AsrSegment[];
  language: string;
  duration: number;
  provider: string;
}

export interface Voice {
  id: string;
  language: string;
  gender?: string | null;
  sample_url?: string | null;
}

export interface SseEvent<P = Record<string, unknown>> {
  type: string;
  payload: P;
  ts: string;
}

export interface ErrorResponse {
  error: {
    code: string;
    message: string;
    details?: Record<string, unknown> | null;
  };
}

// ---------- 模型库（v0.1.2 / ADR-010） ----------

export type ModelSource = "hf" | "ms" | "url" | "torch_hub";

export interface SourceInfo {
  id: ModelSource;
  repo_id: string;
}

export interface CatalogView {
  catalog_key: string;
  label: string;
  kind: string;
  size_mb: number;
  recommend_tier: "entry" | "mid" | "high";
  mirror_authority: "official" | "community";
  sources: SourceInfo[];
  is_builtin: boolean;
  provider_class: string | null;
  model_id: number | null;
  status: string;
  progress: number;
  local_path: string | null;
  queue_position: number | null;
  size_bytes: number | null;
  error_code: string | null;
}

export interface ModelResponse {
  id: number;
  catalog_key: string;
  source: string;
  repo_id: string;
  kind: string;
  local_path: string | null;
  status: string;
  progress: number;
  size_bytes: number | null;
  error_code: string | null;
  error_message: string | null;
  created_at: string;
  started_at?: string | null;
  finished_at?: string | null;
}

export interface CustomAddRequest {
  catalog_key: string;
  source: Exclude<ModelSource, "torch_hub">;
  repo_id: string;
  kind: ProviderKind;
  label?: string | null;
}

// ---------- Provider class schema（动态表单驱动） ----------

export type ConfigFieldType = "path" | "enum" | "str" | "int" | "bool";

export interface ConfigFieldSchema {
  key: string;
  label: string;
  type: ConfigFieldType;
  required: boolean;
  default: unknown;
  options: string[] | null;
  help: string | null;
}

export interface ProviderClassSchema {
  class_name: string;
  label: string;
  kind: ProviderKind;
  fields: ConfigFieldSchema[];
  capabilities: string[];
}

// ---------- LLM Provider（v0.3.0） ----------

export interface LlmProvider {
  id: number;
  name: string;
  base_url: string;
  model: string;
  is_default: boolean;
  enabled: boolean;
  created_at: string;
  updated_at: string;
  // 注意：api_key 永不在响应中返回
}

export interface LlmProviderCreate {
  name: string;
  base_url: string;
  api_key: string;
  model: string;
  is_default?: boolean;
  enabled?: boolean;
}

export interface LlmProviderUpdate {
  base_url?: string;
  api_key?: string; // 留空 = 保持原值
  model?: string;
  is_default?: boolean;
  enabled?: boolean;
}
