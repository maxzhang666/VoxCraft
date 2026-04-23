import { Empty, Toast } from "@douyinfe/semi-ui";
import { useCallback, useEffect, useState } from "react";

import { deleteJob, listJobs } from "@/api/jobs";
import { JobCard } from "@/components/JobCard";
import { JobDetailsModal } from "@/components/JobDetailsModal";
import { useJobListStream } from "@/hooks/useJobListStream";
import type { Job } from "@/types/api";
import { t } from "@/i18n/zh-CN";

export function HistoryTab({ reloadKey }: { reloadKey: number }) {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [detailsJob, setDetailsJob] = useState<Job | null>(null);

  const reload = useCallback(async () => {
    try {
      setJobs(await listJobs({ kind: "clone", limit: 50 }));
    } catch {
      // ignore
    }
  }, []);

  useEffect(() => {
    reload();
  }, [reload, reloadKey]);

  useJobListStream("clone", reload, setJobs);

  const onDelete = async (id: string) => {
    await deleteJob(id);
    Toast.success("已删除");
    reload();
  };

  if (jobs.length === 0) {
    return (
      <Empty
        image={<div style={{ fontSize: 48 }}>🌱</div>}
        title={t.common.empty}
        style={{ padding: "40px 0" }}
      />
    );
  }

  return (
    <div>
      {jobs.map((j) => (
        <JobCard
          key={j.id}
          job={j}
          onDelete={onDelete}
          onViewDetails={setDetailsJob}
        />
      ))}
      <JobDetailsModal job={detailsJob} onClose={() => setDetailsJob(null)} />
    </div>
  );
}
