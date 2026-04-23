# Changelog

All notable changes to this project will be documented in this file.

## [v0.1.3] — 2026-04-23

### Changed — Breaking
- **业务端点全异步化**（[ADR-011](docs/superpowers/specs/voxcraft/decisions/ADR-011-async-by-default.md)）：`POST /asr | /tts | /tts/clone | /separate` 从"同步返回结果"改为"立即返回 `202 {job_id, status: "pending"}`"。外部调用方需改为订阅 SSE 或轮询 `GET /jobs/{id}` 获取结果。取代 ADR-008 §2 的混合同/异步策略。

### Added
- `POST /jobs/{id}/retry` — 失败/取消任务复用 `job_id` 重试（ASR/Clone/Separate 需原始上传仍存在）
- `Job.source_path` 字段 + Alembic migration 0004 — 原始上传落盘保留
- `GET /admin/providers/classes` — Provider 类及其 config schema；驱动前端动态表单
- `Provider.CONFIG_SCHEMA` / `LABEL` / `ConfigField` 基础设施；5 个 Provider 全部声明字段

### Changed
- 探活 `POST /admin/providers/{id}/test` 从"只 import class"改为真实走 `scheduler.run(lru.ensure_loaded(inst))`；失败透传错误码
- 前端 `ModelsManage` Modal：删除 JSON TextArea 与硬编码 `CONFIG_FIELD_BY_CLASS`，改为 schema 驱动的动态表单
- 所有删除按钮改 `Popconfirm` + `type="danger"` 二次确认
- `DELETE /jobs/{id}` 级联清理 `source_path + output_path + output_extras`

### Fixed
- `JobDetailsModal` 从"条件挂载 + 初始 `visible=true`"反模式改为"Modal 常驻 + `visible={!!job}`"；点击详情无反应的问题解决
- `JobCard` ASR 分支误用 `disabled` 变量导致删除按钮被禁用
- `SettingsLayout` / `MainLayout` Sider Nav 宽度溢出（Semi Nav 默认 240px 超出 Sider 宽度）
- Vite dev server 刷新前端路由 `/asr` `/tts` `/separator` 返回 `405 Method Not Allowed`（proxy 按 `Accept: text/html` 区分浏览器导航 / API 调用）
- `ModelsManage` Modal 底部按钮贴边（改用 Semi `footer` prop）

### Docs
- ADR-011 新增；ADR-008 §2 标注 superseded
- 04-architecture.md / 05-api.md 同步异步语义
- 02-capabilities.md / 07-deployment.md XTTS → VoxCPM/IndexTTS
- `plans/archived/voxcraft-v0.1.3-async-and-ux.md` 回溯归档
- 08-roadmap.md 勾选完成项 + 新增 v0.1.2 / v0.1.3 节点

### Tests
- 138 passed, 3 skipped（含 `test_retry_failed_job` / `test_list_classes_returns_schema` 新增）
- `tests/conftest.wait_for_job` helper；所有 integration 测试改为异步期望

## [v0.1.2] — 2026-04-21

模型库（ModelLibrary）：UI 一键下载 / 管理模型。详见 [ADR-010](docs/superpowers/specs/voxcraft/decisions/ADR-010-model-management.md) 与 `plans/archived/voxcraft-v0.1.2.md`。

## [v0.1] — 2026-04-19

MVP：FastAPI 后端 + React/Semi 前端，ASR/TTS/Clone/Separate 骨架、全局单任务锁 + LRU=1、SSE、Docker。详见 `plans/archived/voxcraft-mvp-v0.1.md`。
