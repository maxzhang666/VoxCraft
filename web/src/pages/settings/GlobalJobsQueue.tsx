import { Select, Space, Table, Typography } from "@douyinfe/semi-ui";
import dayjs from "dayjs";
import { useCallback, useEffect, useState } from "react";

import { listJobs } from "@/api/jobs";
import { StatusTag } from "@/components/StatusTag";
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
];

export function GlobalJobsQueue() {
  const [kind, setKind] = useState<JobKind | "">("");
  const [status, setStatus] = useState<JobStatus | "">("");
  const [rows, setRows] = useState<Job[]>([]);
  const [loading, setLoading] = useState(false);

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

  const columns = [
    {
      title: "ID",
      dataIndex: "id",
      width: 140,
      render: (id: string) => id.slice(0, 12),
    },
    { title: "类型", dataIndex: "kind", width: 100 },
    {
      title: "状态",
      dataIndex: "status",
      width: 120,
      render: (s: JobStatus) => <StatusTag status={s} />,
    },
    {
      title: "进度",
      dataIndex: "progress",
      width: 100,
      render: (p: number) => `${Math.round(p * 100)}%`,
    },
    { title: "Provider", dataIndex: "provider_name", width: 200 },
    {
      title: "创建时间",
      dataIndex: "created_at",
      render: (t: string) => dayjs(t).format("YYYY-MM-DD HH:mm:ss"),
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
    </div>
  );
}
