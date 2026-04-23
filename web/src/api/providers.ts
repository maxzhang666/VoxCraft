import { api } from "./client";
import type {
  Provider,
  ProviderClassSchema,
  ProviderCreate,
  ProviderKind,
  ProviderUpdate,
} from "@/types/api";

export const listProviders = (kind?: ProviderKind) =>
  api
    .get<Provider[]>("/admin/providers", { params: kind ? { kind } : {} })
    .then((r) => r.data);

export const createProvider = (data: ProviderCreate) =>
  api.post<Provider>("/admin/providers", data).then((r) => r.data);

export const updateProvider = (id: number, data: ProviderUpdate) =>
  api.patch<Provider>(`/admin/providers/${id}`, data).then((r) => r.data);

export const deleteProvider = (id: number) =>
  api.delete(`/admin/providers/${id}`);

export const setDefaultProvider = (id: number) =>
  api.post<Provider>(`/admin/providers/${id}/set-default`).then((r) => r.data);

export const testProvider = (id: number) =>
  api
    .post<{ ok: boolean; provider: string; detail?: string }>(
      `/admin/providers/${id}/test`
    )
    .then((r) => r.data);

export const listProviderClasses = (kind?: ProviderKind) =>
  api
    .get<ProviderClassSchema[]>("/admin/providers/classes", {
      params: kind ? { kind } : {},
    })
    .then((r) => r.data);
