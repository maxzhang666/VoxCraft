<div align="center">

# VoxCraft

**自托管音视频 AI 推理服务**

语音识别 · 语音合成 · 声纹克隆 · 人声分离 · 视频翻译 —— 统一 HTTP 接口（含 OpenAI 兼容层）与一等 Web UI。

[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Python 3.13+](https://img.shields.io/badge/python-3.13+-blue.svg)](pyproject.toml)
[![Docker: GHCR](https://img.shields.io/badge/docker-ghcr.io-2496ED.svg)](https://github.com/features/packages)
[![CI](https://img.shields.io/badge/CI-GitHub%20Actions-blue.svg)](.github/workflows/docker-build.yml)

[English](README.md) · [简体中文](README_CN.md)

</div>

---

## 为什么选择 VoxCraft

商业音频 AI 平台（ElevenLabs、OpenAI TTS、Descript）强大但有三个代价：**按月计费、录音离开你的网络、模型由厂商掌控**。VoxCraft 在你自己的硬件上提供同一层能力：

- **默认自托管**：所有模型本地运行，无需出网
- **只用开源权重**：自选模型库，每种能力允许切换实现
- **成本感知设计**：音视频推理走本地（一次部署长期使用，便宜），文字任务（翻译、摘要）对接任意 OpenAI 兼容 LLM（token 便宜，维护大模型贵）
- **API 一等，UI 同级**：HTTP 接口面向自动化；Web UI 是真正的工作台，不是管理后台

许可说明：代码 MIT 许可；集成的模型权重各有条款（如 IndexTTS 为非商业）。面向个人、研究、内网使用场景。

## 能力

| 能力 | 端点 | 默认 Provider | 备注 |
|------|------|--------------|------|
| 语音识别（ASR） | `POST /asr` | faster-whisper | 带时间戳，多语言 |
| 语音合成（TTS） | `POST /tts` | Piper | CPU 友好 |
| 声纹克隆 | `POST /tts/clone` | VoxCPM / IndexTTS | 零样本参考音频克隆 |
| 人声分离 | `POST /separate` | Demucs | 分离人声与 BGM |
| **视频翻译** | `POST /video-translate` | ASR + LLM + TTS + ffmpeg | 一次产出字幕 / 译文音频 / 合成视频 |
| OpenAI 兼容层 | `POST /v1/audio/{transcriptions,speech}` | — | 直接替换 OpenAI SDK 的 base_url |
| 管理 Web UI | `GET /ui/` | React + Semi Design | 一等交互入口 |

## 快速开始

从 GHCR 拉取 CI 自动构建的镜像（每次 push master 都会更新）：

```bash
docker run -d --name voxcraft \
  --gpus all \
  -p 8001:8001 \
  -v $(pwd)/models:/models \
  -v $(pwd)/data:/data \
  ghcr.io/OWNER/voxcraft:latest
```

把 `OWNER` 替换为托管 fork 的 GitHub 用户/组织名。然后访问：

- UI → http://localhost:8001/
- OpenAPI 文档 → http://localhost:8001/docs
- 健康检查 → http://localhost:8001/health

完整部署方式（`docker compose`、CPU-only、生产提示）见 [部署](#部署)。

## 异步 API

所有业务端点**提交即 202 返回**。真正的推理由后台串行队列驱动（设计上单任务，见 [ADR-008](docs/superpowers/specs/voxcraft/decisions/ADR-008-concurrency.md)；调度后端为主进程或子进程池，见 [ADR-013](docs/superpowers/specs/voxcraft/decisions/ADR-013-process-pool-cancel.md)）。

```
POST /asr | /tts | /tts/clone | /separate | /video-translate
  → 202 Accepted
  { "job_id": "...", "status": "pending" }
```

获取结果两种方式：

1. **订阅 SSE** `GET /admin/events`，监听 `job_status_changed` 进入 `succeeded` 后拉详情（推荐用于 UI）
2. **轮询** `GET /jobs/{id}` 直到 `status ∈ {succeeded, failed, cancelled}`

产物：`GET /jobs/{id}/output`（单产物）或 `GET /jobs/{id}/output?key=<name>`（多产物，如 `vocals` / `instrumental` / `subtitle` / `audio` / `video`）。

失败任务可通过 `POST /jobs/{id}/retry` 复用同一 `job_id` 重新入队（需要原始上传文件仍在磁盘）。完整契约：[05-api.md](docs/superpowers/specs/voxcraft/05-api.md)、[ADR-011](docs/superpowers/specs/voxcraft/decisions/ADR-011-async-by-default.md)。

## OpenAI 兼容端点

对无状态客户端（CLI、SDK、AI 编排工具），VoxCraft 暴露一个同步 Façade，对齐 OpenAI 音频 API schema：

```python
from openai import OpenAI

client = OpenAI(base_url="http://voxcraft.local:8001/v1", api_key="sk-local")

# 语音识别 — 支持 json / text / srt / vtt / verbose_json
with open("sample.mp3", "rb") as f:
    r = client.audio.transcriptions.create(model="whisper-1", file=f)
    print(r.text)

# 语音合成
audio = client.audio.speech.create(model="tts-1", voice="alloy", input="你好，世界")
audio.stream_to_file("out.mp3")
```

HTTP 层阻塞等到任务终态（默认超时 10 分钟）。每个响应带 `X-VoxCraft-Job-Id` 头，便于回溯原生 `/jobs/{id}` 记录。错误走 OpenAI envelope：`{"error": {"message", "type", "code"}}`。

克隆与分离无 OpenAI 标准，请用原生异步端点。完整契约：[ADR-012](docs/superpowers/specs/voxcraft/decisions/ADR-012-openai-compat.md)。

## 视频翻译（v0.4.0）

单个编排端点把外语视频/音频转成目标语言 —— 一次请求输出字幕、配音音频和合成视频。

```bash
curl -X POST http://voxcraft.local:8001/video-translate \
  -F "source_file=@lecture.mp4" \
  -F "target_lang=zh" \
  -F "subtitle_mode=soft" \
  -F "clone_voice=true" \
  -F "align_mode=elastic"
# → 202 { "job_id": "...", "status": "pending" }
```

产物（通过 `GET /jobs/{id}/output?key=<name>` 下载）：

| key | 内容 | 适用 |
|-----|------|------|
| `subtitle` | 译文 SRT | 总是产出 |
| `audio` | 译文音频（wav） | 总是产出 |
| `video` | 合成视频（音轨替换 + 字幕） | 仅视频输入 |

关键参数（完整说明见 [ADR-014](docs/superpowers/specs/voxcraft/decisions/ADR-014-video-translate-orchestration.md)）：

- `target_lang`（必填）、`source_lang`（可选；留空则 ASR 自动识别）
- `subtitle_mode`：`soft`（字幕轨）· `hard`（烧录进画面）· `none`
- `clone_voice`（默认 `true`）：用原说话人音色合成；需要支持克隆的 TTS Provider
- `align_mode`：`elastic`（默认）· `natural` · `strict` —— 控制译文与原时间轴的对齐方式
- `align_max_speedup` ∈ [1.0, 2.0]（仅 elastic 生效）
- Provider 覆盖：`asr_provider_id` / `tts_provider_id` / `llm_provider_id`
- `system_prompt`（≤ 2000 字符）：自定义翻译 prompt；内置安全后缀总会拼接在其后

前置依赖：

- 至少配置一个 LLM Provider（设置 → LLM 配置，或 `POST /admin/llm`），否则返回 `LLM_NOT_CONFIGURED`
- 启用克隆需所选 TTS Provider 声明 `clone` capability（VoxCPM、IndexTTS）
- 系统需有 `ffmpeg`（Docker 镜像已预装；本地开发 `brew install ffmpeg` / `apt install ffmpeg fonts-noto-cjk`）

上传大小上限：默认 **2 GiB**；通过 `VOXCRAFT_MAX_UPLOAD_SIZE` env 调整（单位字节）。

## LLM 配置（v0.3.0）

文字任务（翻译、摘要、字幕润色）对接任何 OpenAI 兼容端点。在 UI（设置 → LLM 配置）或 `POST /admin/llm` 新增：

| 场景 | Base URL | 示例 Model |
|------|----------|-----------|
| OpenAI | `https://api.openai.com/v1` | `gpt-4o-mini` |
| DeepSeek | `https://api.deepseek.com/v1` | `deepseek-chat` |
| Qwen（阿里云 DashScope） | `https://dashscope.aliyuncs.com/compatible-mode/v1` | `qwen-turbo` |
| 本地 Ollama | `http://localhost:11434/v1` | `qwen2.5:7b` |

> **安全提示**：API Key **明文存储于 `data/voxcraft.sqlite`**（自托管场景的设计取舍）。请保护数据库文件：`chmod 600 data/voxcraft.sqlite`，备份时也注意不要上传到公共位置。

## 部署

### 前置

- Linux（推荐 Ubuntu 22.04 / Debian 12）
- NVIDIA GPU + 驱动 ≥ 535（CPU-only 部署可用，吞吐量较低）
- `docker` + `docker compose` + `nvidia-container-toolkit`

### docker compose

```bash
git clone <repo> voxcraft
cd voxcraft

cp .env.example .env
# 按需编辑 .env

# 下载模型到 ./models/（仅 mock 测试可跳过）
bash scripts/download_models.sh

docker compose up -d
docker compose logs -f voxcraft
```

访问：

- UI：`http://<host>:8001/`（自动重定向到 `/ui/`）
- OpenAPI：`http://<host>:8001/docs`
- 健康：`http://<host>:8001/health`

### CPU-only

编辑 `docker-compose.yml`，注释 `deploy.resources.reservations` 整段；Whisper 用 int8 跑 CPU（速度较慢但可用）。

### 数据持久化

- `./models/` → 容器内 `/models`（模型权重）
- `./data/` → 容器内 `/data`（SQLite 配置 + 任务产物）

删除 `./data/` 即重置所有状态。

## 本地开发

### 后端

```bash
uv sync --all-extras
uv run uvicorn voxcraft.main:app --reload --port 8001
```

### 前端

```bash
cd web
pnpm install
pnpm dev          # Vite 开发服务器（:5173），API 代理到 :8001
```

### 测试

```bash
uv run pytest -v -m "not slow"        # 单元 + 集成（约 10 秒）
uv run pytest -v -m slow              # 含真模型 E2E（需要模型文件）
cd web && pnpm build                  # TypeScript 检查 + 生产打包
```

## 项目结构

```
voxcraft/
├── pyproject.toml          # Python 依赖（uv 管理）
├── Dockerfile              # 多阶段：Node 构建前端 → Python CUDA 运行时
├── docker-compose.yml
├── src/voxcraft/           # 后端
│   ├── api/                #   REST + OpenAI 兼容 + SSE
│   ├── providers/          #   ASR / TTS / 克隆 / 分离（+ LLM 客户端）
│   ├── runtime/            #   调度器 + worker 子进程池
│   ├── video/              #   视频翻译编排器 + ffmpeg 胶水
│   ├── db/                 #   SQLModel + Alembic
│   └── llm/                #   OpenAI 兼容 LLM 客户端
├── web/                    # 前端（React + Semi Design + Vite）
├── migrations/             # Alembic 迁移
├── scripts/                # 模型下载器、清理脚本
└── tests/                  # unit / integration / e2e
```

## 架构与决策

设计文档与 ADR（Architecture Decision Records）位于 `docs/superpowers/`：

- 入口：[docs/superpowers/specs/voxcraft/README.md](docs/superpowers/specs/voxcraft/README.md)
- ADR 索引：[docs/superpowers/specs/voxcraft/decisions/](docs/superpowers/specs/voxcraft/decisions/)

> `docs/` 在仓库上游被显式 git-ignore（属于内部设计沉淀）。发布代码本身足以自解释；ADR 仅供维护者参考。

## Roadmap

当前版本：**v0.4.0** —— 视频翻译编排（[CHANGELOG](CHANGELOG.md)）。

后续：

- **v0.5**：可观测性打磨（Prometheus，结构化任务审计）
- **v1.0**：稳定化 —— 测试覆盖、running 任务取消传播

## 贡献

这是一个小而有态度的项目。如果 PR / Issue 与 [01-positioning.md](docs/superpowers/specs/voxcraft/01-positioning.md) 的设计原则对齐，欢迎提交。重大架构变更需要新立 ADR。

## License

- 源代码：[MIT](LICENSE)
- 集成的第三方模型权重各有条款（IndexTTS 为非商业）。再分发与商业使用请各自核对模型许可
- `docs/` 下的设计文档仅作本地沉淀，不随仓库发布
