import { Toast } from "@douyinfe/semi-ui";
import { useCallback, useEffect, useState } from "react";

import { deleteJob, listJobs } from "@/api/jobs";
import { CapabilityPageTemplate } from "@/components/CapabilityPageTemplate";
import { JobCard } from "@/components/JobCard";
import { JobDetailsModal } from "@/components/JobDetailsModal";
import { TtsDrawer } from "@/drawers/TtsDrawer";
import { useSse } from "@/hooks/useSse";
import type { Job } from "@/types/api";

export function TtsPage() {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [detailsJob, setDetailsJob] = useState<Job | null>(null);

  const reload = useCallback(async () => {
    try {
      setJobs(await listJobs({ kind: "tts", limit: 50 }));
    } catch {
      // ignore
    }
  }, []);

  useEffect(() => {
    reload();
  }, [reload]);

  useSse(["job_progress", "job_status_changed"], (ev) => {
    const p = ev.payload as { kind?: string };
    if (p.kind === "tts") reload();
  });

  const onDelete = async (id: string) => {
    await deleteJob(id);
    Toast.success("已删除");
    reload();
  };

  return (
    <>
      <CapabilityPageTemplate
        title="语音合成"
        icon="🔊"
        onCreate={() => setDrawerOpen(true)}
        createLabel="+ 新建合成"
        isEmpty={jobs.length === 0}
      >
        {jobs.map((j) => (
          <JobCard
            key={j.id}
            job={j}
            onDelete={onDelete}
            onViewDetails={setDetailsJob}
          />
        ))}
      </CapabilityPageTemplate>

      <TtsDrawer
        visible={drawerOpen}
        onClose={() => setDrawerOpen(false)}
        onSuccess={() => {
          setDrawerOpen(false);
          reload();
        }}
      />

      <JobDetailsModal job={detailsJob} onClose={() => setDetailsJob(null)} />
    </>
  );
}
