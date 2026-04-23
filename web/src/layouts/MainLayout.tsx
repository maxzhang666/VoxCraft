import { Layout, Nav, Tag, Typography } from "@douyinfe/semi-ui";
import {
  IconHome,
  IconMicrophone,
  IconSong,
  IconUser,
  IconMusic,
  IconSetting,
} from "@douyinfe/semi-icons";
import { Outlet, useLocation, useNavigate } from "react-router-dom";

import { useSystem } from "@/stores/SystemContext";
import { t } from "@/i18n/zh-CN";

const { Header, Sider, Content } = Layout;
const { Text } = Typography;

const NAV_ITEMS = [
  { itemKey: "/", text: t.nav.dashboard, icon: <IconHome /> },
  { itemKey: "/asr", text: t.nav.asr, icon: <IconMicrophone /> },
  { itemKey: "/tts", text: t.nav.tts, icon: <IconSong /> },
  { itemKey: "/cloning", text: t.nav.cloning, icon: <IconUser /> },
  { itemKey: "/separator", text: t.nav.separator, icon: <IconMusic /> },
  { itemKey: "/settings", text: t.nav.settings, icon: <IconSetting /> },
];

function selectedKey(pathname: string): string {
  if (pathname === "/") return "/";
  const match = NAV_ITEMS.map((n) => n.itemKey)
    .filter((k) => k !== "/")
    .find((k) => pathname.startsWith(k));
  return match ?? "/";
}

export function MainLayout() {
  const nav = useNavigate();
  const loc = useLocation();
  const sys = useSystem();

  return (
    <Layout style={{ height: "100vh" }}>
      <Header
        style={{
          padding: "0 var(--vc-spacing-xl)",
          backgroundColor: "var(--vc-color-bg-card)",
          borderBottom: "1px solid var(--vc-color-border)",
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
        }}
      >
        <Text strong style={{ fontSize: 18 }}>
          🌿 {t.appName}{" "}
          <Text type="tertiary" size="small">
            v{sys.version}
          </Text>
        </Text>
        <div style={{ display: "flex", gap: "var(--vc-spacing-md)" }}>
          <Tag color={sys.sseConnected ? "teal" : "grey"}>
            {sys.sseConnected ? "● 已连接" : "● 断线"}
          </Tag>
          {sys.gpu.available && sys.gpu.totalMb > 0 && (
            <Tag color="blue">
              GPU {sys.gpu.usedMb}/{sys.gpu.totalMb} MB
            </Tag>
          )}
          <Tag>队列 {sys.queueSize}</Tag>
        </div>
      </Header>

      <Layout>
        <Sider
          style={{
            backgroundColor: "var(--vc-color-bg-card)",
            width: 220,
            flexShrink: 0,
          }}
        >
          <Nav
            style={{ width: "100%", height: "100%", border: "none" }}
            items={NAV_ITEMS}
            selectedKeys={[selectedKey(loc.pathname)]}
            onClick={({ itemKey }) => nav(String(itemKey))}
          />
        </Sider>

        <Content
          style={{
            padding: "var(--vc-spacing-xl)",
            backgroundColor: "var(--vc-color-bg)",
            overflow: "auto",
          }}
        >
          <Outlet />
        </Content>
      </Layout>
    </Layout>
  );
}
