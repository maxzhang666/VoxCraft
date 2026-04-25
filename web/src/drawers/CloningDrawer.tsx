import {
  Form,
  Input,
  Radio,
  RadioGroup,
  Select,
  TextArea,
  Toast,
  Typography,
  Upload,
} from "@douyinfe/semi-ui";
import { IconUpload } from "@douyinfe/semi-icons";
import { useEffect, useMemo, useState } from "react";

import { api } from "@/api/client";
import { listProviders } from "@/api/providers";
import { listVoices } from "@/api/voices";
import { TaskCreationDrawer } from "@/components/TaskCreationDrawer";
import type { Provider, Voice } from "@/types/api";

const { Text } = Typography;

interface Props {
  visible: boolean;
  onClose: () => void;
  onSuccess: () => void;
}

// 参考音频白名单：mp4 等视频/容器格式不支持（OS 文件对话框 audio/* 过滤不严，
// 用户能误选；用扩展名兜底 + Toast 给明确提示）
const ALLOWED_AUDIO_EXTS = ["wav", "mp3", "m4a", "ogg", "flac", "aac"];
const ACCEPT_AUDIO =
  "audio/wav,audio/mpeg,audio/mp3,audio/ogg,audio/flac,audio/x-m4a,audio/aac," +
  ALLOWED_AUDIO_EXTS.map((e) => "." + e).join(",");

type Mode = "upload" | "existing";

export function CloningDrawer({ visible, onClose, onSuccess }: Props) {
  // mode：选择音色来源——upload=上传新参考音频走 /tts/clone；existing=用已有音色走 /tts
  const [mode, setMode] = useState<Mode>("upload");
  const [refFile, setRefFile] = useState<File | null>(null);
  const [text, setText] = useState("");
  const [speakerName, setSpeakerName] = useState("");
  const [provider, setProvider] = useState("");
  const [voiceId, setVoiceId] = useState("");
  const [providers, setProviders] = useState<Provider[]>([]);
  const [voices, setVoices] = useState<Voice[]>([]);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (visible) {
      Promise.all([listProviders("cloning"), listVoices()])
        .then(([ps, vs]) => {
          setProviders(ps.filter((p) => p.enabled));
          // preset + cloned 都可选——UI 标签区分；preset 走 Piper 等单音色 Provider，
          // cloned 走 voice_refs；后端 worker 会按 voice_id 反查 ref_path
          setVoices(vs);
        })
        .catch(() => undefined);
    } else {
      setMode("upload");
      setRefFile(null);
      setText("");
      setSpeakerName("");
      setProvider("");
      setVoiceId("");
    }
  }, [visible]);

  // 切换 existing 时若 voiceId 还未选，挑第一个；不强制覆盖 Provider——
  // voice 是跨 Provider 共享素材，用户自由选搭配的 cloning 模型
  const selectedVoice = useMemo(
    () => voices.find((v) => v.id === voiceId) ?? null,
    [voices, voiceId],
  );
  useEffect(() => {
    if (mode === "existing" && voices.length > 0 && !voiceId) {
      setVoiceId(voices[0].id);
    }
  }, [mode, voices, voiceId]);

  const handleSubmit = async () => {
    if (!text.trim()) {
      Toast.warning("请输入要合成的文本");
      return;
    }
    setSubmitting(true);
    try {
      if (mode === "upload") {
        if (!refFile) {
          Toast.warning("请上传参考音频");
          return;
        }
        const fd = new FormData();
        fd.append("reference_audio", refFile);
        fd.append("text", text);
        if (speakerName) fd.append("speaker_name", speakerName);
        if (provider) fd.append("provider", provider);
        await api.post("/tts/clone", fd);
        Toast.info("已加入克隆队列");
      } else {
        if (!voiceId) {
          Toast.warning("请选择已有音色");
          return;
        }
        // 走 /api/tts；声音色已存在则不需要再 clone，复用 voice_id 直接合成
        await api.post("/tts", {
          text,
          voice_id: voiceId,
          provider: provider || selectedVoice?.provider_name || undefined,
        });
        Toast.info("已加入合成队列（在 TTS 任务页查看）");
      }
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
      title="新建克隆"
      submitting={submitting}
      submitLabel={mode === "upload" ? "开始克隆" : "开始合成"}
      onClose={onClose}
      onSubmit={handleSubmit}
    >
      <Form labelPosition="top">
        <Form.Slot label="音色来源">
          <RadioGroup
            value={mode}
            onChange={(e) => setMode(e.target.value as Mode)}
            type="button"
          >
            <Radio value="upload">上传新参考音频</Radio>
            <Radio value="existing" disabled={voices.length === 0}>
              使用已有音色
              {voices.length === 0 ? "（暂无；请先在「我的音色」抽取）" : ""}
            </Radio>
          </RadioGroup>
        </Form.Slot>

        {mode === "upload" ? (
          <>
            <Form.Slot label="参考音频（3-30 秒）">
              <Upload
                accept={ACCEPT_AUDIO}
                limit={1}
                beforeUpload={({ file }) => {
                  const f = file.fileInstance as File;
                  const ext = (f.name.split(".").pop() || "").toLowerCase();
                  if (!ALLOWED_AUDIO_EXTS.includes(ext)) {
                    Toast.warning(
                      `参考声纹仅支持 ${ALLOWED_AUDIO_EXTS.join(" / ")}；不接受视频或容器格式`,
                    );
                    return { fileInstance: f, status: "validateFail" };
                  }
                  setRefFile(f);
                  return false;
                }}
                onRemove={() => setRefFile(null)}
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
                  <IconUpload /> 点击上传参考声纹
                  <div style={{ fontSize: 12, marginTop: 4 }}>
                    支持 {ALLOWED_AUDIO_EXTS.join(" / ")}；视频文件请先抽取音轨
                  </div>
                </div>
              </Upload>
            </Form.Slot>

            <Form.Slot label="音色名称（可选）">
              <Input
                value={speakerName}
                onChange={setSpeakerName}
                placeholder="便于后续识别，如 张三"
              />
            </Form.Slot>
          </>
        ) : (
          <Form.Slot label="选择已有音色">
            <Select
              value={voiceId}
              onChange={(v) => setVoiceId(String(v))}
              style={{ width: "100%" }}
              optionList={voices.map((v) => ({
                label:
                  v.source === "cloned"
                    ? `🎵 ${v.id}（来源：${v.provider_name}）`
                    : `🔈 ${v.id}（预设 · ${v.provider_name}）`,
                value: v.id,
              }))}
              placeholder="选择音色"
            />
            {selectedVoice?.sample_url && (
              <audio
                controls
                src={selectedVoice.sample_url}
                style={{ width: "100%", marginTop: 8 }}
              />
            )}
          </Form.Slot>
        )}

        <Form.Slot label="合成文本">
          <TextArea
            value={text}
            onChange={setText}
            rows={4}
            maxLength={10000}
            placeholder="用此音色合成这段文字"
          />
        </Form.Slot>

        <Form.Slot label="Provider（可选）">
          <Select
            value={provider}
            onChange={(v) => setProvider(String(v))}
            placeholder={
              mode === "existing" && selectedVoice
                ? `留空走音色来源 ${selectedVoice.provider_name}`
                : "使用默认"
            }
            showClear
            style={{ width: "100%" }}
            optionList={providers.map((p) => ({
              label: p.is_default ? `${p.name}（默认）` : p.name,
              value: p.name,
            }))}
          />
          {mode === "existing" && (
            <Text type="tertiary" size="small" style={{ marginTop: 4 }}>
              音色是跨 Provider 共享的素材；可以选其他 cloning Provider 跑同一段参考
            </Text>
          )}
        </Form.Slot>
      </Form>
    </TaskCreationDrawer>
  );
}
