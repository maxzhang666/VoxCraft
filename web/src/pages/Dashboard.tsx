import { Card, Col, Descriptions, Row, Space, Typography } from "@douyinfe/semi-ui";
import { useCallback, useEffect, useState } from "react";

import { listJobs } from "@/api/jobs";
import { GpuGauge } from "@/components/GpuGauge";
import { StatusTag } from "@/components/StatusTag";
import { useSystem } from "@/stores/SystemContext";
import type { Job } from "@/types/api";

const { Title, Text } = Typography;

const KIND_LABEL: Record<string, string> = {
  asr: "🎧 语音转文字",
  tts: "🔊 语音合成",
  clone: "🎭 语音克隆",
  separate: "🎸 人声分离",
};

export function Dashboard() {
  const sys = useSystem();
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
    const id = setInterval(refresh, 10000);
    return () => clearInterval(id);
  }, [refresh]);

  return (
    <div style={{ maxWidth: 1200, margin: "0 auto" }}>
      <Title heading={3} style={{ marginBottom: "var(--vc-spacing-lg)" }}>
        🌿 首页
      </Title>

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

      <Card
        title="最近 5 个任务"
        style={{ marginTop: "var(--vc-spacing-lg)" }}
      >
        {recent.length === 0 ? (
          <Text type="tertiary">暂无任务记录</Text>
        ) : (
          recent.map((j) => (
            <div
              key={j.id}
              style={{
                display: "flex",
                justifyContent: "space-between",
                padding: "var(--vc-spacing-sm) 0",
                borderBottom: "1px solid var(--vc-color-border)",
              }}
            >
              <Space>
                <StatusTag status={j.status} />
                <Text>{KIND_LABEL[j.kind] ?? j.kind}</Text>
                <Text type="tertiary" size="small">
                  {j.id.slice(0, 8)}
                </Text>
              </Space>
              <Text type="tertiary" size="small">
                {new Date(j.created_at).toLocaleString("zh-CN")}
              </Text>
            </div>
          ))
        )}
      </Card>
    </div>
  );
}
