import { Toast } from "@douyinfe/semi-ui";
import { useCallback, useEffect, useState } from "react";

import { deleteJob, listJobs } from "@/api/jobs";
import { CapabilityPageTemplate } from "@/components/CapabilityPageTemplate";
import { JobCard } from "@/components/JobCard";
import { JobDetailsModal } from "@/components/JobDetailsModal";
import { SeparatorDrawer } from "@/drawers/SeparatorDrawer";
import { useJobListStream } from "@/hooks/useJobListStream";
import type { Job } from "@/types/api";

export function SeparatorPage() {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [detailsJob, setDetailsJob] = useState<Job | null>(null);

  const reload = useCallback(async () => {
    try {
      setJobs(await listJobs({ kind: "separate", limit: 50 }));
    } catch {
      // ignore
    }
  }, []);

  useEffect(() => {
    reload();
  }, [reload]);

  useJobListStream("separate", reload, setJobs);

  const onDelete = async (id: string) => {
    await deleteJob(id);
    Toast.success("已删除");
    reload();
  };

  return (
    <>
      <CapabilityPageTemplate
        title="人声分离"
        icon="🎸"
        onCreate={() => setDrawerOpen(true)}
        createLabel="+ 新建分离"
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

      <SeparatorDrawer
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
