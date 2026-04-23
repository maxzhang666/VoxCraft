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

const LANG_OPTIONS = [
  { label: "自动检测", value: "" },
  { label: "中文", value: "zh" },
  { label: "英文", value: "en" },
  { label: "日语", value: "ja" },
  { label: "韩语", value: "ko" },
];

export function AsrDrawer({ visible, onClose, onSuccess }: Props) {
  const [file, setFile] = useState<File | null>(null);
  const [language, setLanguage] = useState<string>("");
  const [provider, setProvider] = useState<string>("");
  const [providers, setProviders] = useState<Provider[]>([]);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (visible) {
      listProviders("asr")
        .then((data) => setProviders(data.filter((p) => p.enabled)))
        .catch(() => undefined);
    } else {
      setFile(null);
      setLanguage("");
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
      if (language) fd.append("language", language);
      if (provider) fd.append("provider", provider);
      await api.post("/asr", fd);
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
      title="新建转录"
      submitting={submitting}
      submitLabel="开始转录"
      onClose={onClose}
      onSubmit={handleSubmit}
    >
      <Form labelPosition="top">
        <Form.Slot label="音频文件">
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

        <Form.Slot label="语言">
          <Select
            value={language}
            onChange={(v) => setLanguage(String(v))}
            optionList={LANG_OPTIONS}
            style={{ width: "100%" }}
          />
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
