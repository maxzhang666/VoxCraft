import {
  Form,
  Input,
  InputNumber,
  Select,
  TextArea,
  Toast,
  Typography,
  Upload,
} from "@douyinfe/semi-ui";
import { IconUpload } from "@douyinfe/semi-icons";
import { useEffect, useState } from "react";

import { listProviders } from "@/api/providers";
import { extractVoice } from "@/api/voices";
import { TaskCreationDrawer } from "@/components/TaskCreationDrawer";
import type { Provider } from "@/types/api";

const { Text } = Typography;

interface Props {
  visible: boolean;
  onClose: () => void;
  onSuccess: () => void;
}

// 后端 voices.py 一致的白名单
const ALLOWED_AUDIO = ["wav", "mp3", "m4a", "ogg", "flac", "aac"];
const ALLOWED_VIDEO = ["mp4", "mkv", "mov", "webm", "avi"];
const ALL_EXTS = [...ALLOWED_AUDIO, ...ALLOWED_VIDEO];
const ACCEPT_REF =
  "audio/*,video/*," + ALL_EXTS.map((e) => "." + e).join(",");

export function ExtractVoiceDrawer({ visible, onClose, onSuccess }: Props) {
  const [file, setFile] = useState<File | null>(null);
  const [speakerName, setSpeakerName] = useState("");
  const [provider, setProvider] = useState<string>("");
  // 默认 start=0 / duration=8s（落在 GPT-SoVITS 3-10s 与 VoxCPM 默认推荐区间内）；
  // 用户可改成 null 走"整段"模式（duration 字段留空即可）
  const [startSeconds, setStartSeconds] = useState<number | null>(0);
  const [durationSeconds, setDurationSeconds] = useState<number | null>(8);
  // prompt_text/prompt_lang 与 voice 绑定（每段参考音频独有），不进 Provider 全局
  const [promptText, setPromptText] = useState("");
  const [promptLang, setPromptLang] = useState<string>("auto");
  const [providers, setProviders] = useState<Provider[]>([]);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (visible) {
      listProviders("cloning")
        .then((d) => setProviders(d.filter((p) => p.enabled)))
        .catch(() => undefined);
    } else {
      setFile(null);
      setSpeakerName("");
      setProvider("");
      setStartSeconds(0);
      setDurationSeconds(8);
      setPromptText("");
      setPromptLang("auto");
    }
  }, [visible]);

  const handleSubmit = async () => {
    if (!file) {
      Toast.warning("请上传音频或视频文件");
      return;
    }
    setSubmitting(true);
    try {
      const r = await extractVoice({
        reference: file,
        speaker_name: speakerName.trim() || undefined,
        provider: provider || undefined,
        start_seconds: startSeconds ?? undefined,
        duration_seconds: durationSeconds ?? undefined,
        prompt_text: promptText.trim() || undefined,
        prompt_lang: promptLang || undefined,
      });
      Toast.success(`已添加音色 ${r.voice_id}`);
      onSuccess();
    } catch {
      // axios 拦截器已 Toast
    } finally {
      setSubmitting(false);
    }
  };

  const noProviders = providers.length === 0;

  return (
    <TaskCreationDrawer
      visible={visible}
      title="抽取声纹"
      submitting={submitting}
      submitLabel="开始抽取"
      onClose={onClose}
      onSubmit={handleSubmit}
    >
      <Form labelPosition="top">
        {noProviders && (
          <div
            style={{
              padding: "var(--vc-spacing-md)",
              border: "1px dashed var(--vc-color-warning)",
              borderRadius: "var(--vc-radius-sm)",
              color: "var(--vc-color-warning)",
              marginBottom: "var(--vc-spacing-md)",
            }}
          >
            还没有 cloning 类型的 Provider；请先去「模型管理」创建一个
          </div>
        )}

        <Form.Slot label="参考音频或视频（建议 5–30 秒清晰人声）">
          <Upload
            accept={ACCEPT_REF}
            limit={1}
            disabled={noProviders}
            beforeUpload={({ file }) => {
              const f = file.fileInstance as File;
              const ext = (f.name.split(".").pop() || "").toLowerCase();
              if (!ALL_EXTS.includes(ext)) {
                Toast.warning(
                  `不支持 .${ext}；可用：${ALL_EXTS.join(" / ")}`,
                );
                return { fileInstance: f, status: "validateFail" };
              }
              setFile(f);
              return false;
            }}
            onRemove={() => setFile(null)}
          >
            <div
              style={{
                border: "2px dashed var(--vc-color-border)",
                borderRadius: "var(--vc-radius-sm)",
                padding: "var(--vc-spacing-lg)",
                textAlign: "center",
                color: "var(--vc-color-text-secondary)",
              }}
            >
              <IconUpload /> 点击或拖拽上传
              <div style={{ fontSize: 12, marginTop: 4 }}>
                视频会自动抽取音轨；音频会标准化为 16kHz mono WAV
              </div>
            </div>
          </Upload>
        </Form.Slot>

        <Form.Slot label="切取范围（秒）— 建议 3-10s 内，匹配 VoxCPM / GPT-SoVITS 推理约束">
          <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
            <InputNumber
              value={startSeconds ?? undefined}
              onChange={(v) =>
                setStartSeconds(typeof v === "number" ? v : null)
              }
              min={0}
              step={0.5}
              precision={1}
              suffix="起点 s"
              placeholder="0"
              style={{ width: 130 }}
            />
            <Text type="tertiary" size="small">→</Text>
            <InputNumber
              value={durationSeconds ?? undefined}
              onChange={(v) =>
                setDurationSeconds(typeof v === "number" ? v : null)
              }
              min={0}
              step={0.5}
              precision={1}
              suffix="时长 s"
              placeholder="整段"
              style={{ width: 130 }}
            />
            <Text type="tertiary" size="small">
              留空则保留整段；时长 0/空 = 不裁剪
            </Text>
          </div>
        </Form.Slot>

        <Form.Slot label="参考音频转写（GPT-SoVITS / VoxCPM 1.x 必填；与音色绑定）">
          <TextArea
            value={promptText}
            onChange={setPromptText}
            rows={2}
            maxLength={10000}
            placeholder="参考音频里说的那段话；建议精确转写以获得最佳克隆效果"
          />
          <Text type="tertiary" size="small" style={{ marginTop: 4 }}>
            VoxCPM 2 可留空（基础克隆，不影响）；GPT-SoVITS 必填
          </Text>
        </Form.Slot>

        <Form.Slot label="参考音频语言（GPT-SoVITS 跨语种克隆时必须明确）">
          <Select
            value={promptLang}
            onChange={(v) => setPromptLang(String(v))}
            style={{ width: "100%" }}
            optionList={[
              { label: "自动 (auto)", value: "auto" },
              { label: "中文 (zh)", value: "zh" },
              { label: "英文 (en)", value: "en" },
              { label: "日文 (ja)", value: "ja" },
              { label: "韩文 (ko)", value: "ko" },
              { label: "粤语 (yue)", value: "yue" },
            ]}
          />
        </Form.Slot>

        <Form.Slot label="音色名称（可选，便于识别）">
          <Input
            value={speakerName}
            onChange={setSpeakerName}
            placeholder="如：张三 / 主播 A"
            maxLength={128}
          />
        </Form.Slot>

        <Form.Slot label="归属 Provider（可选，默认用 cloning 默认 Provider）">
          <Select
            value={provider}
            onChange={(v) => setProvider(String(v))}
            placeholder="使用默认"
            showClear
            style={{ width: "100%" }}
            disabled={noProviders}
            optionList={providers.map((p) => ({
              label: p.is_default ? `${p.name}（默认）` : p.name,
              value: p.name,
            }))}
          />
          <Text type="tertiary" size="small" style={{ marginTop: 4 }}>
            该音色后续在 TTS 任务中只能配合归属 Provider 使用
          </Text>
        </Form.Slot>
      </Form>
    </TaskCreationDrawer>
  );
}
