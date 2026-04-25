import { Button, Empty, Space, Typography } from "@douyinfe/semi-ui";
import { IconPlus, IconRefresh } from "@douyinfe/semi-icons";
import { useState, type ReactNode } from "react";

import { t } from "@/i18n/zh-CN";

const { Title } = Typography;

interface Props {
  title: string;
  icon?: string; // emoji
  onCreate: () => void;
  /** 可选；提供则 header 渲染刷新按钮（带 loading）。各任务页直接传入 reload。 */
  onRefresh?: () => void | Promise<void>;
  createLabel?: string;
  filters?: ReactNode;
  isEmpty?: boolean;
  children: ReactNode;
}

export function CapabilityPageTemplate({
  title,
  icon,
  onCreate,
  onRefresh,
  createLabel = t.actions.create,
  filters,
  isEmpty,
  children,
}: Props) {
  const [refreshing, setRefreshing] = useState(false);
  const handleRefresh = async () => {
    if (!onRefresh) return;
    setRefreshing(true);
    try {
      await onRefresh();
    } finally {
      setRefreshing(false);
    }
  };
  return (
    <div style={{ maxWidth: 1200, margin: "0 auto" }}>
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          marginBottom: "var(--vc-spacing-lg)",
        }}
      >
        <Title heading={3} style={{ margin: 0 }}>
          {icon && <span style={{ marginRight: 8 }}>{icon}</span>}
          {title}
        </Title>
        <Space>
          {onRefresh && (
            <Button
              icon={<IconRefresh />}
              onClick={handleRefresh}
              loading={refreshing}
            >
              刷新
            </Button>
          )}
          <Button theme="solid" icon={<IconPlus />} onClick={onCreate}>
            {createLabel}
          </Button>
        </Space>
      </div>

      {filters && (
        <div style={{ marginBottom: "var(--vc-spacing-md)" }}>
          <Space>{filters}</Space>
        </div>
      )}

      {isEmpty ? (
        <Empty
          image={<div style={{ fontSize: 56 }}>🌱</div>}
          title={t.common.empty}
          style={{ padding: "60px 0" }}
        />
      ) : (
        children
      )}
    </div>
  );
}
