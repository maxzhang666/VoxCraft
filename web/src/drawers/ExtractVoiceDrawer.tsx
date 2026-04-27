import {
  Banner,
  Form,
  Input,
  InputNumber,
  Select,
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
  // 默认 start=0 / duration=8s（落在 GPT-SoVITS 3-10s 推理约束内）；
  // 用户可改成 null 走"整段"模式（duration 字段留空即可）
  const [startSeconds, setStartSeconds] = useState<number | null>(0);
  const [durationSeconds, setDurationSeconds] = useState<number | null>(8);
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
      });
      // 给前端用户讲清楚自动转写到底成没成——这是 GPT-SoVITS / VoxCPM 1.x
      // 等需要参考转写的合成器能不能用这个 voice 的关键
      if (r.transcribed && r.transcript_preview) {
        Toast.success({
          content:
            `已添加音色 ${r.voice_id}（自动转写：「${r.transcript_preview}」）`,
          duration: 6,
        });
      } else if (r.transcribe_warning) {
        Toast.warning({
          content: `音色 ${r.voice_id} 已保存：${r.transcribe_warning}`,
          duration: 8,
        });
      } else {
        Toast.success(`已添加音色 ${r.voice_id}`);
      }
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

        <Banner
          type="info"
          fullMode={false}
          icon={null}
          closeIcon={null}
          description={
            <span style={{ fontSize: 12 }}>
              抽取时会自动用默认 ASR Provider 把参考音频转写为文字（供
              GPT-SoVITS / VoxCPM 1.x 等需要参考转写的合成器使用）。
              请确保「模型管理」里有一个启用并设为默认的 ASR Provider，否则
              生成的音色将无法被这类合成器使用。
            </span>
          }
          style={{ marginBottom: "var(--vc-spacing-md)" }}
        />

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
