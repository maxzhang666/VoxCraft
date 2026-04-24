import {
  AutoComplete,
  Button,
  Form,
  Input,
  Modal,
  Popconfirm,
  Space,
  Switch,
  Table,
  Tag,
  Toast,
  Typography,
} from "@douyinfe/semi-ui";
import { IconRefresh } from "@douyinfe/semi-icons";
import { useCallback, useEffect, useState } from "react";

import {
  createLlm,
  deleteLlm,
  listLlms,
  probeLlmModels,
  setDefaultLlm,
  updateLlm,
} from "@/api/llm";
import type { LlmProvider } from "@/types/api";

const { Title, Text } = Typography;

interface FormState {
  name: string;
  base_url: string;
  api_key: string;
  model: string;
  enabled: boolean;
}

const EMPTY: FormState = {
  name: "",
  base_url: "",
  api_key: "",
  model: "",
  enabled: true,
};

export function LlmConfig() {
  const [rows, setRows] = useState<LlmProvider[]>([]);
  const [loading, setLoading] = useState(false);
  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<LlmProvider | null>(null);
  const [form, setForm] = useState<FormState>(EMPTY);
  const [modelOptions, setModelOptions] = useState<string[]>([]);
  const [probing, setProbing] = useState(false);

  const reload = useCallback(async () => {
    setLoading(true);
    try {
      setRows(await listLlms());
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    reload();
  }, [reload]);

  const openCreate = () => {
    setEditing(null);
    setForm(EMPTY);
    setModelOptions([]);
    setModalOpen(true);
  };

  const openEdit = (p: LlmProvider) => {
    setEditing(p);
    // api_key 不回显，留空即可；用户填写新值才覆盖
    setForm({
      name: p.name,
      base_url: p.base_url,
      api_key: "",
      model: p.model,
      enabled: p.enabled,
    });
    // 已存 model 作为初始下拉项（用户点获取前也能正常编辑）
    setModelOptions(p.model ? [p.model] : []);
    setModalOpen(true);
  };

  const onProbeModels = async () => {
    if (!form.base_url) {
      Toast.warning("请先填写 Base URL");
      return;
    }
    // 编辑态留空 api_key → 用已存；否则用当前输入
    const useSaved = !!editing && !form.api_key;
    if (!editing && !form.api_key) {
      Toast.warning("新建时请先填写 API Key");
      return;
    }
    setProbing(true);
    try {
      const models = await probeLlmModels({
        base_url: form.base_url,
        api_key: useSaved ? undefined : form.api_key,
        use_id: useSaved ? editing!.id : undefined,
      });
      setModelOptions(models);
      if (models.length === 0) {
        Toast.info("端点返回空模型列表");
      } else {
        Toast.success(`获取到 ${models.length} 个模型`);
      }
    } catch {
      // 拦截器已提示
    } finally {
      setProbing(false);
    }
  };

  const onSubmit = async () => {
    if (!form.base_url || !form.model) {
      Toast.warning("Base URL 和 Model 必填");
      return;
    }
    if (!editing && (!form.name || !form.api_key)) {
      Toast.warning("Name 和 API Key 必填");
      return;
    }
    try {
      if (editing) {
        await updateLlm(editing.id, {
          base_url: form.base_url,
          api_key: form.api_key || undefined, // 空值不发送
          model: form.model,
          enabled: form.enabled,
        });
        Toast.success("已更新");
      } else {
        await createLlm({
          name: form.name,
          base_url: form.base_url,
          api_key: form.api_key,
          model: form.model,
          enabled: form.enabled,
        });
        Toast.success("已创建");
      }
      setModalOpen(false);
      await reload();
    } catch {
      // 拦截器已提示
    }
  };

  const onSetDefault = async (p: LlmProvider) => {
    await setDefaultLlm(p.id);
    Toast.success(`已设为默认：${p.name}`);
    reload();
  };

  const onDelete = async (p: LlmProvider) => {
    await deleteLlm(p.id);
    Toast.success("已删除");
    reload();
  };

  const columns = [
    { title: "名称", dataIndex: "name", width: 160 },
    { title: "Base URL", dataIndex: "base_url", width: 280 },
    { title: "Model", dataIndex: "model", width: 160 },
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
      render: (_: unknown, p: LlmProvider) => (
        <Space>
          {!p.is_default && (
            <Button size="small" onClick={() => onSetDefault(p)}>
              设为默认
            </Button>
          )}
          <Button size="small" onClick={() => openEdit(p)}>
            编辑
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
          LLM 配置
        </Title>
        <Button theme="solid" onClick={openCreate}>
          + 新增 LLM
        </Button>
      </div>

      <Text type="tertiary" size="small">
        支持任何 OpenAI 兼容端点（OpenAI / DeepSeek / Qwen / 本地 Ollama 等）。
        API Key 明文存储于 <Text code>data/voxcraft.sqlite</Text>，请自行保护数据库文件。
      </Text>

      <Table
        columns={columns}
        dataSource={rows}
        rowKey="id"
        loading={loading}
        pagination={false}
        style={{ marginTop: "var(--vc-spacing-md)" }}
      />

      <Modal
        visible={modalOpen}
        title={editing ? `编辑 ${editing.name}` : "新增 LLM"}
        onCancel={() => setModalOpen(false)}
        width={520}
        footer={
          <Space>
            <Button onClick={() => setModalOpen(false)}>取消</Button>
            <Button theme="solid" onClick={onSubmit}>
              保存
            </Button>
          </Space>
        }
      >
        <Form labelPosition="left" labelWidth={110}>
          <Form.Slot label="名称">
            <Input
              value={form.name}
              onChange={(v) => setForm((f) => ({ ...f, name: v }))}
              disabled={!!editing}
              placeholder="小写字母/数字/下划线/连字符，如 openai / deepseek"
            />
          </Form.Slot>
          <Form.Slot label="Base URL">
            <Input
              value={form.base_url}
              onChange={(v) => setForm((f) => ({ ...f, base_url: v }))}
              placeholder="https://api.openai.com/v1"
            />
          </Form.Slot>
          <Form.Slot label="API Key">
            <Input
              value={form.api_key}
              mode="password"
              onChange={(v) => setForm((f) => ({ ...f, api_key: v }))}
              placeholder={editing ? "留空保持原值" : "sk-..."}
            />
          </Form.Slot>
          <Form.Slot label="Model">
            <div style={{ display: "flex", gap: 8 }}>
              <AutoComplete
                value={form.model}
                onChange={(v) => setForm((f) => ({ ...f, model: String(v) }))}
                onSelect={(v) => setForm((f) => ({ ...f, model: String(v) }))}
                data={modelOptions}
                placeholder="gpt-4o-mini / deepseek-chat / qwen-turbo / ..."
                style={{ flex: 1 }}
                emptyContent={
                  <div style={{ padding: 8, color: "var(--vc-color-text-secondary)" }}>
                    点击右侧获取按钮拉取
                  </div>
                }
              />
              <Button
                icon={<IconRefresh />}
                onClick={onProbeModels}
                loading={probing}
                title={
                  editing
                    ? "获取模型列表（留空 API Key 时使用已存 Key）"
                    : "获取模型列表（先填 Base URL + API Key）"
                }
              >
                获取
              </Button>
            </div>
          </Form.Slot>
          <Form.Slot label="启用">
            <Switch
              checked={form.enabled}
              onChange={(v) => setForm((f) => ({ ...f, enabled: v }))}
            />
          </Form.Slot>
        </Form>
      </Modal>
    </div>
  );
}
