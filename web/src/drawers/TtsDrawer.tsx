import { Form, Radio, Select, Slider, TextArea, Toast, Typography } from "@douyinfe/semi-ui";
import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";

import { api } from "@/api/client";
import { listProviderClasses, listProviders } from "@/api/providers";
import { listVoices } from "@/api/voices";
import { TaskCreationDrawer } from "@/components/TaskCreationDrawer";
import type { Provider, ProviderClassSchema, Voice } from "@/types/api";

const { Text } = Typography;

interface Props {
  visible: boolean;
  onClose: () => void;
  onSuccess: () => void;
}

export function TtsDrawer({ visible, onClose, onSuccess }: Props) {
  const nav = useNavigate();
  const [text, setText] = useState("");
  const [voiceId, setVoiceId] = useState("");
  const [speed, setSpeed] = useState(1.0);
  const [format, setFormat] = useState<"wav" | "mp3" | "ogg">("wav");
  const [providerName, setProviderName] = useState<string>("");
  const [providers, setProviders] = useState<Provider[]>([]);
  const [classes, setClasses] = useState<ProviderClassSchema[]>([]);
  const [voices, setVoices] = useState<Voice[]>([]);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (visible) {
      // 合并 tts + cloning 两 kind 作为候选 Provider
      Promise.all([
        listProviders("tts"),
        listProviders("cloning"),
        listProviderClasses(),
        listVoices(),
      ]).then(([tts, cloning, cls, vs]) => {
        const combined = [...tts, ...cloning].filter((p) => p.enabled);
        setProviders(combined);
        setClasses(cls);
        setVoices(vs);
        // 默认选 is_default Provider（优先 tts 的默认）
        const def =
          combined.find((p) => p.kind === "tts" && p.is_default) ??
          combined.find((p) => p.is_default) ??
          combined[0];
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

  const isCloning = useMemo(() => {
    if (!selectedProvider) return false;
    const s = classes.find((c) => c.class_name === selectedProvider.class_name);
    return !!s?.capabilities?.includes("clone");
  }, [selectedProvider, classes]);

  // 克隆型：列出**所有** cloned voice。zero-shot 模型（VoxCPM/IndexTTS）每次合成
  // 把 reference WAV 当 prompt，模型本身无状态——voice 是跨 Provider 共享的素材，
  // 不再按 v.provider_name 过滤。voice_refs.provider_name 退化为"创建归属"标签。
  const cloneVoices = useMemo(
    () => voices.filter((v) => v.source === "cloned"),
    [voices],
  );

  // 切换到克隆 Provider 时自动挑第一个 voice；切换到非克隆自动设为 Provider 名
  useEffect(() => {
    if (!selectedProvider) {
      setVoiceId("");
      return;
    }
    if (isCloning) {
      if (!cloneVoices.find((v) => v.id === voiceId)) {
        setVoiceId(cloneVoices[0]?.id ?? "");
      }
    } else {
      // 非克隆：voice_id 等于 Provider 名（单模型单音色）
      setVoiceId(selectedProvider.name);
    }
  }, [selectedProvider?.name, isCloning, cloneVoices]);

  const handleSubmit = async () => {
    if (!text.trim()) {
      Toast.warning("请输入文本");
      return;
    }
    if (!selectedProvider) {
      Toast.warning("请选择语音合成 Provider");
      return;
    }
    if (isCloning && !voiceId) {
      Toast.warning("克隆型 Provider 需要先在声纹克隆页创建一个音色");
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
              label: p.is_default
                ? `${p.name}（默认 · ${p.kind === "cloning" ? "克隆" : "预设"}）`
                : `${p.name} · ${p.kind === "cloning" ? "克隆" : "预设"}`,
              value: p.name,
            }))}
            placeholder="先选择 Provider"
          />
        </Form.Slot>

        {isCloning ? (
          <Form.Slot label="音色（克隆）">
            {cloneVoices.length === 0 ? (
              <div
                style={{
                  padding: "var(--vc-spacing-md)",
                  border: "1px dashed var(--vc-color-border)",
                  borderRadius: "var(--vc-radius-sm)",
                  color: "var(--vc-color-text-secondary)",
                }}
              >
                <div>此 Provider 没有可用音色。</div>
                <Text
                  link
                  onClick={() => {
                    onClose();
                    nav("/cloning");
                  }}
                >
                  → 去声纹克隆页创建一个
                </Text>
              </div>
            ) : (
              <Select
                value={voiceId}
                onChange={(v) => setVoiceId(String(v))}
                style={{ width: "100%" }}
                optionList={cloneVoices.map((v) => ({
                  label: v.provider_name
                    ? `${v.id}（来源：${v.provider_name}）`
                    : v.id,
                  value: v.id,
                }))}
                placeholder="选择已克隆的音色"
              />
            )}
          </Form.Slot>
        ) : (
          selectedProvider && (
            <Form.Slot label="音色">
              <Text type="tertiary" size="small">
                此 Provider 为单音色（预设），音色即 Provider 本身：
                <Text code style={{ marginLeft: 4 }}>{selectedProvider.name}</Text>
              </Text>
            </Form.Slot>
          )
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
