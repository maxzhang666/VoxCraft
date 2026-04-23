import { Button, SideSheet, Space } from "@douyinfe/semi-ui";
import type { ReactNode } from "react";

import { t } from "@/i18n/zh-CN";

interface Props {
  visible: boolean;
  title: string;
  submitting?: boolean;
  submitLabel?: string;
  onClose: () => void;
  onSubmit: () => void;
  children: ReactNode;
}

export function TaskCreationDrawer({
  visible,
  title,
  submitting,
  submitLabel = t.actions.submit,
  onClose,
  onSubmit,
  children,
}: Props) {
  return (
    <SideSheet
      visible={visible}
      title={title}
      placement="right"
      width={560}
      onCancel={onClose}
      maskClosable={!submitting}
      footer={
        <div style={{ display: "flex", justifyContent: "flex-end" }}>
          <Space>
            <Button onClick={onClose} disabled={submitting}>
              {t.actions.cancel}
            </Button>
            <Button theme="solid" loading={submitting} onClick={onSubmit}>
              {submitLabel}
            </Button>
          </Space>
        </div>
      }
    >
      {children}
    </SideSheet>
  );
}
