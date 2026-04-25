import { Button, Card, Popconfirm, Progress, Space, Toast, Typography } from "@douyinfe/semi-ui";
import dayjs from "dayjs";
import relativeTime from "dayjs/plugin/relativeTime";
import "dayjs/locale/zh-cn";

import type { Job } from "@/types/api";
import { jobOutputUrl, jobPreviewUrl, retryJob } from "@/api/jobs";
import { JobBadges } from "./JobBadges";
import { StatusTag } from "./StatusTag";

dayjs.extend(relativeTime);
dayjs.locale("zh-cn");

const { Text } = Typography;

interface Props {
  job: Job;
  onDelete?: (id: string) => void;
  onViewDetails?: (job: Job) => void;
}

async function handleRetry(id: string) {
  try {
    await retryJob(id);
    Toast.info("已重新入队");
  } catch {
    // 拦截器已提示
  }
}

function DeleteButton({ id, onDelete }: { id: string; onDelete?: (id: string) => void }) {
  return (
    <Popconfirm
      title="确认删除此任务？"
      content="原始上传与产物文件将一并清除，不可恢复。"
      okText="删除"
      okType="danger"
      cancelText="取消"
      position="topRight"
      onConfirm={() => onDelete?.(id)}
    >
      <Button size="small" type="danger">
        删除
      </Button>
    </Popconfirm>
  );
}

function KindActions({ job, onDelete }: Props) {
  const disabled = job.status !== "succeeded";
  switch (job.kind) {
    case "asr":
      return (
        <Space>
          <DeleteButton id={job.id} onDelete={onDelete} />
        </Space>
      );
    case "tts":
    case "clone":
      return (
        <Space>
          {!disabled && (
            <audio controls src={jobPreviewUrl(job.id)} style={{ height: 28 }} />
          )}
          <Button
            size="small"
            disabled={disabled}
            onClick={() => window.open(jobOutputUrl(job.id), "_blank")}
          >
            下载
          </Button>
          <DeleteButton id={job.id} onDelete={onDelete} />
        </Space>
      );
    case "separate":
      return (
        <Space>
          <Button
            size="small"
            disabled={disabled}
            onClick={() =>
              window.open(jobOutputUrl(job.id, "vocals"), "_blank")
            }
          >
            人声
          </Button>
          <Button
            size="small"
            disabled={disabled}
            onClick={() =>
              window.open(jobOutputUrl(job.id, "instrumental"), "_blank")
            }
          >
            BGM
          </Button>
          <DeleteButton id={job.id} onDelete={onDelete} />
        </Space>
      );
    case "video_translate": {
      const extras = job.output_extras ?? {};
      const hasVideo = !!extras["video"];
      return (
        <Space>
          <Button
            size="small"
            disabled={disabled}
            onClick={() =>
              window.open(jobOutputUrl(job.id, "subtitle"), "_blank")
            }
          >
            字幕
          </Button>
          <Button
            size="small"
            disabled={disabled}
            onClick={() =>
              window.open(jobOutputUrl(job.id, "audio"), "_blank")
            }
          >
            译文音频
          </Button>
          {hasVideo && (
            <Button
              size="small"
              disabled={disabled}
              onClick={() =>
                window.open(jobOutputUrl(job.id, "video"), "_blank")
              }
            >
              合成视频
            </Button>
          )}
          <DeleteButton id={job.id} onDelete={onDelete} />
        </Space>
      );
    }
  }
}

export function JobCard(props: Props) {
  const { job, onViewDetails } = props;
  return (
    <Card
      style={{ marginBottom: "var(--vc-spacing-md)" }}
      bodyStyle={{ padding: "var(--vc-spacing-lg)" }}
    >
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          marginBottom: "var(--vc-spacing-sm)",
        }}
      >
        <Space>
          <StatusTag status={job.status} />
          <Text strong>{(job.request as any)?.source_filename ?? job.id}</Text>
        </Space>
        <Text type="tertiary" size="small">
          {dayjs(job.created_at).fromNow()}
        </Text>
      </div>

      <JobBadges job={job} />

      {job.status === "running" && (
        <Progress
          percent={Math.round(job.progress * 100)}
          stroke="var(--vc-color-primary)"
          style={{ marginBottom: "var(--vc-spacing-sm)" }}
        />
      )}

      {job.error_code && (
        <Text
          type={job.status === "interrupted" ? "warning" : "danger"}
          size="small"
          style={{ whiteSpace: "pre-wrap", display: "block" }}
        >
          [{job.error_code}] {job.error_message ?? ""}
        </Text>
      )}

      <div style={{ marginTop: "var(--vc-spacing-sm)" }}>
        <Space>
          <KindActions {...props} />
          {(job.status === "failed" || job.status === "cancelled") && (
            <Button size="small" onClick={() => handleRetry(job.id)}>
              重试
            </Button>
          )}
          {job.status === "interrupted" && (
            <Button
              size="small"
              theme="solid"
              type="warning"
              onClick={() => handleRetry(job.id)}
            >
              继续
            </Button>
          )}
          {onViewDetails && (
            <Button size="small" type="tertiary" onClick={() => onViewDetails(job)}>
              详情
            </Button>
          )}
        </Space>
      </div>
    </Card>
  );
}
