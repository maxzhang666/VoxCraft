import { Form, Select, Toast, Upload } from "@douyinfe/semi-ui";
import { IconUpload } from "@douyinfe/semi-icons";
import { useEffect, useState } from "react";

import { api } from "@/api/client";
import { listProviders } from "@/api/providers";
import { TaskCreationDrawer } from "@/components/TaskCreationDrawer";
import type { Provider } from "@/types/api";

interface Props {
  visible: boolean;
  onClose: () => void;
  onSuccess: () => void;
}

export function SeparatorDrawer({ visible, onClose, onSuccess }: Props) {
  const [file, setFile] = useState<File | null>(null);
  const [provider, setProvider] = useState("");
  const [providers, setProviders] = useState<Provider[]>([]);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (visible) {
      listProviders("separator").then((d) =>
        setProviders(d.filter((p) => p.enabled))
      );
    } else {
      setFile(null);
      setProvider("");
    }
  }, [visible]);

  const handleSubmit = async () => {
    if (!file) {
      Toast.warning("请先选择音频文件");
      return;
    }
    setSubmitting(true);
    try {
      const fd = new FormData();
      fd.append("audio", file);
      if (provider) fd.append("provider", provider);
      await api.post("/separate", fd);
      Toast.info("已加入队列");
      onSuccess();
    } catch {
      // 拦截器已提示
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <TaskCreationDrawer
      visible={visible}
      title="新建分离"
      submitting={submitting}
      submitLabel="开始分离"
      onClose={onClose}
      onSubmit={handleSubmit}
    >
      <Form labelPosition="top">
        <Form.Slot label="音频/视频文件">
          <Upload
            accept="audio/*,video/*"
            draggable
            limit={1}
            beforeUpload={({ file }) => {
              setFile(file.fileInstance as File);
              return false;
            }}
            onRemove={() => setFile(null)}
          >
            <div
              style={{
                border: "2px dashed var(--vc-color-border)",
                borderRadius: "var(--vc-radius-sm)",
                padding: "var(--vc-spacing-xl)",
                textAlign: "center",
                color: "var(--vc-color-text-secondary)",
              }}
            >
              <IconUpload size="large" />
              <div style={{ marginTop: 8 }}>拖拽或点击上传</div>
            </div>
          </Upload>
        </Form.Slot>

        <Form.Slot label="Provider（可选）">
          <Select
            value={provider}
            onChange={(v) => setProvider(String(v))}
            placeholder="使用默认"
            showClear
            style={{ width: "100%" }}
            optionList={providers.map((p) => ({
              label: p.is_default ? `${p.name}（默认）` : p.name,
              value: p.name,
            }))}
          />
        </Form.Slot>
      </Form>
    </TaskCreationDrawer>
  );
}
