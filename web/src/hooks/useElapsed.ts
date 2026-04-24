import { useEffect, useState } from "react";

import type { Job } from "@/types/api";

/**
 * 返回 Job 当前已耗时（毫秒）。
 * - running：每秒 tick，实时变大
 * - succeeded/failed/cancelled：锁定在 finished_at - started_at
 * - pending/无 started_at：null（调用方自行处理）
 */
export function useElapsed(job: Job): number | null {
  const [now, setNow] = useState<number>(() => Date.now());

  useEffect(() => {
    if (job.status !== "running") return;
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, [job.status, job.id]);

  if (!job.started_at) return null;

  const start = new Date(job.started_at).getTime();
  if (job.status === "running") return now - start;

  if (job.finished_at) {
    return new Date(job.finished_at).getTime() - start;
  }
  return null;
}
