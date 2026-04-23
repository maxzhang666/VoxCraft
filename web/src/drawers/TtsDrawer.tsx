import { Form, Radio, Select, Slider, TextArea, Toast } from "@douyinfe/semi-ui";
import { useEffect, useState } from "react";

import { api } from "@/api/client";
import { listProviders } from "@/api/providers";
import { listVoices } from "@/api/voices";
import { TaskCreationDrawer } from "@/components/TaskCreationDrawer";
import type { Provider, Voice } from "@/types/api";

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
  const [provider, setProvider] = useState("");
  const [providers, setProviders] = useState<Provider[]>([]);
  const [voices, setVoices] = useState<Voice[]>([]);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (visible) {
      listProviders("tts").then((d) =>
        setProviders(d.filter((p) => p.enabled))
      );
      listVoices().then((v) => setVoices(v));
    } else {
      setText("");
      setVoiceId("");
      setSpeed(1.0);
      setFormat("wav");
      setProvider("");
    }
  }, [visible]);

  const handleSubmit = async () => {
    if (!text.trim()) {
      Toast.warning("请输入文本");
      return;
    }
    if (!voiceId) {
      Toast.warning("请选择音色");
      return;
    }
    setSubmitting(true);
    try {
      await api.post("/tts", {
        text,
        voice_id: voiceId,
        speed,
        format,
        provider: provider || undefined,
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

        <Form.Slot label="音色">
          <Select
            value={voiceId}
            onChange={(v) => setVoiceId(String(v))}
            style={{ width: "100%" }}
            optionList={voices.map((v) => ({
              label: `${v.id}（${v.language}）`,
              value: v.id,
            }))}
            placeholder="选择音色"
          />
        </Form.Slot>

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
