import { api } from "./client";

export interface GpuInfo {
  available: boolean;
  used_mb: number;
  total_mb: number;
  name: string | null;
}

export interface HealthResponse {
  status: "ok" | "degraded" | "down";
  db: boolean;
  gpu: GpuInfo;
}

export interface ModelsResponse {
  asr: string[];
  tts: string[];
  cloning: string[];
  separator: string[];
  translation: string[];
}

export const getHealth = () =>
  api.get<HealthResponse>("/health").then((r) => r.data);

export const getModels = () =>
  api.get<ModelsResponse>("/models").then((r) => r.data);
