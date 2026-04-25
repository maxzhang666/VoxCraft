import { Button, Space, Tabs, Typography } from "@douyinfe/semi-ui";
import { IconPlus, IconRefresh } from "@douyinfe/semi-icons";
import { useState } from "react";

import { CloningDrawer } from "@/drawers/CloningDrawer";
import { HistoryTab } from "./HistoryTab";
import { VoicesTab } from "./VoicesTab";

const { Title } = Typography;
const { TabPane } = Tabs;

export function CloningPage() {
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);
  const [activeTab, setActiveTab] = useState("history");

  const onSuccess = () => {
    setDrawerOpen(false);
    setReloadKey((k) => k + 1);
  };

  // 顶部刷新按钮：bump reloadKey 触发 HistoryTab / VoicesTab 重新拉取（两个 Tab 都依赖此 key）
  const onRefresh = () => setReloadKey((k) => k + 1);

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
          🎭 语音克隆
        </Title>
        <Space>
          <Button icon={<IconRefresh />} onClick={onRefresh}>
            刷新
          </Button>
          <Button
            theme="solid"
            icon={<IconPlus />}
            onClick={() => setDrawerOpen(true)}
          >
            + 新建克隆
          </Button>
        </Space>
      </div>

      <Tabs activeKey={activeTab} onChange={setActiveTab}>
        <TabPane tab="历史任务" itemKey="history">
          <HistoryTab reloadKey={reloadKey} />
        </TabPane>
        <TabPane tab="我的音色" itemKey="voices">
          <VoicesTab reloadKey={reloadKey} />
        </TabPane>
      </Tabs>

      <CloningDrawer
        visible={drawerOpen}
        onClose={() => setDrawerOpen(false)}
        onSuccess={onSuccess}
      />
    </div>
  );
}
