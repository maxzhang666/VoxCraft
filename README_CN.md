<div align="center">

# VoxCraft

**自托管音视频 AI 推理服务**

语音识别 · 语音合成 · 声纹克隆 · 人声分离 · 视频翻译

[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Python 3.13+](https://img.shields.io/badge/python-3.13+-blue.svg)](pyproject.toml)
[![Docker](https://img.shields.io/badge/docker-ghcr.io-2496ED.svg)](Dockerfile)

[English](README.md) · [简体中文](README_CN.md)

</div>

---

## 为什么选择 VoxCraft

商业音频 AI 平台功能强但不透明，按分钟计费，录音还得上传到别人的服务器。VoxCraft 在你自己的硬件上提供同一层能力，只用开源模型。

- 无按量计费，无数据出网
- 只用开源权重；每种能力可替换引擎
- 音视频推理本地运行；文字任务（翻译、摘要）对接任意 OpenAI 兼容 LLM（你选 endpoint、你管 API Key）
- HTTP API 与 Web UI 同为一等入口 —— 自动化和人工操作都顺手

## 功能

| 能力 | 端点 | 默认引擎 | 说明 |
|------|------|---------|------|
| 语音识别 | `POST /api/asr` | faster-whisper | 多语言，带分段时间戳 |
| 语音合成 | `POST /api/tts` | Piper | CPU 友好，延迟低 |
| 声纹克隆 | `POST /api/tts/clone` | VoxCPM / IndexTTS | 几秒参考音频即可零样本克隆 |
| 人声分离 | `POST /api/separate` | Demucs | 分离人声与 BGM stems |
| **视频翻译** | `POST /api/video-translate` | ASR + LLM + TTS + ffmpeg | 一次请求得到字幕、配音、合成视频 |
| OpenAI 兼容层 | `POST /v1/audio/{transcriptions,speech}` | — | 直接替换 OpenAI SDK base_url |
| Web UI | `GET /ui/` | React + Semi Design | 上传、监控任务、管理 Provider |

## 快速开始

```bash
docker run -d --name voxcraft \
  --gpus all \
  -p 8001:8001 \
  -v $(pwd)/models:/models \
  -v $(pwd)/data:/data \
  ghcr.io/OWNER/voxcraft:latest
```

把 `OWNER` 换成托管 fork 的 GitHub 用户或组织名。然后访问：

- Web UI → http://localhost:8001/
- API 文档（OpenAPI / Swagger）→ http://localhost:8001/docs
- 健康检查 → http://localhost:8001/api/health

无 GPU？见 [部署](#部署)。

## 使用

所有业务端点都是**异步**的。提交立刻返回 `202 { job_id, status: "pending" }`；推理在后台串行队列中执行。获取结果两种方式：

- **Server-Sent Events**：`GET /api/admin/events`，监听 `job_status_changed`
- **轮询**：`GET /api/jobs/{id}`，直到 `status ∈ {succeeded, failed, cancelled}`

产物下载：`GET /api/jobs/{id}/output`（单产物）或 `?key=<name>`（多产物）。失败任务可用 `POST /api/jobs/{id}/retry` 重新入队。

### 语音识别

```bash
curl -X POST http://localhost:8001/api/asr -F "audio=@lecture.mp3" -F "language=en"
```

### 语音合成

```bash
curl -X POST http://localhost:8001/api/tts \
  -H "Content-Type: application/json" \
  -d '{"text": "你好，世界。", "voice_id": "piper-zh"}'
```

### 声纹克隆

```bash
curl -X POST http://localhost:8001/api/tts/clone \
  -F "text=用这个声音说话。" \
  -F "reference_audio=@speaker.wav"
```

### 人声分离

```bash
curl -X POST http://localhost:8001/api/separate -F "audio=@song.mp3"
# 拿 stems：
# GET /api/jobs/{id}/output?key=vocals
# GET /api/jobs/{id}/output?key=instrumental
```

### 视频翻译

端到端处理视频或音频：字幕 + 配音音频 + 合成视频（视频输入时）。

```bash
curl -X POST http://localhost:8001/api/video-translate \
  -F "source_file=@lecture.mp4" \
  -F "target_lang=zh" \
  -F "subtitle_mode=soft" \
  -F "clone_voice=true" \
  -F "align_mode=elastic"
```

产物：

| key | 内容 | 场景 |
|-----|------|------|
| `subtitle` | 译文 SRT | 总是产出 |
| `audio` | 译文音频（wav） | 总是产出 |
| `video` | 合成视频 | 仅视频输入 |

主要参数：

- `target_lang`（必填）、`source_lang`（可选；留空则 ASR 自动识别）
- `subtitle_mode`：`soft`（字幕轨）· `hard`（烧录进画面）· `none`
- `clone_voice`（默认 `true`）：用原说话人音色合成（需要支持克隆的 TTS 引擎）
- `align_mode`：`elastic` · `natural` · `strict` —— 译文如何匹配原时间轴
- `align_max_speedup` ∈ [1.0, 2.0]（仅 elastic 生效）
- Provider 覆盖：`asr_provider_id` / `tts_provider_id` / `llm_provider_id`
- `system_prompt`（≤ 2000 字符）：自定义翻译 prompt；固定安全后缀总会拼接其后

前置要求：至少一个 LLM Provider（见 [LLM 配置](#llm-配置)）；宿主机可用 `ffmpeg`（Docker 镜像已自带）。上传大小默认 2 GiB，通过 `VOXCRAFT_MAX_UPLOAD_SIZE` 调整（字节）。

### OpenAI 兼容端点

无状态客户端（OpenAI SDK、LangChain、编排工具）可直接用 OpenAI 音频 schema：

```python
from openai import OpenAI

client = OpenAI(base_url="http://localhost:8001/v1", api_key="sk-local")

with open("sample.mp3", "rb") as f:
    r = client.audio.transcriptions.create(model="whisper-1", file=f)
    print(r.text)

audio = client.audio.speech.create(model="tts-1", voice="alloy", input="你好")
audio.stream_to_file("out.mp3")
```

- 转录响应格式：`json`、`text`、`srt`、`vtt`、`verbose_json`
- 默认请求超时 10 分钟（客户端可覆盖）
- 每个响应带 `X-VoxCraft-Job-Id` 头，用于回溯原生 `/api/jobs/{id}` 记录
- 错误走 OpenAI envelope：`{ "error": { "message", "type", "code" } }`

声纹克隆和人声分离不在 OpenAI 标准内，请用上面的原生端点。

## LLM 配置

文字任务委托给任意 OpenAI 兼容端点。在设置 → **LLM 配置**页新增，或通过 `POST /api/admin/llm`：

| 场景 | Base URL | 示例 model |
|------|----------|-----------|
| OpenAI | `https://api.openai.com/v1` | `gpt-4o-mini` |
| DeepSeek | `https://api.deepseek.com/v1` | `deepseek-chat` |
| Qwen（阿里云 DashScope） | `https://dashscope.aliyuncs.com/compatible-mode/v1` | `qwen-turbo` |
| Ollama（本地） | `http://localhost:11434/v1` | `qwen2.5:7b` |

**LLM 配置**页的 Model 字段提供"获取"按钮，点击调用目标端点的 `/v1/models` 拉取可用模型列表填入下拉——不必手动记 model id。

> **安全提示**：API Key **明文存储**于 `data/voxcraft.sqlite`（自托管场景的设计取舍）。请保护该文件：`chmod 600 data/voxcraft.sqlite`，并在备份时避免上传到公共位置。

## 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `VOXCRAFT_PORT` | `8001` | HTTP 监听端口 |
| `VOXCRAFT_DB` | `./data/voxcraft.sqlite` | SQLite 配置与任务库 |
| `VOXCRAFT_OUTPUT_DIR` | `./data/outputs` | 任务产物目录 |
| `VOXCRAFT_MODELS_DIR` | `./models` | 模型权重缓存 |
| `VOXCRAFT_MAX_UPLOAD_SIZE` | `2147483648`（2 GiB） | `/api/video-translate` 上传大小上限 |
| `VOXCRAFT_LOG_LEVEL` | `INFO` | 日志级别 |
| `VOXCRAFT_PREFERRED_SOURCE` | `hf` | 默认模型源（`hf` / `ms`） |

## 部署

### docker compose

```bash
git clone <your-fork> voxcraft
cd voxcraft
cp .env.example .env          # 按需编辑

# 下载默认模型权重（可选；UI 也提供下载页）
bash scripts/download_models.sh

docker compose up -d
docker compose logs -f voxcraft
```

参考环境：

- Linux 宿主（推荐 Ubuntu 22.04 / Debian 12）
- NVIDIA GPU + 驱动 ≥ 535（可选，见下方 CPU-only）
- `docker` + `docker compose` + `nvidia-container-toolkit`

### CPU-only

注释掉 `docker-compose.yml` 的 `deploy.resources.reservations` 段。Whisper 可用 int8 跑 CPU（较慢但可用）。部分较大的模型（VoxCPM、Demucs）无 GPU 可能不实用。

### 数据持久化

- `./models/` → `/models`（模型权重缓存）
- `./data/` → `/data`（SQLite 状态 + 任务产物）

删除 `./data/` 即重置所有配置与历史。

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
uv run pytest -v -m "not slow"        # 单元 + 集成
uv run pytest -v -m slow              # 含真模型 E2E（需模型权重）
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
│   ├── providers/          #   ASR / TTS / 克隆 / 分离 / LLM 客户端
│   ├── runtime/            #   调度器 + worker 子进程池
│   ├── video/              #   视频翻译编排器 + ffmpeg 胶水
│   ├── db/                 #   SQLModel + Alembic
│   └── llm/                #   OpenAI 兼容 LLM 客户端
├── web/                    # 前端（React + Semi Design + Vite）
├── migrations/             # Alembic 迁移
├── scripts/                # 模型下载器、清理脚本
└── tests/                  # unit / integration / e2e
```

## License

- 源代码：[MIT](LICENSE)
- 集成的第三方模型权重各有许可（**IndexTTS 为非商业许可**等）。再分发或商业使用前请各自核对

发布历史：[CHANGELOG.md](CHANGELOG.md)。
