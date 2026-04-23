import { api } from "./client";
import type { Job, JobKind, JobStatus } from "@/types/api";

export interface ListJobsParams {
  kind?: JobKind;
  status?: JobStatus;
  since?: string;
  limit?: number;
  offset?: number;
}

export const listJobs = (params: ListJobsParams = {}) =>
  api.get<Job[]>("/jobs", { params }).then((r) => r.data);

export const getJob = (id: string) =>
  api.get<Job>(`/jobs/${id}`).then((r) => r.data);

export const deleteJob = (id: string) => api.delete(`/jobs/${id}`);

export const retryJob = (id: string) =>
  api
    .post<{ job_id: string; status: string }>(`/jobs/${id}/retry`)
    .then((r) => r.data);

export const jobOutputUrl = (id: string, key?: string) =>
  key ? `/jobs/${id}/output?key=${encodeURIComponent(key)}` : `/jobs/${id}/output`;

export const jobPreviewUrl = (id: string, key?: string) =>
  key
    ? `/jobs/${id}/output/preview?key=${encodeURIComponent(key)}`
    : `/jobs/${id}/output/preview`;
