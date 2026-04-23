import { Button, Card, Space, Typography } from "@douyinfe/semi-ui";
import type { Voice } from "@/types/api";

const { Text } = Typography;

interface Props {
  voice: Voice;
  onDelete?: (id: string) => void;
}

export function VoiceCard({ voice, onDelete }: Props) {
  return (
    <Card
      style={{ height: "100%" }}
      bodyStyle={{
        display: "flex",
        flexDirection: "column",
        gap: "var(--vc-spacing-sm)",
        padding: "var(--vc-spacing-lg)",
      }}
    >
      <Text strong style={{ fontSize: 16 }}>
        🎵 {voice.id}
      </Text>
      <Text type="tertiary" size="small">
        语言：{voice.language}
      </Text>
      <Space>
        {voice.sample_url && (
          <audio controls src={voice.sample_url} style={{ height: 28 }} />
        )}
        {onDelete && (
          <Button size="small" type="danger" onClick={() => onDelete(voice.id)}>
            删除
          </Button>
        )}
      </Space>
    </Card>
  );
}
