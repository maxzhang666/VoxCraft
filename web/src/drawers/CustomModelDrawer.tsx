import { Form, Input, Radio, Select, Toast } from "@douyinfe/semi-ui";
import { useEffect, useState } from "react";

import { addCustomModel } from "@/api/modelsLibrary";
import { TaskCreationDrawer } from "@/components/TaskCreationDrawer";
import type { CustomAddRequest } from "@/types/api";

interface Props {
  visible: boolean;
  onClose: () => void;
  onSuccess: () => void;
}

export function CustomModelDrawer({ visible, onClose, onSuccess }: Props) {
  const [key, setKey] = useState("custom_");
  const [source, setSource] = useState<CustomAddRequest["source"]>("hf");
  const [repoId, setRepoId] = useState("");
  const [kind, setKind] = useState<CustomAddRequest["kind"]>("asr");
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (!visible) {
      setKey("custom_");
      setSource("hf");
      setRepoId("");
      setKind("asr");
    }
  }, [visible]);

  const handleSubmit = async () => {
    if (!key.startsWith("custom_") || key.length < 8) {
      Toast.warning("catalog key 必须以 custom_ 开头，且至少 1 个额外字符");
      return;
    }
    if (!repoId.trim()) {
      Toast.warning("repo_id / URL 必填");
      return;
    }
    setSubmitting(true);
    try {
      await addCustomModel({
        catalog_key: key,
        source,
        repo_id: repoId.trim(),
        kind,
      });
      Toast.success("已加入下载队列");
      onSuccess();
    } catch {
      /* interceptor 已 Toast */
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <TaskCreationDrawer
      visible={visible}
      title="添加自定义模型"
      submitting={submitting}
      submitLabel="加入下载队列"
      onClose={onClose}
      onSubmit={handleSubmit}
    >
      <Form labelPosition="top">
        <Form.Slot label="Catalog Key（必须以 custom_ 开头）">
          <Input value={key} onChange={setKey} placeholder="custom_my-whisper" />
        </Form.Slot>

        <Form.Slot label="下载源">
          <Radio.Group
            value={source}
            onChange={(e) => setSource(e.target.value)}
          >
            <Radio value="hf">HuggingFace</Radio>
            <Radio value="ms">ModelScope</Radio>
            <Radio value="url">URL 直下</Radio>
          </Radio.Group>
        </Form.Slot>

        <Form.Slot label={source === "url" ? "下载 URL" : "Repo ID"}>
          <Input
            value={repoId}
            onChange={setRepoId}
            placeholder={
              source === "url"
                ? "https://example.com/model.onnx"
                : "org-name/repo-name"
            }
          />
        </Form.Slot>

        <Form.Slot label="能力类型">
          <Select
            value={kind}
            onChange={(v) => setKind(v as CustomAddRequest["kind"])}
            style={{ width: "100%" }}
            optionList={[
              { label: "语音识别 (ASR)", value: "asr" },
              { label: "语音合成 (TTS)", value: "tts" },
              { label: "语音克隆 (Cloning)", value: "cloning" },
              { label: "人声分离 (Separator)", value: "separator" },
            ]}
          />
        </Form.Slot>
      </Form>
    </TaskCreationDrawer>
  );
}
