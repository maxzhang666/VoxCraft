import { Button, Descriptions, Modal, Space, Tag, Toast, Typography } from "@douyinfe/semi-ui";

import { StatusTag } from "./StatusTag";
import { JsonViewer } from "./JsonViewer";
import { retryJob } from "@/api/jobs";
import type { Job } from "@/types/api";

const { Text, Paragraph } = Typography;

const KIND_LABEL: Record<string, string> = {
  asr: "语音识别",
  tts: "语音合成",
  clone: "语音克隆",
  separate: "人声分离",
};

interface Props {
  job: Job | null;
  onClose: () => void;
  onRetried?: () => void;
}

export function JobDetailsModal({ job, onClose, onRetried }: Props) {
  const canRetry =
    !!job && (job.status === "failed" || job.status === "cancelled");

  const handleRetry = async () => {
    if (!job) return;
    try {
      await retryJob(job.id);
      Toast.info("已重新入队");
      onClose();
      onRetried?.();
    } catch {
      // 拦截器已提示
    }
  };
  return (
    <Modal
      visible={!!job}
      onCancel={onClose}
      footer={null}
      title={job ? `任务详情 · ${KIND_LABEL[job.kind] ?? job.kind}` : ""}
      width={720}
      centered
    >
      {job && (
        <Space vertical align="start" spacing={12} style={{ width: "100%" }}>
          <Descriptions
            align="left"
            data={[
              { key: "ID", value: <Text code>{job.id}</Text> },
              { key: "状态", value: <StatusTag status={job.status} /> },
              { key: "类型", value: <Tag>{job.kind}</Tag> },
              {
                key: "Provider",
                value: job.provider_name ?? <Text type="tertiary">—</Text>,
              },
              {
                key: "进度",
                value: `${Math.round(job.progress * 100)}%`,
              },
              {
                key: "创建时间",
                value: new Date(job.created_at).toLocaleString("zh-CN"),
              },
              {
                key: "完成时间",
                value: job.finished_at
                  ? new Date(job.finished_at).toLocaleString("zh-CN")
                  : "—",
              },
            ]}
          />

          {job.error_code && (
            <div style={{ width: "100%" }}>
              <Text type="danger" strong>
                错误 · [{job.error_code}]
              </Text>
              <Paragraph
                type="danger"
                style={{ marginTop: 4, whiteSpace: "pre-wrap", wordBreak: "break-word" }}
              >
                {job.error_message ?? "（无消息）"}
              </Paragraph>
            </div>
          )}

          {canRetry && (
            <Button theme="solid" onClick={handleRetry}>
              重试
            </Button>
          )}

          <div style={{ width: "100%" }}>
            <Text strong>请求参数</Text>
            <JsonViewer data={job.request ?? {}} />
          </div>

          {job.result && (
            <div style={{ width: "100%" }}>
              <Text strong>结果</Text>
              <JsonViewer data={job.result} />
            </div>
          )}
        </Space>
      )}
    </Modal>
  );
}
