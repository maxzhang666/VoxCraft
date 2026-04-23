import {
  Button,
  Popconfirm,
  Select,
  Space,
  Table,
  Toast,
  Typography,
} from "@douyinfe/semi-ui";
import dayjs from "dayjs";
import { useCallback, useEffect, useState } from "react";

import { deleteJob, listJobs, retryJob } from "@/api/jobs";
import { JobDetailsModal } from "@/components/JobDetailsModal";
import { StatusTag } from "@/components/StatusTag";
import { useSse } from "@/hooks/useSse";
import type { Job, JobKind, JobStatus } from "@/types/api";

const { Title } = Typography;

const KIND_OPTIONS = [
  { label: "全部", value: "" },
  { label: "语音识别", value: "asr" },
  { label: "语音合成", value: "tts" },
  { label: "语音克隆", value: "clone" },
  { label: "人声分离", value: "separate" },
];

const STATUS_OPTIONS = [
  { label: "全部", value: "" },
  { label: "等待中", value: "pending" },
  { label: "运行中", value: "running" },
  { label: "已完成", value: "succeeded" },
  { label: "失败", value: "failed" },
  { label: "已取消", value: "cancelled" },
];

export function GlobalJobsQueue() {
  const [kind, setKind] = useState<JobKind | "">("");
  const [status, setStatus] = useState<JobStatus | "">("");
  const [rows, setRows] = useState<Job[]>([]);
  const [loading, setLoading] = useState(false);
  const [detailsJob, setDetailsJob] = useState<Job | null>(null);

  const reload = useCallback(async () => {
    setLoading(true);
    try {
      const data = await listJobs({
        kind: (kind || undefined) as JobKind | undefined,
        status: (status || undefined) as JobStatus | undefined,
        limit: 100,
      });
      setRows(data);
    } finally {
      setLoading(false);
    }
  }, [kind, status]);

  useEffect(() => {
    reload();
  }, [reload]);

  // SSE 驱动实时刷新：任何 Job 状态变化都重拉当前过滤结果
  useSse(["job_status_changed", "job_progress"], reload);

  const onDelete = async (id: string) => {
    await deleteJob(id);
    Toast.success("已删除");
    reload();
  };

  const onRetry = async (id: string) => {
    try {
      await retryJob(id);
      Toast.info("已重新入队");
    } catch {
      // 拦截器已提示
    }
  };

  const columns = [
    {
      title: "ID",
      dataIndex: "id",
      width: 140,
      render: (id: string) => id.slice(0, 12),
    },
    { title: "类型", dataIndex: "kind", width: 90 },
    {
      title: "状态",
      dataIndex: "status",
      width: 110,
      render: (s: JobStatus) => <StatusTag status={s} />,
    },
    {
      title: "进度",
      dataIndex: "progress",
      width: 80,
      render: (p: number) => `${Math.round(p * 100)}%`,
    },
    { title: "Provider", dataIndex: "provider_name", width: 180 },
    {
      title: "创建时间",
      dataIndex: "created_at",
      width: 170,
      render: (t: string) => dayjs(t).format("YYYY-MM-DD HH:mm:ss"),
    },
    {
      title: "操作",
      width: 220,
      render: (_: unknown, j: Job) => (
        <Space>
          <Button size="small" type="tertiary" onClick={() => setDetailsJob(j)}>
            详情
          </Button>
          {(j.status === "failed" || j.status === "cancelled") && (
            <Button size="small" onClick={() => onRetry(j.id)}>
              重试
            </Button>
          )}
          <Popconfirm
            title={`删除任务 ${j.id.slice(0, 8)} ？`}
            content="原始上传与产物文件将一并清除，不可恢复。"
            onConfirm={() => onDelete(j.id)}
          >
            <Button size="small" type="danger">
              删除
            </Button>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  return (
    <div>
      <Title heading={3} style={{ marginBottom: "var(--vc-spacing-lg)" }}>
        任务队列
      </Title>
      <Space style={{ marginBottom: "var(--vc-spacing-md)" }}>
        <Select
          value={kind}
          onChange={(v) => setKind(v as JobKind | "")}
          optionList={KIND_OPTIONS}
          style={{ width: 160 }}
        />
        <Select
          value={status}
          onChange={(v) => setStatus(v as JobStatus | "")}
          optionList={STATUS_OPTIONS}
          style={{ width: 160 }}
        />
      </Space>
      <Table
        columns={columns}
        dataSource={rows}
        rowKey="id"
        loading={loading}
        pagination={{ pageSize: 20 }}
      />

      <JobDetailsModal job={detailsJob} onClose={() => setDetailsJob(null)} />
    </div>
  );
}
