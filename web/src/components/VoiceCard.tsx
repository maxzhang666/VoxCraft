import { Button, Card, Popconfirm, Space, Typography } from "@douyinfe/semi-ui";
import type { Voice } from "@/types/api";

const { Text } = Typography;

interface Props {
  voice: Voice;
  speakerName?: string | null;
  onDelete?: (id: string) => void;
}

export function VoiceCard({ voice, speakerName, onDelete }: Props) {
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
        🎵 {speakerName || voice.id}
      </Text>
      {speakerName && (
        <Text type="tertiary" size="small">
          ID：{voice.id}
        </Text>
      )}
      <Text type="tertiary" size="small">
        语言：{voice.language}
        {voice.provider_name ? ` · ${voice.provider_name}` : ""}
      </Text>
      <Space>
        {voice.sample_url && (
          <audio controls src={voice.sample_url} style={{ height: 28 }} />
        )}
        {onDelete && (
          <Popconfirm
            title={`删除音色 ${speakerName || voice.id}？`}
            content="将同时删除磁盘上的参考音频文件，不可恢复"
            onConfirm={() => onDelete(voice.id)}
          >
            <Button size="small" type="danger">
              删除
            </Button>
          </Popconfirm>
        )}
      </Space>
    </Card>
  );
}
