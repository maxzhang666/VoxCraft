import { Empty, Typography } from "@douyinfe/semi-ui";

const { Title, Paragraph } = Typography;

export function LlmConfig() {
  return (
    <div>
      <Title heading={3} style={{ marginBottom: "var(--vc-spacing-lg)" }}>
        LLM 配置
      </Title>
      <Paragraph type="tertiary">
        翻译能力延后到 v0.5+ 接入（见 ADR-003）。此页为占位。
      </Paragraph>
      <Empty
        image={<div style={{ fontSize: 56 }}>🌐</div>}
        title="暂未启用"
        description="v0.5+ 接入 OpenAI 兼容 LLM API 后可管理"
        style={{ padding: "60px 0" }}
      />
    </div>
  );
}
