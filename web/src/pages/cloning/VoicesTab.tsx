import { Button, Col, Empty, Row, Space, Toast, Typography } from "@douyinfe/semi-ui";
import { IconPlus } from "@douyinfe/semi-icons";
import { useCallback, useEffect, useState } from "react";

import { deleteVoice, listVoices } from "@/api/voices";
import { VoiceCard } from "@/components/VoiceCard";
import { ExtractVoiceDrawer } from "@/drawers/ExtractVoiceDrawer";
import type { Voice } from "@/types/api";
import { t } from "@/i18n/zh-CN";

const { Text } = Typography;

export function VoicesTab({ reloadKey }: { reloadKey: number }) {
  const [voices, setVoices] = useState<Voice[]>([]);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [internalKey, setInternalKey] = useState(0);

  const reload = useCallback(async () => {
    try {
      const all = await listVoices();
      setVoices(all.filter((v) => v.id.startsWith("vx_")));
    } catch {
      // ignore
    }
  }, []);

  useEffect(() => {
    reload();
  }, [reload, reloadKey, internalKey]);

  const onExtractSuccess = () => {
    setDrawerOpen(false);
    setInternalKey((k) => k + 1);
  };

  const onDelete = async (id: string) => {
    try {
      await deleteVoice(id);
      Toast.success("已删除");
      setInternalKey((k) => k + 1);
    } catch {
      // 拦截器已提示
    }
  };

  return (
    <>
      <Space style={{ marginBottom: "var(--vc-spacing-md)" }}>
        <Button
          icon={<IconPlus />}
          onClick={() => setDrawerOpen(true)}
        >
          抽取声纹
        </Button>
        <Text type="tertiary" size="small">
          上传音频或视频，自动抽取音轨并加入音色库
        </Text>
      </Space>

      {voices.length === 0 ? (
        <Empty
          image={<div style={{ fontSize: 48 }}>🎵</div>}
          title="还没有音色"
          description={t.common.empty}
          style={{ padding: "40px 0" }}
        />
      ) : (
        <Row gutter={[16, 16]}>
          {voices.map((v) => (
            <Col span={8} key={v.id}>
              <VoiceCard voice={v} onDelete={onDelete} />
            </Col>
          ))}
        </Row>
      )}

      <ExtractVoiceDrawer
        visible={drawerOpen}
        onClose={() => setDrawerOpen(false)}
        onSuccess={onExtractSuccess}
      />
    </>
  );
}
