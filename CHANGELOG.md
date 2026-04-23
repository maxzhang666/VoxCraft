# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased]

### Docs
- **ADR-013 Accepted**（[process-pool-cancel](docs/superpowers/specs/voxcraft/decisions/ADR-013-process-pool-cancel.md)）：Worker 子进程调度 + Running 任务真取消的完整设计固化。否决"伪取消"方案，选 `multiprocessing.Process` + `SIGTERM` 路径；接受 LRU 冷启动代价换取真中断能力。**实施留给下一会话窗口**（代码改动涉及 scheduler/business/jobs/main 多模块 + 新 worker 入口，不在当前会话塞入）。

### Added（接口前置）
- `Scheduler.cancel(job_id) -> bool` 接口，in-process 实现固定返回 False（明示"不能保证已停"）；为 ADR-013 的 `PoolScheduler` 实施留接口锚点
- `Settings.scheduler_backend: Literal["inprocess","pool"]`（默认 `inprocess`），预留生产切换 pool 的配置项

## [v0.1.4] — 2026-04-23

### Added — OpenAI 兼容 API 层（[ADR-012](docs/superpowers/specs/voxcraft/decisions/ADR-012-openai-compat.md)）
- `POST /v1/audio/transcriptions` 对齐 OpenAI Whisper API；支持 `response_format` ∈ `{json, text, srt, vtt, verbose_json}`
- `POST /v1/audio/speech` 对齐 OpenAI TTS API；支持 `response_format` ∈ `{mp3, opus, aac, flac, wav, pcm}`
- 请求校验错误走 OpenAI error envelope `{error:{message,type,code}}`，不再返回 VoxCraft 默认 `{error:{code,message,details}}`（仅限 `/v1/audio/*` 路径）
- 所有响应带 `X-VoxCraft-Job-Id` 头便于追溯
- 入口层同步（内核仍 ADR-011 异步）：等到 Job 终态回包，默认 10 分钟超时；超时不中断后台任务

### 不影响
- 现有 `/asr` `/tts` `/tts/clone` `/separate` 异步端点（UI 与 SSE 场景继续使用）
- 异步 runner、Job 表结构、SSE 事件

### Tests
- 150 passed, 3 skipped（含 `test_oai_compat.py` 新增 12 个用例）

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
