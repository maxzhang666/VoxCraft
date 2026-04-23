# Changelog

All notable changes to this project will be documented in this file.

## [v0.2.0] — 2026-04-23

架构跃迁版本。核心：`Scheduler` 抽象 + 进程池真取消（ADR-013）、OpenAI 兼容 API 层（ADR-012）、
全量异步化稳定化（ADR-011）、体验打磨。

生产部署可通过 `VOXCRAFT_SCHEDULER_BACKEND=pool` 切换到真取消后端；默认仍为 `inprocess` 保证零依赖。

### Added — ADR-013 进程池 + 真取消实装
- **`PoolScheduler`**（`runtime/pool_scheduler.py`）：worker 子进程常驻 + mp.Queue 双向 IPC + asyncio.Future 等待。Cancel running 任务 = SIGTERM worker + respawn；真释放 GPU
- **`worker_process.py`**：worker 子进程主循环（LRU=1 本进程内维护，同步执行，无 asyncio）。支持 `extra_class_imports` 测试注入 Mock Provider
- **`worker_runners.py`**：四个 kind 的纯同步 runner（ASR/TTS/Clone/Separate），从 `business.py` 提取，pickle-safe 输入输出
- **`runtime/scheduler_api.py`**：`Scheduler` Protocol + `JobRequest` / `JobResult` dataclass（跨进程 pickle）
- `start_method` 参数（`spawn`/`forkserver`/`fork`）：生产用 spawn（CUDA 安全），测试用 forkserver（绕过 pytest 下 sys.argv[0] re-import 问题）
- **5 个 pool 专项测试**：submit / 串行 / cancel running + respawn / cancel unknown / provider unknown；155 passed, 3 skipped（原 150 + 5 新）

### Changed — ADR-013 接入
- `InProcessScheduler.submit(JobRequest)`：新接口兼容 `PoolScheduler`；保留旧 `run(coro_fn)` 向后兼容
- `business.run_job`：从"Provider 实例化 + scheduler.run(closure)"改为"打包 `JobRequest` → `scheduler.submit(req)` → 按 `JobResult` 写回 DB"。四个 `_run_*` 函数删除（逻辑搬到 `worker_runners.py`）
- `jobs.py DELETE`：running 任务调 `scheduler.cancel(job_id)`；返回 True 时即时标 cancelled + 发 SSE；False 时保留旧行为（硬删 + 后台跑完）
- `main.py lifespan`：按 `settings.scheduler_backend` 实例化 InProcess / Pool；shutdown 时调度器优雅停机
- **默认 backend 仍为 `inprocess`**（测试友好、CI 零依赖）；生产部署可 `VOXCRAFT_SCHEDULER_BACKEND=pool` 开启真取消

### Added（前期）
- `Scheduler.cancel(job_id) -> bool` 接口（ADR-013 前置）；InProcess 实现固定返回 False
- `Settings.scheduler_backend: Literal["inprocess","pool"]`
- **pytest-cov 接入 + 80% 覆盖率门槛**：`make coverage` 一键跑；HTML 输出 `htmlcov/`；dev 依赖加 `pytest-cov>=6.0`。当前基线 **85.0%**（TOTAL）
- **首页快捷入口**：Dashboard 四个能力大卡片（🎧/🔊/🎭/🎸）点击即跳对应能力页
- **首页最近任务 SSE 实时刷新**：订阅 `job_status_changed`，状态变化即刻反映；10s 兜底轮询保留

### Changed
- **Vite bundle 拆包**：原 1.4MB 单 chunk → `index`(40KB 业务) / `react-vendor`(156KB) / `vendor`(366KB) / `semi`(886KB)；浏览器并发下载 + 缓存命中率↑；改动业务代码只失效 40KB index chunk
- **GlobalJobsQueue 设置页**：过滤补齐 `cancelled` 选项；订阅 SSE `job_status_changed` / `job_progress` 实时刷新；加操作列（详情 / 重试 / 删除带 Popconfirm）；接入 `JobDetailsModal`
- **SystemDiagnosis 设置页**：加 30s 周期刷新 health/models；订阅 SSE `model_loaded` / `model_unloaded` / `provider_failed` 实时响应

### Removed（死代码）
- `api/schemas/asr.py`（`AsrResponse` / `AsrSegmentSchema`）——v0.1.3 异步化后无引用
- `api/schemas/separate.py`（`SeparateResponse`）——同上
- `api/schemas/common.py`（`ErrorResponse` / `ErrorDetail`）——错误处理走 `error_handlers.py` 手写 dict，此 schema 从未引用
- `pages/Placeholder.tsx`——无引用

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
