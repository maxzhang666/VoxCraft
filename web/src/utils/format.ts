/**
 * 文件大小 / 时长格式化工具。
 * 在 JobCard badge 行、任务详情等多处复用。
 */

export function formatBytes(n: number | null | undefined): string {
  if (n === null || n === undefined || n < 0 || !Number.isFinite(n)) return "-";
  if (n < 1024) return `${n} B`;
  if (n < 1024 ** 2) return `${(n / 1024).toFixed(1)} KB`;
  if (n < 1024 ** 3) return `${(n / 1024 ** 2).toFixed(1)} MB`;
  return `${(n / 1024 ** 3).toFixed(2)} GB`;
}

/** 把毫秒数格式化为人类可读时长（耗时场景，精度到秒）。 */
export function formatElapsed(ms: number | null | undefined): string {
  if (ms === null || ms === undefined || ms < 0 || !Number.isFinite(ms)) return "-";
  const s = Math.floor(ms / 1000);
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  const rem = s % 60;
  if (m < 60) return `${m}m${rem ? `${rem}s` : ""}`;
  const h = Math.floor(m / 60);
  const mRem = m % 60;
  return `${h}h${mRem ? `${mRem}m` : ""}`;
}

/** 把秒数格式化为媒体时长（mm:ss / h:mm:ss）。 */
export function formatMediaDuration(seconds: number | null | undefined): string {
  if (
    seconds === null || seconds === undefined ||
    seconds < 0 || !Number.isFinite(seconds)
  ) return "-";
  const s = Math.floor(seconds % 60);
  const m = Math.floor(seconds / 60) % 60;
  const h = Math.floor(seconds / 3600);
  const pad = (n: number) => n.toString().padStart(2, "0");
  if (h > 0) return `${h}:${pad(m)}:${pad(s)}`;
  return `${m}:${pad(s)}`;
}
