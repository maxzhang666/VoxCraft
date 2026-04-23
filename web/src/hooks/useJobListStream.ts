import type { Dispatch, SetStateAction } from "react";

import type { Job, JobKind } from "@/types/api";
import { useSse } from "./useSse";

/**
 * 能力页订阅 SSE 驱动本地 jobs 列表更新的统一 hook。
 *
 * - `job_progress` → 内存更新对应 job 的 progress（**不发 HTTP**，避免 per-segment 轮请求）
 * - `job_status_changed` → 走 reload（状态变化往往伴随 result/error/finished_at 等需后端拉的字段）
 *
 * 仅处理与 `kind` 匹配的事件；其他 kind 的事件由它自己的能力页处理。
 */
export function useJobListStream(
  kind: JobKind,
  reload: () => void,
  setJobs: Dispatch<SetStateAction<Job[]>>,
): void {
  useSse(["job_progress", "job_status_changed"], (ev) => {
    const p = ev.payload as {
      kind?: string;
      job_id?: string;
      progress?: number;
    };
    if (p.kind !== kind) return;

    if (ev.type === "job_progress" && p.job_id && typeof p.progress === "number") {
      const newProgress = p.progress;
      const targetId = p.job_id;
      setJobs((prev) =>
        prev.map((j) => (j.id === targetId ? { ...j, progress: newProgress } : j)),
      );
      return;
    }

    if (ev.type === "job_status_changed") {
      reload();
    }
  });
}
