import { Tag } from "@douyinfe/semi-ui";
import type { JobStatus } from "@/types/api";
import { t } from "@/i18n/zh-CN";

const COLOR: Record<JobStatus, "grey" | "blue" | "green" | "red" | "orange"> = {
  pending: "grey",
  running: "blue",
  succeeded: "green",
  failed: "red",
  cancelled: "orange",
};

export function StatusTag({ status }: { status: JobStatus }) {
  return (
    <Tag color={COLOR[status]} size="small" shape="circle">
      ● {t.status[status]}
    </Tag>
  );
}
