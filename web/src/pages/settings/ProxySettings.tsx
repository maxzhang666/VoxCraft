import {
  Banner,
  Button,
  Form,
  Input,
  Space,
  Toast,
  Typography,
} from "@douyinfe/semi-ui";
import { useEffect, useState } from "react";

import { getProxy, updateProxy, type ProxySettings as ProxyDto } from "@/api/proxy";

const { Title, Text } = Typography;

const EMPTY: ProxyDto = {
  hf_endpoint: "",
  https_proxy: "",
  http_proxy: "",
  no_proxy: "",
};

export function ProxySettings() {
  const [data, setData] = useState<ProxyDto>(EMPTY);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    setLoading(true);
    getProxy()
      .then(setData)
      .catch(() => undefined)
      .finally(() => setLoading(false));
  }, []);

  const handleSave = async () => {
    setSaving(true);
    try {
      const saved = await updateProxy(data);
      setData(saved);
      Toast.success("已保存并生效");
    } catch {
      // axios 拦截器已提示
    } finally {
      setSaving(false);
    }
  };

  const update = (k: keyof ProxyDto) => (v: string) =>
    setData((d) => ({ ...d, [k]: v }));

  return (
    <div style={{ maxWidth: 720 }}>
      <Title heading={3} style={{ marginBottom: "var(--vc-spacing-lg)" }}>
        网络代理
      </Title>

      <Banner
        type="info"
        description="保存后立即生效（注入环境变量），新发起的模型下载会通过新代理。已在下载中的任务不受影响。"
        style={{ marginBottom: "var(--vc-spacing-lg)" }}
        closeIcon={null}
      />

      <Form labelPosition="top" disabled={loading}>
        <Form.Slot label="HuggingFace 镜像（HF_ENDPOINT）">
          <Input
            value={data.hf_endpoint}
            onChange={update("hf_endpoint")}
            placeholder="https://hf-mirror.com"
          />
          <Text type="tertiary" size="small">
            HF 站直连失败时填镜像地址（如 https://hf-mirror.com）；留空走官方
          </Text>
        </Form.Slot>

        <Form.Slot label="HTTPS 代理（HTTPS_PROXY）">
          <Input
            value={data.https_proxy}
            onChange={update("https_proxy")}
            placeholder="http://10.0.0.1:7890"
          />
        </Form.Slot>

        <Form.Slot label="HTTP 代理（HTTP_PROXY）">
          <Input
            value={data.http_proxy}
            onChange={update("http_proxy")}
            placeholder="http://10.0.0.1:7890"
          />
        </Form.Slot>

        <Form.Slot label="代理排除清单（NO_PROXY）">
          <Input
            value={data.no_proxy}
            onChange={update("no_proxy")}
            placeholder="localhost,127.0.0.1,*.internal"
          />
          <Text type="tertiary" size="small">
            逗号分隔；这些地址不走代理直连
          </Text>
        </Form.Slot>

        <Space style={{ marginTop: "var(--vc-spacing-lg)" }}>
          <Button theme="solid" loading={saving} onClick={handleSave}>
            保存并生效
          </Button>
          <Button onClick={() => setData(EMPTY)} disabled={saving}>
            清空
          </Button>
        </Space>
      </Form>
    </div>
  );
}
