import {
  Button,
  Card,
  Popconfirm,
  Progress,
  Space,
  Tag,
  Typography,
} from "@douyinfe/semi-ui";
import type { CatalogView } from "@/types/api";

const { Text } = Typography;

const TIER_LABEL: Record<string, { label: string; color: string }> = {
  entry: { label: "入门", color: "grey" },
  mid: { label: "中端", color: "blue" },
  high: { label: "高端", color: "purple" },
};

const KIND_LABEL: Record<string, string> = {
  asr: "语音识别",
  tts: "语音合成",
  cloning: "语音克隆",
  separator: "人声分离",
  unknown: "未分类",
};

const SOURCE_BUTTON_LABEL: Record<string, string> = {
  hf: "⬇️ HF",
  ms: "⬇️ MS",
  url: "⬇️ 直链",
  torch_hub: "⬇️ torch.hub",
};

interface Props {
  entry: CatalogView;
  onDownload: (entry: CatalogView, source: string) => void | Promise<void>;
  onCancel: (entry: CatalogView) => void | Promise<void>;
  onDelete: (entry: CatalogView) => void | Promise<void>;
}

export function ModelCatalogCard({ entry, onDownload, onCancel, onDelete }: Props) {
  const tier = TIER_LABEL[entry.recommend_tier] ?? { label: entry.recommend_tier, color: "grey" };
  const sizeMb = entry.size_bytes
    ? Math.round(entry.size_bytes / 1024 / 1024)
    : entry.size_mb;
  const { status } = entry;
  const isActive = status === "pending" || status === "downloading";
  const isTerminal = status === "ready" || status === "failed" || status === "cancelled";
  const canDownload = status === "not_downloaded" || status === "failed" || status === "cancelled";
  const sourcesLine = entry.sources.map((s) => `${s.id}: ${s.repo_id}`).join("  ·  ");

  return (
    <Card
      bodyStyle={{
        padding: "var(--vc-spacing-lg)",
        display: "flex",
        flexDirection: "column",
        gap: 8,
        height: "100%",
      }}
      style={{ height: "100%" }}
    >
      {/* 标题：长文本 ellipsis + tooltip */}
      <Text strong style={{ fontSize: 15 }} ellipsis={{ showTooltip: true }}>
        {entry.label}
      </Text>

      {/* 标签：tier / kind / size / 镜像权威性 / custom 标记 */}
      <Space wrap spacing={4}>
        <Tag color={tier.color as any} size="small">{tier.label}</Tag>
        <Tag size="small">{KIND_LABEL[entry.kind] ?? entry.kind}</Tag>
        <Tag color="cyan" size="small">{sizeMb} MB</Tag>
        {entry.mirror_authority === "community" && (
          <Tag color="orange" size="small">社区</Tag>
        )}
        {!entry.is_builtin && <Tag color="violet" size="small">自定义</Tag>}
      </Space>

      {/* 数据源（repo_id 通常很长，必须 ellipsis + hover 完整） */}
      {sourcesLine && (
        <Text type="tertiary" size="small" ellipsis={{ showTooltip: true }}>
          {sourcesLine}
        </Text>
      )}

      {/* 状态行 / 进度 */}
      {status === "downloading" && (
        <>
          <Progress
            percent={Math.max(1, Math.round(entry.progress * 100))}
            stroke="var(--vc-color-primary)"
            showInfo={false}
            style={{ width: "100%" }}
          />
          {entry.queue_position != null && entry.queue_position > 0 ? (
            <Text type="tertiary" size="small">
              ⏳ 排队（前 {entry.queue_position} 个）
            </Text>
          ) : (
            <Text type="tertiary" size="small">下载中…</Text>
          )}
        </>
      )}

      {status === "ready" && entry.local_path && (
        <Text
          type="tertiary"
          size="small"
          ellipsis={{ showTooltip: true }}
        >
          ✓ {entry.local_path}
        </Text>
      )}

      {status === "failed" && (
        <Text type="danger" size="small" ellipsis={{ showTooltip: true }}>
          ✗ [{entry.error_code ?? "DOWNLOAD_FAILED"}] 下载失败，可重试
        </Text>
      )}

      {status === "cancelled" && (
        <Text type="warning" size="small">⊘ 已取消</Text>
      )}

      {/* 占位 spacer：让按钮始终在卡片底部对齐 */}
      <div style={{ flex: 1 }} />

      <Space wrap spacing={4}>
        {canDownload &&
          entry.sources.map((s) => (
            <Popconfirm
              key={s.id}
              title={`下载 ${entry.label}？`}
              content={`约 ${sizeMb} MB，来源：${s.id}`}
              onConfirm={() => onDownload(entry, s.id)}
            >
              <Button
                theme={s.id === "ms" ? "solid" : "light"}
                size="small"
                type={s.id === "ms" ? "primary" : "tertiary"}
              >
                {SOURCE_BUTTON_LABEL[s.id] ?? s.id}
              </Button>
            </Popconfirm>
          ))}

        {isActive && (
          <Button size="small" onClick={() => onCancel(entry)}>
            取消
          </Button>
        )}

        {isTerminal && status === "ready" && (
          <Popconfirm
            title="删除此模型？"
            content="会同时删除本地文件；若被 Provider 引用会拒绝删除。"
            onConfirm={() => onDelete(entry)}
          >
            <Button size="small" type="danger">删除</Button>
          </Popconfirm>
        )}

        {(status === "failed" || status === "cancelled") && entry.model_id != null && (
          <Button size="small" type="tertiary" onClick={() => onDelete(entry)}>
            清理记录
          </Button>
        )}
      </Space>
    </Card>
  );
}

