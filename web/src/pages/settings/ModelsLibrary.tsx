import { Button, Empty, Select, Space, Toast, Typography } from "@douyinfe/semi-ui";
import { IconPlus, IconRefresh } from "@douyinfe/semi-icons";
import { useCallback, useEffect, useState } from "react";

import {
  cancelDownload,
  deleteModel,
  downloadCatalog,
  listLibrary,
} from "@/api/modelsLibrary";
import { ModelCatalogCard } from "@/components/ModelCatalogCard";
import { CustomModelDrawer } from "@/drawers/CustomModelDrawer";
import { useSse } from "@/hooks/useSse";
import type { CatalogView } from "@/types/api";

const { Title } = Typography;

const KIND_FILTERS = [
  { label: "全部", value: "" },
  { label: "语音识别", value: "asr" },
  { label: "语音合成", value: "tts" },
  { label: "语音克隆", value: "cloning" },
  { label: "人声分离", value: "separator" },
];

export function ModelsLibrary() {
  const [entries, setEntries] = useState<CatalogView[]>([]);
  const [kind, setKind] = useState<string>("");
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [loading, setLoading] = useState(false);

  const reload = useCallback(async () => {
    setLoading(true);
    try {
      setEntries(await listLibrary());
    } catch {
      /* interceptor 已 Toast */
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    reload();
  }, [reload]);

  useSse(
    [
      "model_download_progress",
      "model_download_completed",
      "model_download_failed",
    ],
    () => {
      reload();
    }
  );

  const onDownload = async (entry: CatalogView, source: string) => {
    try {
      await downloadCatalog(entry.catalog_key, source);
      Toast.success(`已加入下载队列：${entry.label}`);
      reload();
    } catch {
      /* interceptor 已 Toast */
    }
  };

  const onCancel = async (entry: CatalogView) => {
    if (entry.model_id == null) return;
    try {
      await cancelDownload(entry.model_id);
      Toast.success("已取消");
      reload();
    } catch {
      /* interceptor 已 Toast */
    }
  };

  const onDelete = async (entry: CatalogView) => {
    if (entry.model_id == null) return;
    try {
      await deleteModel(entry.model_id);
      Toast.success("已删除");
      reload();
    } catch {
      /* interceptor 已 Toast */
    }
  };

  const filtered = kind ? entries.filter((e) => e.kind === kind) : entries;

  return (
    <div>
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          marginBottom: "var(--vc-spacing-lg)",
        }}
      >
        <Title heading={3} style={{ margin: 0 }}>
          模型库
        </Title>
        <Space>
          <Select
            value={kind}
            onChange={(v) => setKind(String(v))}
            optionList={KIND_FILTERS}
            style={{ width: 140 }}
          />
          <Button icon={<IconRefresh />} onClick={reload} loading={loading}>
            刷新
          </Button>
          <Button
            theme="solid"
            icon={<IconPlus />}
            onClick={() => setDrawerOpen(true)}
          >
            添加自定义
          </Button>
        </Space>
      </div>

      {filtered.length === 0 ? (
        <Empty
          image={<div style={{ fontSize: 48 }}>📚</div>}
          title="暂无条目"
          description="当前筛选下没有模型"
          style={{ padding: "40px 0" }}
        />
      ) : (
        filtered.map((e) => (
          <ModelCatalogCard
            key={e.catalog_key}
            entry={e}
            onDownload={onDownload}
            onCancel={onCancel}
            onDelete={onDelete}
          />
        ))
      )}

      <CustomModelDrawer
        visible={drawerOpen}
        onClose={() => setDrawerOpen(false)}
        onSuccess={() => {
          setDrawerOpen(false);
          reload();
        }}
      />
    </div>
  );
}
