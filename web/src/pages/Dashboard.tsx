import { Card, Col, Descriptions, Row, Space, Typography } from "@douyinfe/semi-ui";
import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";

import { listJobs } from "@/api/jobs";
import { GpuGauge } from "@/components/GpuGauge";
import { StatusTag } from "@/components/StatusTag";
import { useSse } from "@/hooks/useSse";
import { useSystem } from "@/stores/SystemContext";
import type { Job, JobKind } from "@/types/api";

const { Title, Text } = Typography;

const KIND_META: Record<JobKind, { label: string; icon: string; path: string }> = {
  asr: { label: "语音转文字", icon: "🎧", path: "/asr" },
  tts: { label: "语音合成", icon: "🔊", path: "/tts" },
  clone: { label: "语音克隆", icon: "🎭", path: "/cloning" },
  separate: { label: "人声分离", icon: "🎸", path: "/separator" },
  video_translate: { label: "视频翻译", icon: "🎬", path: "/video-translate" },
};

const KINDS: JobKind[] = ["asr", "tts", "clone", "separate", "video_translate"];

export function Dashboard() {
  const sys = useSystem();
  const navigate = useNavigate();
  const [recent, setRecent] = useState<Job[]>([]);

  const refresh = useCallback(async () => {
    try {
      const jobs = await listJobs({ limit: 5 });
      setRecent(jobs);
    } catch {
      // 拦截器已提示
    }
  }, []);

  useEffect(() => {
    refresh();
    // 10s 兜底轮询；SSE 正常时不会触发冗余
    const id = setInterval(refresh, 10000);
    return () => clearInterval(id);
  }, [refresh]);

  // SSE 驱动即时更新：任何 job 状态变化都刷新列表
  useSse(["job_status_changed"], refresh);

  return (
    <div style={{ maxWidth: 1200, margin: "0 auto" }}>
      <Title heading={3} style={{ marginBottom: "var(--vc-spacing-lg)" }}>
        🌿 首页
      </Title>

      {/* 能力快捷入口 */}
      <Row gutter={16} style={{ marginBottom: "var(--vc-spacing-lg)" }}>
        {KINDS.map((k) => {
          const m = KIND_META[k];
          return (
            <Col span={Math.floor(24 / KINDS.length)} key={k}>
              <div
                onClick={() => navigate(m.path)}
                style={{ cursor: "pointer" }}
              >
                <Card
                  shadows="hover"
                  bodyStyle={{
                    padding: "var(--vc-spacing-lg)",
                    textAlign: "center",
                  }}
                >
                  <div style={{ fontSize: 32, lineHeight: 1 }}>{m.icon}</div>
                  <div style={{ marginTop: 8, fontWeight: 500 }}>{m.label}</div>
                </Card>
              </div>
            </Col>
          );
        })}
      </Row>

      {/* 服务状态 / GPU */}
      <Row gutter={16}>
        <Col span={12}>
          <Card title="服务状态" style={{ height: "100%" }}>
            <Descriptions
              align="left"
              data={[
                { key: "版本", value: `v${sys.version}` },
                {
                  key: "连接",
                  value: sys.sseConnected ? "● 已连接" : "● 断线",
                },
                {
                  key: "当前模型",
                  value: sys.activeProvider
                    ? `${sys.activeProvider.kind} / ${sys.activeProvider.name}`
                    : "无",
                },
                { key: "队列", value: String(sys.queueSize) },
              ]}
            />
          </Card>
        </Col>
        <Col span={12}>
          <Card title="GPU 占用">
            <GpuGauge
              usedMb={sys.gpu.usedMb}
              totalMb={sys.gpu.totalMb}
              available={sys.gpu.available}
            />
          </Card>
        </Col>
      </Row>

      {/* 最近 5 个任务（点击跳转对应能力页） */}
      <Card title="最近 5 个任务" style={{ marginTop: "var(--vc-spacing-lg)" }}>
        {recent.length === 0 ? (
          <Text type="tertiary">暂无任务记录</Text>
        ) : (
          recent.map((j) => {
            const m = KIND_META[j.kind];
            return (
              <div
                key={j.id}
                onClick={() => navigate(m.path)}
                style={{
                  display: "flex",
                  justifyContent: "space-between",
                  padding: "var(--vc-spacing-sm) 0",
                  borderBottom: "1px solid var(--vc-color-border)",
                  cursor: "pointer",
                }}
              >
                <Space>
                  <StatusTag status={j.status} />
                  <Text>
                    {m.icon} {m.label}
                  </Text>
                  <Text type="tertiary" size="small">
                    {j.id.slice(0, 8)}
                  </Text>
                </Space>
                <Text type="tertiary" size="small">
                  {new Date(j.created_at).toLocaleString("zh-CN")}
                </Text>
              </div>
            );
          })
        )}
      </Card>
    </div>
  );
}
