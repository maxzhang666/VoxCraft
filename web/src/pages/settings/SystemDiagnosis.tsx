import { Card, Descriptions, Typography } from "@douyinfe/semi-ui";
import { useCallback, useEffect, useState } from "react";

import { getHealth, getModels, type ModelsResponse } from "@/api/system";
import { GpuGauge } from "@/components/GpuGauge";
import { useSse } from "@/hooks/useSse";
import { useSystem } from "@/stores/SystemContext";

const { Title } = Typography;

export function SystemDiagnosis() {
  const sys = useSystem();
  const [health, setHealth] = useState<{ status: string; db: boolean; gpu: boolean } | null>(null);
  const [models, setModels] = useState<ModelsResponse | null>(null);

  const refresh = useCallback(() => {
    getHealth().then(setHealth).catch(() => undefined);
    getModels().then(setModels).catch(() => undefined);
  }, []);

  useEffect(() => {
    refresh();
    // 30s 周期刷新；面板停留期间保持数据新鲜
    const id = setInterval(refresh, 30000);
    return () => clearInterval(id);
  }, [refresh]);

  // Provider 启停 / 模型加载完成时立即刷新（运维场景这类事件敏感）
  useSse(
    ["model_loaded", "model_unloaded", "provider_failed"],
    refresh,
  );

  return (
    <div>
      <Title heading={3} style={{ marginBottom: "var(--vc-spacing-lg)" }}>
        系统诊断
      </Title>

      <Card title="运行时" style={{ marginBottom: "var(--vc-spacing-lg)" }}>
        <Descriptions
          data={[
            { key: "版本", value: `v${sys.version}` },
            { key: "服务状态", value: health?.status ?? "loading" },
            { key: "数据库", value: health?.db ? "✅ 正常" : "❌ 不可用" },
            { key: "GPU 可用", value: sys.gpu.available ? "是" : "否" },
            { key: "当前驻留", value: sys.activeProvider?.name ?? "无" },
            { key: "队列长度", value: String(sys.queueSize) },
            { key: "SSE", value: sys.sseConnected ? "● 已连接" : "● 断线" },
          ]}
        />
      </Card>

      <Card title="GPU 资源" style={{ marginBottom: "var(--vc-spacing-lg)" }}>
        <GpuGauge
          usedMb={sys.gpu.usedMb}
          totalMb={sys.gpu.totalMb}
          available={sys.gpu.available}
        />
      </Card>

      {models && (
        <Card title="已启用模型">
          <Descriptions
            data={(["asr", "tts", "cloning", "separator"] as const).map((k) => ({
              key: k,
              value: models[k].join(" · ") || "（无）",
            }))}
          />
        </Card>
      )}
    </div>
  );
}
