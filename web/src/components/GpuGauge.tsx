import { Progress, Typography } from "@douyinfe/semi-ui";

const { Text } = Typography;

interface Props {
  usedMb: number;
  totalMb: number;
  available: boolean;
}

export function GpuGauge({ usedMb, totalMb, available }: Props) {
  if (!available || totalMb === 0) {
    return (
      <div style={{ textAlign: "center", padding: "var(--vc-spacing-md)" }}>
        <Text type="tertiary">未检测到 GPU</Text>
      </div>
    );
  }
  const pct = Math.min(100, Math.round((usedMb / totalMb) * 100));
  const stroke =
    pct > 80
      ? "var(--vc-color-error)"
      : pct > 50
        ? "var(--vc-color-warning)"
        : "var(--vc-color-primary)";

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      <Progress percent={pct} stroke={stroke} showInfo={false} />
      <Text size="small">
        {usedMb} / {totalMb} MB · {pct}%
      </Text>
    </div>
  );
}
