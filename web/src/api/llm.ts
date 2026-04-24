import { api } from "./client";
import type {
  LlmProvider,
  LlmProviderCreate,
  LlmProviderUpdate,
} from "@/types/api";

export const listLlms = () =>
  api.get<LlmProvider[]>("/admin/llm").then((r) => r.data);

export const createLlm = (data: LlmProviderCreate) =>
  api.post<LlmProvider>("/admin/llm", data).then((r) => r.data);

export const updateLlm = (id: number, data: LlmProviderUpdate) =>
  api.patch<LlmProvider>(`/admin/llm/${id}`, data).then((r) => r.data);

export const deleteLlm = (id: number) => api.delete(`/admin/llm/${id}`);

export const setDefaultLlm = (id: number) =>
  api.post<LlmProvider>(`/admin/llm/${id}/set-default`).then((r) => r.data);

export interface ProbeModelsRequest {
  base_url: string;
  api_key?: string;
  use_id?: number;
}

export const probeLlmModels = (body: ProbeModelsRequest) =>
  api
    .post<{ models: string[] }>("/admin/llm/probe-models", body)
    .then((r) => r.data.models);
