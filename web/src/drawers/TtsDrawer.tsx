import {
  Form,
  Radio,
  Select,
  Slider,
  TextArea,
  Toast,
  Typography,
} from "@douyinfe/semi-ui";
import { useEffect, useMemo, useState } from "react";

import { api } from "@/api/client";
import { listProviders } from "@/api/providers";
import { TaskCreationDrawer } from "@/components/TaskCreationDrawer";
import type { Provider } from "@/types/api";

const { Text } = Typography;

interface Props {
  visible: boolean;
  onClose: () => void;
  onSuccess: () => void;
}

export function TtsDrawer({ visible, onClose, onSuccess }: Props) {
  const [text, setText] = useState("");
  const [voiceId, setVoiceId] = useState("");
  const [speed, setSpeed] = useState(1.0);
  const [format, setFormat] = useState<"wav" | "mp3" | "ogg">("wav");
  const [providerName, setProviderName] = useState<string>("");
  const [providers, setProviders] = useState<Provider[]>([]);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (visible) {
      listProviders("tts").then((tts) => {
        const enabled = tts.filter((p) => p.enabled);
        setProviders(enabled);
        const def = enabled.find((p) => p.is_default) ?? enabled[0];
        if (def) setProviderName(def.name);
      });
    } else {
      setText("");
      setVoiceId("");
      setSpeed(1.0);
      setFormat("wav");
      setProviderName("");
    }
  }, [visible]);

  const selectedProvider = useMemo(
    () => providers.find((p) => p.name === providerName) ?? null,
    [providers, providerName],
  );

  // 预设 TTS（Piper 等）：voice_id 等于 Provider 名（单模型单音色）。
  // 切换 Provider 时自动同步 voice_id。
  useEffect(() => {
    setVoiceId(selectedProvider ? selectedProvider.name : "");
  }, [selectedProvider?.name]);

  const handleSubmit = async () => {
    if (!text.trim()) {
      Toast.warning("请输入文本");
      return;
    }
    if (!selectedProvider) {
      Toast.warning("请选择语音合成 Provider");
      return;
    }
    setSubmitting(true);
    try {
      await api.post("/tts", {
        text,
        voice_id: voiceId,
        speed,
        format,
        provider: providerName,
      });
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
      title="新建合成"
      submitting={submitting}
      submitLabel="开始合成"
      onClose={onClose}
      onSubmit={handleSubmit}
    >
      <Form labelPosition="top">
        <Form.Slot label="文本">
          <TextArea
            value={text}
            onChange={setText}
            rows={6}
            maxLength={10000}
            showClear
            placeholder="输入要合成的文本（最多 10000 字符）"
          />
        </Form.Slot>

        <Form.Slot label="Provider（引擎）">
          <Select
            value={providerName}
            onChange={(v) => setProviderName(String(v))}
            style={{ width: "100%" }}
            optionList={providers.map((p) => ({
              label: p.is_default ? `${p.name}（默认）` : p.name,
              value: p.name,
            }))}
            placeholder="先选择 Provider"
          />
        </Form.Slot>

        {selectedProvider && (
          <Form.Slot label="音色">
            <Text type="tertiary" size="small">
              此 Provider 为单音色（预设），音色即 Provider 本身：
              <Text code style={{ marginLeft: 4 }}>{selectedProvider.name}</Text>
            </Text>
          </Form.Slot>
        )}

        <Form.Slot label={`语速 ${speed.toFixed(1)}x`}>
          <Slider
            value={speed}
            onChange={(v) => {
              if (v === undefined) return;
              setSpeed(Array.isArray(v) ? v[0] : v);
            }}
            min={0.5}
            max={2}
            step={0.1}
            marks={{ 0.5: "0.5x", 1: "1x", 2: "2x" }}
          />
        </Form.Slot>

        <Form.Slot label="格式">
          <Radio.Group
            value={format}
            onChange={(e) => setFormat(e.target.value)}
          >
            <Radio value="wav">WAV</Radio>
            <Radio value="mp3">MP3</Radio>
            <Radio value="ogg">OGG</Radio>
          </Radio.Group>
        </Form.Slot>
      </Form>
    </TaskCreationDrawer>
  );
}
