import { Col, Empty, Row } from "@douyinfe/semi-ui";
import { useCallback, useEffect, useState } from "react";

import { listVoices } from "@/api/voices";
import { VoiceCard } from "@/components/VoiceCard";
import type { Voice } from "@/types/api";
import { t } from "@/i18n/zh-CN";

export function VoicesTab({ reloadKey }: { reloadKey: number }) {
  const [voices, setVoices] = useState<Voice[]>([]);

  const reload = useCallback(async () => {
    try {
      // 过滤出 vx_ 开头的克隆音色（非静态 Provider name）
      const all = await listVoices();
      setVoices(all.filter((v) => v.id.startsWith("vx_")));
    } catch {
      // ignore
    }
  }, []);

  useEffect(() => {
    reload();
  }, [reload, reloadKey]);

  if (voices.length === 0) {
    return (
      <Empty
        image={<div style={{ fontSize: 48 }}>🎵</div>}
        title="还没有克隆的音色"
        description={t.common.empty}
        style={{ padding: "40px 0" }}
      />
    );
  }

  return (
    <Row gutter={[16, 16]}>
      {voices.map((v) => (
        <Col span={8} key={v.id}>
          <VoiceCard voice={v} />
        </Col>
      ))}
    </Row>
  );
}
