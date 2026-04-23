import { api } from "./client";

export interface HealthResponse {
  status: "ok" | "degraded" | "down";
  db: boolean;
  gpu: boolean;
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
