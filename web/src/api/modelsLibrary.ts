import { api } from "./client";
import type {
  CatalogView,
  CustomAddRequest,
  ModelResponse,
} from "@/types/api";

export const listLibrary = () =>
  api.get<CatalogView[]>("/admin/models-library").then((r) => r.data);

export const downloadCatalog = (key: string, source?: string) =>
  api
    .post<ModelResponse>(
      `/admin/models-library/${encodeURIComponent(key)}/download`,
      null,
      { params: source ? { source } : {} }
    )
    .then((r) => r.data);

export const addCustomModel = (data: CustomAddRequest) =>
  api.post<ModelResponse>("/admin/models-library/custom", data).then((r) => r.data);

export const deleteModel = (id: number) =>
  api.delete(`/admin/models-library/${id}`);

export const cancelDownload = (id: number) =>
  api.post(`/admin/models-library/${id}/cancel`);
