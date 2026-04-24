import { Space, Tag } from "@douyinfe/semi-ui";

import { useElapsed } from "@/hooks/useElapsed";
import type { Job } from "@/types/api";
import { formatBytes, formatElapsed, formatMediaDuration } from "@/utils/format";

type Color =
  | "grey" | "blue" | "green" | "teal" | "yellow" | "orange" | "red" | "violet";

interface Badge {
  text: string;
  color?: Color;
}

interface Props {
  job: Job;
}

/**
 * 任务卡片元信息行（ADR-014 之外的通用组件）。
 * 每种 kind 精选 4-5 个最有价值的字段，减少点进详情的频次。
 * 实时耗时通过 useElapsed hook 每秒 tick。
 */
export function JobBadges({ job }: Props) {
  const elapsedMs = useElapsed(job);
  const elapsedText = elapsedMs !== null ? formatElapsed(elapsedMs) : null;

  const badges = buildBadges(job, elapsedText);
  if (badges.length === 0) return null;

  return (
    <div style={{ marginTop: 4, marginBottom: 4 }}>
      <Space wrap spacing={6}>
        {badges.map((b, i) => (
          <Tag key={i} size="small" color={b.color ?? "grey"}>
            {b.text}
          </Tag>
        ))}
      </Space>
    </div>
  );
}

function buildBadges(job: Job, elapsed: string | null): Badge[] {
  // 通用：队列位置（仅 pending）
  if (job.status === "pending") {
    const out: Badge[] = [];
    if (job.queue_position !== null && job.queue_position !== undefined) {
      out.push({ text: `队列 #${job.queue_position + 1}`, color: "blue" });
    }
    if (job.provider_name) out.push({ text: `模型: ${job.provider_name}` });
    const srcSize = reqNum(job, "source_size_bytes");
    if (srcSize !== null) out.push({ text: formatBytes(srcSize) });
    return out;
  }

  const req = (job.request ?? {}) as Record<string, unknown>;
  const res = (job.result ?? {}) as Record<string, unknown>;
  const sizes = (res.artifact_sizes ?? {}) as Record<string, number>;
  const srcSize = reqNum(job, "source_size_bytes");
  const timeText = elapsed ?? "-";

  switch (job.kind) {
    case "asr": {
      const out: Badge[] = [];
      if (job.provider_name) out.push({ text: job.provider_name });
      if (srcSize !== null) out.push({ text: formatBytes(srcSize) });
      const dur = resNum(res, "duration");
      if (dur !== null) out.push({ text: formatMediaDuration(dur) });
      const lang = resStr(res, "language");
      if (lang) out.push({ text: lang, color: "blue" });
      if (elapsed) out.push({ text: timeText });
      return out;
    }

    case "tts": {
      const out: Badge[] = [];
      if (job.provider_name) out.push({ text: job.provider_name });
      const text = reqStr(req, "text");
      if (text) out.push({ text: `${text.length} 字` });
      const fmt = reqStr(req, "format");
      if (fmt) out.push({ text: fmt });
      const mainSize = sizes.main;
      if (typeof mainSize === "number") out.push({ text: formatBytes(mainSize) });
      if (elapsed) out.push({ text: timeText });
      return out;
    }

    case "clone": {
      const out: Badge[] = [];
      if (job.provider_name) out.push({ text: job.provider_name });
      if (srcSize !== null) out.push({ text: `参考 ${formatBytes(srcSize)}` });
      const text = reqStr(req, "text");
      if (text) out.push({ text: `${text.length} 字` });
      const mainSize = sizes.main;
      if (typeof mainSize === "number") out.push({ text: formatBytes(mainSize) });
      if (elapsed) out.push({ text: timeText });
      return out;
    }

    case "separate": {
      const out: Badge[] = [];
      if (job.provider_name) out.push({ text: job.provider_name });
      if (srcSize !== null) out.push({ text: formatBytes(srcSize) });
      if (typeof sizes.vocals === "number") {
        out.push({ text: `人声 ${formatBytes(sizes.vocals)}` });
      }
      if (typeof sizes.instrumental === "number") {
        out.push({ text: `BGM ${formatBytes(sizes.instrumental)}` });
      }
      if (elapsed) out.push({ text: timeText });
      return out;
    }

    case "video_translate": {
      const out: Badge[] = [];
      const src = reqStr(req, "source_lang");
      const tgt = reqStr(req, "target_lang");
      if (tgt) out.push({ text: `${src ?? "auto"} → ${tgt}`, color: "blue" });
      if (srcSize !== null) out.push({ text: formatBytes(srcSize) });
      const subtitleMode = reqStr(req, "subtitle_mode");
      if (subtitleMode && subtitleMode !== "none") {
        out.push({ text: `字幕 ${subtitleMode}` });
      }
      const warnCount = Array.isArray(job.warnings) ? job.warnings.length : 0;
      if (warnCount > 0) {
        out.push({ text: `${warnCount} 条警告`, color: "yellow" });
      }
      if (elapsed) out.push({ text: timeText });
      return out;
    }
  }
  return [];
}

// ---------- 字段取值 helpers（容忍 unknown） ----------

function reqNum(job: Job, key: string): number | null {
  const v = (job.request as Record<string, unknown>)?.[key];
  return typeof v === "number" ? v : null;
}

function reqStr(req: Record<string, unknown>, key: string): string | null {
  const v = req[key];
  return typeof v === "string" && v.length > 0 ? v : null;
}

function resNum(res: Record<string, unknown>, key: string): number | null {
  const v = res[key];
  return typeof v === "number" ? v : null;
}

function resStr(res: Record<string, unknown>, key: string): string | null {
  const v = res[key];
  return typeof v === "string" && v.length > 0 ? v : null;
}
