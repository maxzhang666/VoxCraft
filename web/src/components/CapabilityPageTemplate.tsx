import { Button, Empty, Space, Typography } from "@douyinfe/semi-ui";
import { IconPlus } from "@douyinfe/semi-icons";
import type { ReactNode } from "react";

import { t } from "@/i18n/zh-CN";

const { Title } = Typography;

interface Props {
  title: string;
  icon?: string; // emoji
  onCreate: () => void;
  createLabel?: string;
  filters?: ReactNode;
  isEmpty?: boolean;
  children: ReactNode;
}

export function CapabilityPageTemplate({
  title,
  icon,
  onCreate,
  createLabel = t.actions.create,
  filters,
  isEmpty,
  children,
}: Props) {
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
        <Button theme="solid" icon={<IconPlus />} onClick={onCreate}>
          {createLabel}
        </Button>
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
