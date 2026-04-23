import { Empty, Typography } from "@douyinfe/semi-ui";

const { Title } = Typography;

export function Placeholder({ title }: { title: string }) {
  return (
    <div>
      <Title heading={3}>{title}</Title>
      <Empty
        image={<div style={{ fontSize: 56 }}>🌱</div>}
        title="页面开发中"
        description="即将上线，敬请期待"
        style={{ padding: "var(--vc-spacing-xl) 0" }}
      />
    </div>
  );
}
