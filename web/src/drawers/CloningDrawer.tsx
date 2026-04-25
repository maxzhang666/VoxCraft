import { Form, Input, Select, TextArea, Toast, Upload } from "@douyinfe/semi-ui";
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

// 参考音频白名单：mp4 等视频/容器格式不支持（OS 文件对话框 audio/* 过滤不严，
// 用户能误选；用扩展名兜底 + Toast 给明确提示）
const ALLOWED_AUDIO_EXTS = ["wav", "mp3", "m4a", "ogg", "flac", "aac"];
const ACCEPT_AUDIO =
  "audio/wav,audio/mpeg,audio/mp3,audio/ogg,audio/flac,audio/x-m4a,audio/aac," +
  ALLOWED_AUDIO_EXTS.map((e) => "." + e).join(",");

export function CloningDrawer({ visible, onClose, onSuccess }: Props) {
  const [refFile, setRefFile] = useState<File | null>(null);
  const [text, setText] = useState("");
  const [speakerName, setSpeakerName] = useState("");
  const [provider, setProvider] = useState("");
  const [providers, setProviders] = useState<Provider[]>([]);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (visible) {
      listProviders("cloning").then((d) =>
        setProviders(d.filter((p) => p.enabled))
      );
    } else {
      setRefFile(null);
      setText("");
      setSpeakerName("");
      setProvider("");
    }
  }, [visible]);

  const handleSubmit = async () => {
    if (!refFile) {
      Toast.warning("请上传参考音频");
      return;
    }
    if (!text.trim()) {
      Toast.warning("请输入要合成的文本");
      return;
    }
    setSubmitting(true);
    try {
      const fd = new FormData();
      fd.append("reference_audio", refFile);
      fd.append("text", text);
      if (speakerName) fd.append("speaker_name", speakerName);
      if (provider) fd.append("provider", provider);
      await api.post("/tts/clone", fd);
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
      title="新建克隆"
      submitting={submitting}
      submitLabel="开始克隆"
      onClose={onClose}
      onSubmit={handleSubmit}
    >
      <Form labelPosition="top">
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

        <Form.Slot label="合成文本">
          <TextArea
            value={text}
            onChange={setText}
            rows={4}
            maxLength={10000}
            placeholder="用克隆出的音色合成这段文字"
          />
        </Form.Slot>

        <Form.Slot label="音色名称（可选）">
          <Input
            value={speakerName}
            onChange={setSpeakerName}
            placeholder="便于后续识别，如 张三"
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
