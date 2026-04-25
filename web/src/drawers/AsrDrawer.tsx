import {
  Collapsible,
  Form,
  InputNumber,
  Select,
  Switch,
  TextArea,
  Toast,
  Typography,
  Upload,
} from "@douyinfe/semi-ui";
import { IconChevronDown, IconChevronRight, IconUpload } from "@douyinfe/semi-icons";
import { useEffect, useState } from "react";

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

  // ASR 调优字段（与 /api/asr Form 字段一一对应；空值不发，让后端走 Provider 默认）
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [prompt, setPrompt] = useState<string>("");
  const [temperature, setTemperature] = useState<number | undefined>();
  const [beamSize, setBeamSize] = useState<number | undefined>();
  const [vadFilter, setVadFilter] = useState<boolean | undefined>();
  const [conditionPrev, setConditionPrev] = useState<boolean | undefined>();
  const [wordTimestamps, setWordTimestamps] = useState<boolean | undefined>();

  useEffect(() => {
    if (visible) {
      listProviders("asr")
        .then((data) => setProviders(data.filter((p) => p.enabled)))
        .catch(() => undefined);
    } else {
      setFile(null);
      setLanguage("");
      setProvider("");
      setAdvancedOpen(false);
      setPrompt("");
      setTemperature(undefined);
      setBeamSize(undefined);
      setVadFilter(undefined);
      setConditionPrev(undefined);
      setWordTimestamps(undefined);
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
      // 调优字段：未填则不附加，让后端走 Provider config 默认
      if (prompt.trim()) fd.append("prompt", prompt);
      if (temperature !== undefined) fd.append("temperature", String(temperature));
      if (beamSize !== undefined) fd.append("beam_size", String(beamSize));
      if (vadFilter !== undefined) fd.append("vad_filter", String(vadFilter));
      if (conditionPrev !== undefined)
        fd.append("condition_on_previous_text", String(conditionPrev));
      if (wordTimestamps !== undefined)
        fd.append("word_timestamps", String(wordTimestamps));
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

        <div
          onClick={() => setAdvancedOpen(!advancedOpen)}
          style={{
            cursor: "pointer",
            display: "flex",
            alignItems: "center",
            margin: "var(--vc-spacing-md) 0 var(--vc-spacing-sm)",
            color: "var(--vc-color-text-secondary)",
          }}
        >
          {advancedOpen ? <IconChevronDown /> : <IconChevronRight />}
          <span style={{ marginLeft: 4 }}>识别精度调优（可选）</span>
        </div>

        <Collapsible isOpen={advancedOpen}>
          <Form.Slot label="初始 Prompt（领域词汇/风格提示，对齐 OpenAI prompt 字段）">
            <TextArea
              value={prompt}
              onChange={setPrompt}
              placeholder='如"以下是普通话演讲，包含术语：VoxCraft / FastAPI"，可改善专有名词识别'
              rows={2}
              maxCount={1000}
            />
          </Form.Slot>

          <Form.Slot label="温度（0=贪婪可复现；>0 引入采样）">
            <InputNumber
              value={temperature}
              onChange={(v) => setTemperature(v as number | undefined)}
              min={0}
              max={1}
              step={0.1}
              placeholder="留空走 Provider 默认（0.0）"
              style={{ width: "100%" }}
            />
          </Form.Slot>

          <Form.Slot label="Beam 宽度（增大→更准更慢，常用 1~10）">
            <InputNumber
              value={beamSize}
              onChange={(v) => setBeamSize(v as number | undefined)}
              min={1}
              max={20}
              step={1}
              placeholder="留空走 Provider 默认（5）"
              style={{ width: "100%" }}
            />
          </Form.Slot>

          <Form.Slot label="VAD 过滤静音（含背景噪声音频强烈推荐）">
            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <Switch
                checked={vadFilter === true}
                onChange={(v) => setVadFilter(v ? true : undefined)}
              />
              <Text type="tertiary" size="small">
                关闭=走 Provider 默认；开启则启用 Silero VAD 跳过静音段
              </Text>
            </div>
          </Form.Slot>

          <Form.Slot label="上下文延续（长音频出现重复幻觉时建议关闭）">
            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <Switch
                checked={conditionPrev === false}
                onChange={(v) => setConditionPrev(v ? false : undefined)}
              />
              <Text type="tertiary" size="small">
                开启此开关=禁用上下文（避免错误传播）；不开=走 Provider 默认
              </Text>
            </div>
          </Form.Slot>

          <Form.Slot label="输出词级时间戳（视频字幕对齐用，但慢约 30%）">
            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <Switch
                checked={wordTimestamps === true}
                onChange={(v) => setWordTimestamps(v ? true : undefined)}
              />
              <Text type="tertiary" size="small">
                开启后 segment 内含 words 列表（OpenAI verbose_json 同义）
              </Text>
            </div>
          </Form.Slot>

          <Text type="tertiary" size="small" style={{ display: "block", marginTop: 8 }}>
            其他阈值参数（compression_ratio_threshold / log_prob_threshold /
            no_speech_threshold）请到「模型管理」修改 Provider 默认值
          </Text>
        </Collapsible>
      </Form>
    </TaskCreationDrawer>
  );
}
