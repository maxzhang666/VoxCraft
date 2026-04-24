import { Button, Descriptions, Space, Table, Tabs, Tag, Typography } from "@douyinfe/semi-ui";
import { IconDownload } from "@douyinfe/semi-icons";
import { useEffect, useState } from "react";

import { jobOutputUrl } from "@/api/jobs";
import type { Job } from "@/types/api";
import { formatMediaDuration } from "@/utils/format";

const { Text, Paragraph } = Typography;

interface SegmentDetail {
  index: number;
  orig_start: number;
  orig_end: number;
  final_start: number;
  final_end: number;
  speed: number;
  drift: number;
  source_text: string;
  translated_text: string;
  untranslated: boolean;
}

interface Props {
  job: Job;
}

/**
 * 视频翻译专用详情面板：参数摘要 / 三路产物预览 / 逐段原文-译文对照。
 * 目标是用户无需下载单独文件就能把控每个环节的质量。
 */
export function VideoTranslateDetails({ job }: Props) {
  const request = (job.request ?? {}) as Record<string, unknown>;
  const result = (job.result ?? {}) as Record<string, unknown>;
  const extras = job.output_extras ?? {};
  const segments = (result.segments as SegmentDetail[] | undefined) ?? [];

  return (
    <Space vertical spacing={16} align="start" style={{ width: "100%" }}>
      <ParamsSummary request={request} result={result} />
      {job.status === "succeeded" && (
        <ArtifactsPreview jobId={job.id} extras={extras} />
      )}
      {segments.length > 0 && <SegmentsTable segments={segments} />}
    </Space>
  );
}

// ---------- 参数摘要 ----------

function ParamsSummary({
  request,
  result,
}: {
  request: Record<string, unknown>;
  result: Record<string, unknown>;
}) {
  const s = (k: string): string | null => {
    const v = request[k];
    return typeof v === "string" ? v : null;
  };
  const b = (k: string): boolean | null => {
    const v = request[k];
    return typeof v === "boolean" ? v : null;
  };
  const rs = (k: string): unknown => result[k];

  const data: { key: string; value: React.ReactNode }[] = [
    { key: "源 → 目标", value: `${s("source_lang") ?? "auto"} → ${s("target_lang") ?? "-"}` },
    { key: "字幕模式", value: s("subtitle_mode") ?? "-" },
    {
      key: "克隆",
      value:
        b("clone_voice") === true ? (
          <Tag color="teal">开启</Tag>
        ) : (
          <Tag>关闭</Tag>
        ),
    },
    { key: "对齐模式", value: s("align_mode") ?? "-" },
    { key: "检测语言", value: typeof rs("language") === "string" ? (rs("language") as string) : "-" },
    {
      key: "原音频时长",
      value: typeof rs("duration") === "number" ? formatMediaDuration(rs("duration") as number) : "-",
    },
    { key: "分段数", value: String(rs("segment_count") ?? "-") },
  ];

  return (
    <div style={{ width: "100%" }}>
      <Text strong>编排参数</Text>
      <Descriptions align="left" data={data} style={{ marginTop: 4 }} />
    </div>
  );
}

// ---------- 产物预览 ----------

function ArtifactsPreview({
  jobId,
  extras,
}: {
  jobId: string;
  extras: Record<string, string>;
}) {
  const hasSubtitle = !!extras["subtitle"];
  const hasAudio = !!extras["audio"];
  const hasVideo = !!extras["video"];

  return (
    <div style={{ width: "100%" }}>
      <Text strong>产物预览</Text>
      <Tabs type="line" defaultActiveKey={hasVideo ? "video" : "audio"}>
        {hasSubtitle && (
          <Tabs.TabPane tab="字幕 (SRT)" itemKey="subtitle">
            <SubtitlePreview jobId={jobId} />
          </Tabs.TabPane>
        )}
        {hasAudio && (
          <Tabs.TabPane tab="译文音频" itemKey="audio">
            <div style={{ marginTop: 8 }}>
              <audio
                controls
                src={jobOutputUrl(jobId, "audio")}
                style={{ width: "100%" }}
              />
              <div style={{ marginTop: 8 }}>
                <DownloadButton url={jobOutputUrl(jobId, "audio")} label="下载音频" />
              </div>
            </div>
          </Tabs.TabPane>
        )}
        {hasVideo && (
          <Tabs.TabPane tab="合成视频" itemKey="video">
            <div style={{ marginTop: 8 }}>
              <video
                controls
                src={jobOutputUrl(jobId, "video")}
                style={{ width: "100%", maxHeight: 360 }}
              />
              <div style={{ marginTop: 8 }}>
                <DownloadButton url={jobOutputUrl(jobId, "video")} label="下载视频" />
              </div>
            </div>
          </Tabs.TabPane>
        )}
      </Tabs>
    </div>
  );
}

function SubtitlePreview({ jobId }: { jobId: string }) {
  const [text, setText] = useState<string>("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const url = jobOutputUrl(jobId, "subtitle");
    fetch(url)
      .then((r) => (r.ok ? r.text() : Promise.reject(r.status)))
      .then(setText)
      .catch(() => setText("（字幕读取失败）"))
      .finally(() => setLoading(false));
  }, [jobId]);

  return (
    <div style={{ marginTop: 8 }}>
      <pre
        style={{
          maxHeight: 260,
          overflow: "auto",
          padding: "var(--vc-spacing-sm)",
          backgroundColor: "var(--vc-color-bg-muted, #f6f6f6)",
          fontSize: 12,
          borderRadius: 4,
          margin: 0,
          whiteSpace: "pre-wrap",
          wordBreak: "break-word",
        }}
      >
        {loading ? "加载中..." : text}
      </pre>
      <div style={{ marginTop: 8 }}>
        <DownloadButton url={jobOutputUrl(jobId, "subtitle")} label="下载 SRT" />
      </div>
    </div>
  );
}

function DownloadButton({ url, label }: { url: string; label: string }) {
  return (
    <Button
      size="small"
      icon={<IconDownload />}
      onClick={() => window.open(url, "_blank")}
    >
      {label}
    </Button>
  );
}

// ---------- 逐段对照表 ----------

function SegmentsTable({ segments }: { segments: SegmentDetail[] }) {
  const columns = [
    {
      title: "#",
      dataIndex: "index",
      width: 48,
    },
    {
      title: "原时间",
      width: 120,
      render: (_: unknown, r: SegmentDetail) =>
        `${formatMediaDuration(r.orig_start)} ~ ${formatMediaDuration(r.orig_end)}`,
    },
    {
      title: "原文",
      dataIndex: "source_text",
      render: (t: string) => (
        <Paragraph
          ellipsis={{ rows: 2, expandable: true }}
          style={{ margin: 0 }}
        >
          {t}
        </Paragraph>
      ),
    },
    {
      title: "译文",
      dataIndex: "translated_text",
      render: (t: string, r: SegmentDetail) => (
        <Paragraph
          ellipsis={{ rows: 2, expandable: true }}
          style={{
            margin: 0,
            color: r.untranslated ? "var(--semi-color-warning)" : undefined,
          }}
        >
          {t}
        </Paragraph>
      ),
    },
    {
      title: "速率",
      width: 80,
      render: (_: unknown, r: SegmentDetail) =>
        r.speed === 1 ? "-" : `${r.speed.toFixed(2)}x`,
    },
    {
      title: "drift",
      width: 80,
      render: (_: unknown, r: SegmentDetail) =>
        Math.abs(r.drift) < 0.05 ? "-" : `${r.drift > 0 ? "+" : ""}${r.drift.toFixed(2)}s`,
    },
  ];

  const untranslatedCount = segments.filter((s) => s.untranslated).length;

  return (
    <div style={{ width: "100%" }}>
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          marginBottom: 4,
        }}
      >
        <Text strong>原文-译文对照（{segments.length} 段）</Text>
        {untranslatedCount > 0 && (
          <Tag color="yellow">
            {untranslatedCount} 段未翻译（已回退原文）
          </Tag>
        )}
      </div>
      <Table
        columns={columns}
        dataSource={segments}
        rowKey="index"
        size="small"
        pagination={segments.length > 20 ? { pageSize: 20 } : false}
      />
    </div>
  );
}
