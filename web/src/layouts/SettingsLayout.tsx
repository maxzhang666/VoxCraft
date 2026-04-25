import { Layout, Nav } from "@douyinfe/semi-ui";
import { Outlet, useLocation, useNavigate } from "react-router-dom";

import { t } from "@/i18n/zh-CN";

const { Sider, Content } = Layout;

const SETTINGS_ITEMS = [
  { itemKey: "/settings/models", text: t.settingsNav.models },
  { itemKey: "/settings/models-library", text: t.settingsNav.modelsLibrary },
  { itemKey: "/settings/llm", text: t.settingsNav.llm },
  { itemKey: "/settings/proxy", text: t.settingsNav.proxy },
  { itemKey: "/settings/system", text: t.settingsNav.system },
  { itemKey: "/settings/jobs", text: t.settingsNav.jobs },
];

export function SettingsLayout() {
  const nav = useNavigate();
  const loc = useLocation();

  return (
    <Layout style={{ height: "100%" }}>
      <Sider style={{ width: 180, flexShrink: 0, backgroundColor: "transparent" }}>
        <Nav
          items={SETTINGS_ITEMS}
          selectedKeys={[loc.pathname]}
          onClick={({ itemKey }) => nav(String(itemKey))}
          style={{
            width: "100%",            // 覆盖 Semi Nav 默认 240px，避免溢出到右侧 Content
            border: "none",
            backgroundColor: "transparent",
          }}
        />
      </Sider>
      <Content style={{ paddingLeft: "var(--vc-spacing-xl)" }}>
        <Outlet />
      </Content>
    </Layout>
  );
}
