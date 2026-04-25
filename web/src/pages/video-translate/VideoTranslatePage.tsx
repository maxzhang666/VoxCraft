import { Toast } from "@douyinfe/semi-ui";
import { useCallback, useEffect, useState } from "react";

import { deleteJob, listJobs } from "@/api/jobs";
import { CapabilityPageTemplate } from "@/components/CapabilityPageTemplate";
import { JobCard } from "@/components/JobCard";
import { JobDetailsModal } from "@/components/JobDetailsModal";
import { VideoTranslateDrawer } from "@/drawers/VideoTranslateDrawer";
import { useJobListStream } from "@/hooks/useJobListStream";
import type { Job } from "@/types/api";

export function VideoTranslatePage() {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [detailsJob, setDetailsJob] = useState<Job | null>(null);

  const reload = useCallback(async () => {
    try {
      setJobs(await listJobs({ kind: "video_translate", limit: 50 }));
    } catch {
      // 拦截器已提示
    }
  }, []);

  useEffect(() => {
    reload();
  }, [reload]);

  useJobListStream("video_translate", reload, setJobs);

  const onDelete = async (id: string) => {
    await deleteJob(id);
    Toast.success("已删除");
    reload();
  };

  return (
    <>
      <CapabilityPageTemplate
        title="视频语音级翻译"
        icon="🎬"
        onCreate={() => setDrawerOpen(true)}
        onRefresh={reload}
        createLabel="+ 新建视频翻译"
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

      <VideoTranslateDrawer
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
