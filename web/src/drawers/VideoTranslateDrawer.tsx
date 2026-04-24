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
import { useEffect, useMemo, useState } from "react";

import { listLlms } from "@/api/llm";
import { listProviderClasses, listProviders } from "@/api/providers";
import { submitVideoTranslate } from "@/api/videoTranslate";
import { TaskCreationDrawer } from "@/components/TaskCreationDrawer";
import type {
  AlignMode,
  LlmProvider,
  Provider,
  ProviderClassSchema,
  SubtitleMode,
} from "@/types/api";

const { Text } = Typography;

const LANG_OPTIONS = [
  { label: "中文 (zh)", value: "zh" },
  { label: "英文 (en)", value: "en" },
  { label: "日语 (ja)", value: "ja" },
  { label: "韩语 (ko)", value: "ko" },
  { label: "法语 (fr)", value: "fr" },
  { label: "德语 (de)", value: "de" },
  { label: "西班牙语 (es)", value: "es" },
];

const SUBTITLE_MODE_OPTIONS: { label: string; value: SubtitleMode }[] = [
  { label: "软字幕（播放器可开关，不重编码）", value: "soft" },
  { label: "硬字幕（烧录进画面，需重编码）", value: "hard" },
  { label: "不嵌字幕", value: "none" },
];

const ALIGN_MODE_OPTIONS: { label: string; value: AlignMode }[] = [
  { label: "elastic（按原起始点 + 语速压缩）", value: "elastic" },
  { label: "natural（译文自然时长）", value: "natural" },
  { label: "strict（强制贴合原段时长）", value: "strict" },
];

interface Props {
  visible: boolean;
  onClose: () => void;
  onSuccess: () => void;
}

export function VideoTranslateDrawer({ visible, onClose, onSuccess }: Props) {
  const [file, setFile] = useState<File | null>(null);
  const [targetLang, setTargetLang] = useState<string>("zh");
  const [sourceLang, setSourceLang] = useState<string | undefined>();
  const [subtitleMode, setSubtitleMode] = useState<SubtitleMode>("soft");
  const [cloneVoice, setCloneVoice] = useState<boolean>(true);
  const [alignMode, setAlignMode] = useState<AlignMode>("elastic");
  const [alignMaxSpeedup, setAlignMaxSpeedup] = useState<number>(1.3);
  const [asrProviderId, setAsrProviderId] = useState<number | undefined>();
  const [ttsProviderId, setTtsProviderId] = useState<number | undefined>();
  const [llmProviderId, setLlmProviderId] = useState<number | undefined>();
  const [systemPrompt, setSystemPrompt] = useState<string>("");
  const [maxInflation, setMaxInflation] = useState<number>(5);
  const [advancedOpen, setAdvancedOpen] = useState(false);

  const [asrProviders, setAsrProviders] = useState<Provider[]>([]);
  const [ttsProviders, setTtsProviders] = useState<Provider[]>([]);
  const [llmProviders, setLlmProviders] = useState<LlmProvider[]>([]);
  const [classSchemas, setClassSchemas] = useState<ProviderClassSchema[]>([]);
  const [submitting, setSubmitting] = useState(false);

  const reset = () => {
    setFile(null);
    setTargetLang("zh");
    setSourceLang(undefined);
    setSubtitleMode("soft");
    setCloneVoice(true);
    setAlignMode("elastic");
    setAlignMaxSpeedup(1.3);
    setAsrProviderId(undefined);
    setTtsProviderId(undefined);
    setLlmProviderId(undefined);
    setSystemPrompt("");
    setMaxInflation(5);
    setAdvancedOpen(false);
  };

  useEffect(() => {
    if (!visible) {
      reset();
      return;
    }
    Promise.all([
      listProviders("asr"),
      listProviders("tts"),
      listProviders("cloning"),
      listLlms(),
      listProviderClasses(),
    ])
      .then(([asr, tts, cloning, llms, schemas]) => {
        setAsrProviders(asr.filter((p) => p.enabled));
        setTtsProviders([...tts, ...cloning].filter((p) => p.enabled));
        setLlmProviders(llms.filter((p) => p.enabled));
        setClassSchemas(schemas);
      })
      .catch(() => undefined);
  }, [visible]);

  const isCloneCapable = useMemo(() => {
    return (classSchema: string | undefined) => {
      if (!classSchema) return false;
      const s = classSchemas.find((c) => c.class_name === classSchema);
      return !!s?.capabilities?.includes("clone");
    };
  }, [classSchemas]);

  const selectedTts = useMemo(
    () => ttsProviders.find((p) => p.id === ttsProviderId),
    [ttsProviders, ttsProviderId],
  );

  const cloneUnsupported =
    cloneVoice && selectedTts && !isCloneCapable(selectedTts.class_name);

  const handleSubmit = async () => {
    if (!file) {
      Toast.warning("请先选择视频或音频文件");
      return;
    }
    if (!targetLang.trim()) {
      Toast.warning("请填写目标语言");
      return;
    }
    if (cloneUnsupported) {
      Toast.warning(
        `${selectedTts?.name} 不支持克隆，请关闭克隆或换一个支持克隆的 TTS`,
      );
      return;
    }
    setSubmitting(true);
    try {
      await submitVideoTranslate({
        source_file: file,
        target_lang: targetLang,
        source_lang: sourceLang || undefined,
        subtitle_mode: subtitleMode,
        clone_voice: cloneVoice,
        align_mode: alignMode,
        align_max_speedup: alignMaxSpeedup,
        asr_provider_id: asrProviderId,
        tts_provider_id: ttsProviderId,
        llm_provider_id: llmProviderId,
        system_prompt: systemPrompt.trim() || undefined,
        translate_max_inflation: maxInflation,
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
      title="新建视频翻译"
      submitting={submitting}
      submitLabel="提交翻译"
      onClose={onClose}
      onSubmit={handleSubmit}
    >
      <Form labelPosition="top">
        <Form.Slot label="视频或音频文件">
          <Upload
            accept="video/*,audio/*"
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
              <Text type="tertiary" size="small" style={{ marginTop: 4 }}>
                支持 mp4/mkv/webm/mov 等视频，wav/mp3/m4a 等音频
              </Text>
            </div>
          </Upload>
        </Form.Slot>

        <Form.Slot label="目标语言">
          <Select
            value={targetLang}
            onChange={(v) => setTargetLang(String(v))}
            optionList={LANG_OPTIONS}
            style={{ width: "100%" }}
          />
        </Form.Slot>

        <Form.Slot label="源语言（可选，留空让 ASR 自动识别）">
          <Select
            value={sourceLang}
            onChange={(v) => setSourceLang(v ? String(v) : undefined)}
            optionList={LANG_OPTIONS}
            placeholder="自动检测"
            showClear
            style={{ width: "100%" }}
          />
        </Form.Slot>

        <Form.Slot label="字幕嵌入方式（仅对视频输入生效）">
          <Select
            value={subtitleMode}
            onChange={(v) => setSubtitleMode(v as SubtitleMode)}
            optionList={SUBTITLE_MODE_OPTIONS}
            style={{ width: "100%" }}
          />
        </Form.Slot>

        <Form.Slot label="声纹克隆">
          <div
            style={{ display: "flex", alignItems: "center", gap: 8 }}
          >
            <Switch checked={cloneVoice} onChange={setCloneVoice} />
            <Text type="tertiary" size="small">
              开启后用原说话人音色合成；需要支持克隆的 TTS Provider
            </Text>
          </div>
          {cloneUnsupported && (
            <Text type="danger" size="small" style={{ marginTop: 4 }}>
              所选 TTS Provider 不支持克隆
            </Text>
          )}
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
          <span style={{ marginLeft: 4 }}>高级选项</span>
        </div>

        <Collapsible isOpen={advancedOpen}>
          <Form.Slot label="时间轴对齐策略">
            <Select
              value={alignMode}
              onChange={(v) => setAlignMode(v as AlignMode)}
              optionList={ALIGN_MODE_OPTIONS}
              style={{ width: "100%" }}
            />
          </Form.Slot>

          {alignMode === "elastic" && (
            <Form.Slot label="最大语速压缩倍数（elastic 专用）">
              <InputNumber
                value={alignMaxSpeedup}
                onChange={(v) => setAlignMaxSpeedup(Number(v))}
                min={1}
                max={2}
                step={0.1}
                style={{ width: "100%" }}
              />
            </Form.Slot>
          )}

          <Form.Slot label="ASR Provider（可选）">
            <Select
              value={asrProviderId}
              onChange={(v) => setAsrProviderId(v ? Number(v) : undefined)}
              placeholder="使用默认"
              showClear
              style={{ width: "100%" }}
              optionList={asrProviders.map((p) => ({
                label: p.is_default ? `${p.name}（默认）` : p.name,
                value: p.id,
              }))}
            />
          </Form.Slot>

          <Form.Slot label="TTS Provider（可选）">
            <Select
              value={ttsProviderId}
              onChange={(v) => setTtsProviderId(v ? Number(v) : undefined)}
              placeholder="使用默认"
              showClear
              style={{ width: "100%" }}
              optionList={ttsProviders.map((p) => {
                const canClone = isCloneCapable(p.class_name);
                return {
                  label: `${p.is_default ? p.name + "（默认）" : p.name}${
                    canClone ? " · 支持克隆" : ""
                  }`,
                  value: p.id,
                };
              })}
            />
          </Form.Slot>

          <Form.Slot label="LLM Provider（翻译用，可选）">
            <Select
              value={llmProviderId}
              onChange={(v) => setLlmProviderId(v ? Number(v) : undefined)}
              placeholder="使用默认"
              showClear
              style={{ width: "100%" }}
              optionList={llmProviders.map((p) => ({
                label: p.is_default ? `${p.name}（默认）` : p.name,
                value: p.id,
              }))}
            />
          </Form.Slot>

          <Form.Slot label="System Prompt 覆盖（可选，≤ 2000 字符）">
            <TextArea
              value={systemPrompt}
              onChange={setSystemPrompt}
              placeholder="留空使用内置默认 prompt；自定义内容会拼在护栏前面"
              rows={3}
              maxCount={2000}
            />
          </Form.Slot>

          <Form.Slot label="翻译膨胀上限（LLM 输出超原文多少倍判为降级）">
            <InputNumber
              value={maxInflation}
              onChange={(v) => setMaxInflation(Number(v))}
              min={0}
              max={20}
              step={0.5}
              style={{ width: "100%" }}
            />
            <Text type="tertiary" size="small" style={{ marginTop: 4 }}>
              默认 5.0 容纳常规语义膨胀；设 0 完全关闭此检查（仍保留空/markdown/元信息三项）
            </Text>
          </Form.Slot>
        </Collapsible>
      </Form>
    </TaskCreationDrawer>
  );
}
