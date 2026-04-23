import {
  Button,
  Form,
  Input,
  InputNumber,
  Modal,
  Popconfirm,
  Select,
  Space,
  Switch,
  Table,
  Tabs,
  Tag,
  Toast,
  Typography,
} from "@douyinfe/semi-ui";
import { useCallback, useEffect, useMemo, useState } from "react";

import { listLibrary } from "@/api/modelsLibrary";
import {
  createProvider,
  deleteProvider,
  listProviderClasses,
  listProviders,
  setDefaultProvider,
  testProvider,
  updateProvider,
} from "@/api/providers";
import type {
  CatalogView,
  ConfigFieldSchema,
  Provider,
  ProviderClassSchema,
  ProviderCreate,
  ProviderKind,
} from "@/types/api";

const { Title } = Typography;
const { TabPane } = Tabs;

const KINDS: ProviderKind[] = ["asr", "tts", "cloning", "separator"];
const KIND_LABEL: Record<ProviderKind, string> = {
  asr: "语音识别",
  tts: "语音合成",
  cloning: "语音克隆",
  separator: "人声分离",
};

/** 某个 Provider 类的 schema 中，第一个 type=path 的字段——"选模型"时用它承载模型路径。 */
function pathFieldOf(schema: ProviderClassSchema): ConfigFieldSchema | undefined {
  return schema.fields.find((f) => f.type === "path");
}

/** 依 schema 生成表单的初始 config（未填写 → 取 default 或空值）。 */
function defaultConfigForSchema(
  schema: ProviderClassSchema,
  existing?: Record<string, unknown>
): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const f of schema.fields) {
    const prev = existing?.[f.key];
    out[f.key] = prev !== undefined ? prev : f.default ?? "";
  }
  return out;
}

export function ModelsManage() {
  const [activeKind, setActiveKind] = useState<ProviderKind>("asr");
  const [rows, setRows] = useState<Provider[]>([]);
  const [loading, setLoading] = useState(false);
  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<Provider | null>(null);

  // Modal 依赖的数据
  const [libraryReady, setLibraryReady] = useState<CatalogView[]>([]);
  const [classes, setClasses] = useState<ProviderClassSchema[]>([]);

  // 表单当前状态（受控，由 class_name + config 两部分组成）
  const [form, setForm] = useState<{
    name: string;
    className: string;
    config: Record<string, unknown>;
    enabled: boolean;
  }>({ name: "", className: "", config: {}, enabled: true });

  const activeSchema = useMemo(
    () => classes.find((c) => c.class_name === form.className),
    [classes, form.className],
  );

  const reload = useCallback(async () => {
    setLoading(true);
    try {
      const data = await listProviders(activeKind);
      setRows(data);
    } finally {
      setLoading(false);
    }
  }, [activeKind]);

  useEffect(() => {
    reload();
  }, [reload]);

  // Modal 打开：按当前 kind 拉 schema + 已下载模型
  useEffect(() => {
    if (!modalOpen) return;
    Promise.all([
      listProviderClasses(activeKind).catch(() => [] as ProviderClassSchema[]),
      listLibrary().catch(() => [] as CatalogView[]),
    ]).then(([cs, lib]) => {
      setClasses(cs);
      setLibraryReady(lib.filter((e) => e.status === "ready"));

      // 初始化表单值：编辑态从 editing 展开；新增态默认空
      if (editing) {
        const sch = cs.find((c) => c.class_name === editing.class_name);
        setForm({
          name: editing.name,
          className: editing.class_name,
          config: sch
            ? defaultConfigForSchema(sch, editing.config)
            : { ...editing.config },
          enabled: editing.enabled,
        });
      } else {
        setForm({ name: "", className: "", config: {}, enabled: true });
      }
    });
  }, [modalOpen, activeKind, editing]);

  /** 选模型：自动填 class_name、name、路径字段。非内置模型 (provider_class=null) 提示手选。 */
  const applyModel = (modelId: number) => {
    const entry = libraryReady.find((m) => m.model_id === modelId);
    if (!entry || !entry.local_path) return;

    const className = entry.provider_class;
    if (!className) {
      Toast.warning("该模型为自定义/手动条目，请在下方手选实现");
      return;
    }
    const schema = classes.find((c) => c.class_name === className);
    if (!schema) {
      Toast.error(`未知实现类：${className}`);
      return;
    }

    const pathField = pathFieldOf(schema);
    let value = entry.local_path;
    // Demucs 不是路径，是预训练权重名
    if (className === "DemucsProvider") {
      value = entry.catalog_key.replace(/^demucs-/, "");
    } else if (className === "PiperProvider") {
      try {
        const urlName = new URL(entry.sources[0]?.repo_id ?? "").pathname
          .split("/")
          .filter(Boolean)
          .pop();
        if (urlName && urlName.endsWith(".onnx")) {
          value = `${entry.local_path}/${urlName}`;
        }
      } catch {
        /* keep directory */
      }
    }

    const base = defaultConfigForSchema(schema, form.config);
    if (pathField) base[pathField.key] = value;
    // Demucs 的 model_name 是 enum，不走 path 字段——单独塞
    if (className === "DemucsProvider") base.model_name = value;

    const suggestedName =
      form.name || entry.catalog_key.replace(/[^a-z0-9_\-]/g, "-");

    setForm((f) => ({
      ...f,
      className,
      name: suggestedName,
      config: base,
    }));
    Toast.success(`已自动配置：${schema.label}`);
  };

  const openCreate = () => {
    setEditing(null);
    setModalOpen(true);
  };

  const openEdit = (p: Provider) => {
    setEditing(p);
    setModalOpen(true);
  };

  const onSubmit = async () => {
    if (!form.className) {
      Toast.warning("请选择模型或实现类");
      return;
    }
    if (!editing && !form.name) {
      Toast.warning("请填写名称");
      return;
    }
    // required 字段检查
    const schema = classes.find((c) => c.class_name === form.className);
    if (schema) {
      for (const f of schema.fields) {
        if (f.required && (form.config[f.key] === "" || form.config[f.key] == null)) {
          Toast.error(`${f.label} 不能为空`);
          return;
        }
      }
    }

    try {
      if (editing) {
        await updateProvider(editing.id, {
          config: form.config,
          enabled: form.enabled,
        });
        Toast.success("已更新");
      } else {
        await createProvider({
          kind: activeKind,
          name: form.name,
          class_name: form.className,
          config: form.config,
        } satisfies ProviderCreate);
        Toast.success("已创建");
      }
      setModalOpen(false);
      await reload();
    } catch {
      // 拦截器已提示
    }
  };

  const onSetDefault = async (p: Provider) => {
    await setDefaultProvider(p.id);
    Toast.success(`已设为默认：${p.name}`);
    reload();
  };

  const onTest = async (p: Provider) => {
    const loadingId = Toast.info({ content: `探活中：${p.name}…`, duration: 0 });
    try {
      const r = await testProvider(p.id);
      if (r.ok) {
        Toast.success(`探活成功：${p.name}${r.detail ? `（${r.detail}）` : ""}`);
      } else {
        Toast.error(`探活失败：${p.name}${r.detail ? ` - ${r.detail}` : ""}`);
      }
    } catch {
      // 拦截器已提示
    } finally {
      Toast.close(loadingId);
    }
  };

  const onDelete = async (p: Provider) => {
    await deleteProvider(p.id);
    Toast.success("已删除");
    reload();
  };

  const columns = [
    { title: "名称", dataIndex: "name", width: 240 },
    { title: "实现类", dataIndex: "class_name", width: 240 },
    {
      title: "默认",
      dataIndex: "is_default",
      width: 80,
      render: (v: boolean) => (v ? <Tag color="teal">默认</Tag> : null),
    },
    {
      title: "启用",
      dataIndex: "enabled",
      width: 80,
      render: (v: boolean) =>
        v ? <Tag color="green">是</Tag> : <Tag color="grey">否</Tag>,
    },
    {
      title: "操作",
      render: (_: unknown, p: Provider) => (
        <Space>
          {!p.is_default && (
            <Button size="small" onClick={() => onSetDefault(p)}>
              设为默认
            </Button>
          )}
          <Button size="small" onClick={() => openEdit(p)}>
            编辑
          </Button>
          <Button size="small" onClick={() => onTest(p)}>
            探活
          </Button>
          <Popconfirm title={`删除 ${p.name} ？`} onConfirm={() => onDelete(p)}>
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
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          marginBottom: "var(--vc-spacing-lg)",
        }}
      >
        <Title heading={3} style={{ margin: 0 }}>
          模型管理
        </Title>
        <Button theme="solid" onClick={openCreate}>
          + 新增模型
        </Button>
      </div>

      <Tabs
        activeKey={activeKind}
        onChange={(k) => setActiveKind(k as ProviderKind)}
      >
        {KINDS.map((k) => (
          <TabPane tab={KIND_LABEL[k]} itemKey={k} key={k}>
            <Table
              columns={columns}
              dataSource={rows}
              rowKey="id"
              loading={loading}
              pagination={false}
            />
          </TabPane>
        ))}
      </Tabs>

      <Modal
        visible={modalOpen}
        title={editing ? `编辑 ${editing.name}` : `新增 ${KIND_LABEL[activeKind]}`}
        onCancel={() => setModalOpen(false)}
        width={560}
        footer={
          <Space>
            <Button onClick={() => setModalOpen(false)}>取消</Button>
            <Button theme="solid" onClick={onSubmit}>
              保存
            </Button>
          </Space>
        }
      >
        <Form labelPosition="left" labelWidth={100}>
          {!editing && (
            <>
              <Form.Slot label="模型">
                <Select
                  placeholder={
                    libraryReady.length === 0
                      ? "暂无已下载模型（去模型库下载）"
                      : "选已下载模型 · 自动填写实现 / 名称 / 路径"
                  }
                  disabled={libraryReady.length === 0}
                  style={{ width: "100%" }}
                  onChange={(v) => applyModel(Number(v))}
                  optionList={libraryReady
                    .filter((m) => !m.kind || m.kind === activeKind)
                    .map((m) => ({
                      label: `${m.catalog_key}（${KIND_LABEL[m.kind as ProviderKind] ?? m.kind}）${m.provider_class ? ` · ${m.provider_class}` : " · 手选实现"}`,
                      value: m.model_id!,
                    }))}
                />
              </Form.Slot>
              <Form.Slot label="名称">
                <Input
                  value={form.name}
                  onChange={(v) => setForm((f) => ({ ...f, name: v }))}
                  placeholder="小写字母/数字/下划线/连字符"
                />
              </Form.Slot>
              <Form.Slot label="实现">
                <Select
                  value={form.className || undefined}
                  placeholder="选模型后自动填；也可手选"
                  style={{ width: "100%" }}
                  onChange={(v) => {
                    const cn = String(v);
                    const sch = classes.find((c) => c.class_name === cn);
                    setForm((f) => ({
                      ...f,
                      className: cn,
                      config: sch ? defaultConfigForSchema(sch, f.config) : {},
                    }));
                  }}
                  optionList={classes.map((c) => ({
                    label: c.label,
                    value: c.class_name,
                  }))}
                />
              </Form.Slot>
            </>
          )}

          {activeSchema ? (
            activeSchema.fields.map((f) => (
              <Form.Slot key={f.key} label={f.label}>
                {renderField(f, form.config[f.key], (v) =>
                  setForm((prev) => ({
                    ...prev,
                    config: { ...prev.config, [f.key]: v },
                  }))
                )}
                {f.help && (
                  <div
                    style={{
                      fontSize: 12,
                      color: "var(--vc-color-text-secondary)",
                      marginTop: 2,
                    }}
                  >
                    {f.help}
                  </div>
                )}
              </Form.Slot>
            ))
          ) : (
            <div style={{ color: "var(--vc-color-text-secondary)", padding: "8px 0" }}>
              {editing
                ? "此 Provider 的实现类未在 registry 中，无法动态配置"
                : "请先选择模型或实现"}
            </div>
          )}

          {editing && (
            <Form.Slot label="启用">
              <Switch
                checked={form.enabled}
                onChange={(v) => setForm((f) => ({ ...f, enabled: v }))}
              />
            </Form.Slot>
          )}
        </Form>
      </Modal>
    </div>
  );
}

/** 按字段 schema 渲染对应的 Semi 控件。 */
function renderField(
  f: ConfigFieldSchema,
  value: unknown,
  onChange: (v: unknown) => void
) {
  switch (f.type) {
    case "enum":
      return (
        <Select
          value={(value as string) ?? undefined}
          onChange={(v) => onChange(String(v))}
          optionList={(f.options ?? []).map((o) => ({ label: o, value: o }))}
          style={{ width: "100%" }}
        />
      );
    case "int":
      return (
        <InputNumber
          value={(value as number) ?? undefined}
          onChange={(v) => onChange(v)}
          style={{ width: "100%" }}
        />
      );
    case "bool":
      return (
        <Switch checked={Boolean(value)} onChange={(v) => onChange(v)} />
      );
    case "path":
    case "str":
    default:
      return (
        <Input
          value={(value as string) ?? ""}
          onChange={(v) => onChange(v)}
          placeholder={f.type === "path" ? "选模型后自动填；也可手改" : undefined}
        />
      );
  }
}
