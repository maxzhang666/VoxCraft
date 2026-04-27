import {
  Collapsible,
  Form,
  InputNumber,
  Radio,
  Select,
  Slider,
  TextArea,
  Toast,
  Typography,
} from "@douyinfe/semi-ui";
import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";

import { api } from "@/api/client";
import { listProviderClasses, listProviders } from "@/api/providers";
import { listVoices } from "@/api/voices";
import { TaskCreationDrawer } from "@/components/TaskCreationDrawer";
import type {
  Provider,
  ProviderClassSchema,
  TtsGenerationParams,
  Voice,
} from "@/types/api";

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
  // 高级生成参数（每次生成可调，不传走 Provider 默认）。
  // UI 只显示当前 Provider class 实际识别的字段（其他字段填了也会被忽略）。
  const [advOpen, setAdvOpen] = useState(false);
  const [topK, setTopK] = useState<number | null>(null);
  const [topP, setTopP] = useState<number | null>(null);
  const [temperature, setTemperature] = useState<number | null>(null);
  const [textSplitMethod, setTextSplitMethod] = useState<string>("");
  const [textLang, setTextLang] = useState<string>("");
  const [cfgValue, setCfgValue] = useState<number | null>(null);
  const [inferenceTimesteps, setInferenceTimesteps] = useState<number | null>(null);

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
      setAdvOpen(false);
      setTopK(null);
      setTopP(null);
      setTemperature(null);
      setTextSplitMethod("");
      setTextLang("");
      setCfgValue(null);
      setInferenceTimesteps(null);
    }
  }, [visible]);

  const selectedProvider = useMemo(
    () => providers.find((p) => p.name === providerName) ?? null,
    [providers, providerName],
  );

  // Provider class 决定高级面板展示哪些字段：
  // - GPT-SoVITS: top_k / top_p / temperature / text_split_method / text_lang
  // - VoxCPM: cfg_value / inference_timesteps
  // - 其他（Piper / IndexTTS 等）: 不显示高级面板
  const providerFamily = useMemo<"gpt_sovits" | "voxcpm" | "none">(() => {
    const cls = selectedProvider?.class_name ?? "";
    if (cls === "GptSoVitsProvider") return "gpt_sovits";
    if (cls === "VoxCpmCloningProvider") return "voxcpm";
    return "none";
  }, [selectedProvider]);

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
      // 只把当前 Provider 家族识别的字段塞进 generation；其他保留 null
      const generation: TtsGenerationParams = {};
      if (providerFamily === "gpt_sovits") {
        if (topK !== null) generation.top_k = topK;
        if (topP !== null) generation.top_p = topP;
        if (temperature !== null) generation.temperature = temperature;
        if (textSplitMethod) generation.text_split_method = textSplitMethod;
        if (textLang) generation.text_lang = textLang;
      } else if (providerFamily === "voxcpm") {
        if (cfgValue !== null) generation.cfg_value = cfgValue;
        if (inferenceTimesteps !== null) generation.inference_timesteps = inferenceTimesteps;
      }
      await api.post("/tts", {
        text,
        voice_id: voiceId,
        speed,
        format,
        provider: providerName,
        generation: Object.keys(generation).length > 0 ? generation : undefined,
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

        {/* 高级生成参数：每次生成可调；不传走 Provider 默认。
            按当前 Provider class 动态展示——只显示该模型实际识别的字段。
            选 Piper / IndexTTS 等不暴露 generation 参数的 Provider 时，整块隐藏。 */}
        {providerFamily !== "none" && (
          <Form.Slot label="">
            <Text
              link
              onClick={() => setAdvOpen((v) => !v)}
              style={{ cursor: "pointer" }}
            >
              {advOpen
                ? "▾ 收起高级参数"
                : providerFamily === "gpt_sovits"
                  ? "▸ 高级生成参数（采样 / 切分 / 目标语言）"
                  : "▸ 高级生成参数（CFG / 推理步数）"}
            </Text>
            <Collapsible isOpen={advOpen} keepDOM>
              <div
                style={{
                  display: "grid",
                  gridTemplateColumns: "1fr 1fr",
                  gap: 12,
                  marginTop: 8,
                  padding: "var(--vc-spacing-md)",
                  background: "var(--vc-color-fill-1)",
                  borderRadius: "var(--vc-radius-sm)",
                }}
              >
                {providerFamily === "gpt_sovits" && (
                  <>
                    <div>
                      <Text type="tertiary" size="small">目标语言 text_lang</Text>
                      <Select
                        value={textLang}
                        onChange={(v) => setTextLang(String(v))}
                        showClear
                        placeholder="默认 zh"
                        optionList={[
                          { label: "中文 (zh)", value: "zh" },
                          { label: "英文 (en)", value: "en" },
                          { label: "日文 (ja)", value: "ja" },
                          { label: "韩文 (ko)", value: "ko" },
                          { label: "粤语 (yue)", value: "yue" },
                          { label: "auto（多语种自动切）", value: "auto" },
                        ]}
                        style={{ width: "100%" }}
                      />
                    </div>
                    <div>
                      <Text type="tertiary" size="small">切分 text_split_method</Text>
                      <Select
                        value={textSplitMethod}
                        onChange={(v) => setTextSplitMethod(String(v))}
                        showClear
                        placeholder="默认 cut5"
                        optionList={[
                          { label: "cut0 (不切)", value: "cut0" },
                          { label: "cut1", value: "cut1" },
                          { label: "cut2", value: "cut2" },
                          { label: "cut3", value: "cut3" },
                          { label: "cut4", value: "cut4" },
                          { label: "cut5 (按标点)", value: "cut5" },
                        ]}
                        style={{ width: "100%" }}
                      />
                    </div>
                    <div>
                      <Text type="tertiary" size="small">采样 top_k</Text>
                      <InputNumber
                        value={topK ?? undefined}
                        onChange={(v) => setTopK(typeof v === "number" ? v : null)}
                        min={1}
                        max={100}
                        placeholder="默认 15"
                        style={{ width: "100%" }}
                      />
                    </div>
                    <div>
                      <Text type="tertiary" size="small">采样 top_p</Text>
                      <InputNumber
                        value={topP ?? undefined}
                        onChange={(v) => setTopP(typeof v === "number" ? v : null)}
                        min={0.01}
                        max={1}
                        step={0.05}
                        precision={2}
                        placeholder="默认 1.0"
                        style={{ width: "100%" }}
                      />
                    </div>
                    <div>
                      <Text type="tertiary" size="small">温度 temperature</Text>
                      <InputNumber
                        value={temperature ?? undefined}
                        onChange={(v) =>
                          setTemperature(typeof v === "number" ? v : null)
                        }
                        min={0.01}
                        max={2}
                        step={0.05}
                        precision={2}
                        placeholder="默认 1.0"
                        style={{ width: "100%" }}
                      />
                    </div>
                  </>
                )}
                {providerFamily === "voxcpm" && (
                  <>
                    <div>
                      <Text type="tertiary" size="small">CFG 引导强度 cfg_value</Text>
                      <InputNumber
                        value={cfgValue ?? undefined}
                        onChange={(v) =>
                          setCfgValue(typeof v === "number" ? v : null)
                        }
                        min={0.5}
                        max={5}
                        step={0.1}
                        precision={1}
                        placeholder="默认 2.0"
                        style={{ width: "100%" }}
                      />
                    </div>
                    <div>
                      <Text type="tertiary" size="small">推理步数 inference_timesteps</Text>
                      <InputNumber
                        value={inferenceTimesteps ?? undefined}
                        onChange={(v) =>
                          setInferenceTimesteps(typeof v === "number" ? v : null)
                        }
                        min={1}
                        max={100}
                        placeholder="默认 10"
                        style={{ width: "100%" }}
                      />
                    </div>
                  </>
                )}
              </div>
            </Collapsible>
          </Form.Slot>
        )}
      </Form>
    </TaskCreationDrawer>
  );
}
