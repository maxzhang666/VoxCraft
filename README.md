# VoxCraft

自托管多模态音频推理服务：ASR / TTS / 声纹克隆 / 人声分离。

**定位**：非商业自托管（家庭/内部/个人研究）。参见 [设计 Spec](docs/superpowers/specs/voxcraft/README.md)。

## 能力

| 能力 | API 端点 | 默认 Provider |
|------|---------|---------------|
| 语音识别 | `POST /asr` | faster-whisper |
| 语音合成 | `POST /tts` | Piper |
| 声纹克隆 | `POST /tts/clone` | VoxCPM / IndexTTS |
| 人声分离 | `POST /separate` | Demucs |
| 管理 UI | `GET /ui/` | React + Semi |

### 异步语义（v0.1.3 起）

所有业务端点**提交即返回**，真正执行由后台 runner 调度：

```
POST /asr | /tts | /tts/clone | /separate
  → 202 Accepted
  { "job_id": "uuid", "status": "pending" }
```

获取结果的两条路径：

1. **订阅 SSE** `GET /admin/events`（推荐）——监听 `job_status_changed`，收到 `succeeded` 时再拉详情
2. **轮询** `GET /jobs/{id}` 直到 `status ∈ {succeeded, failed, cancelled}`

产物下载：`GET /jobs/{id}/output`（或 `?key=vocals` / `?key=instrumental` 多产物场景）。

失败任务支持 `POST /jobs/{id}/retry` 复用同一 `job_id` 重试（ASR/Clone/Separate 需原始上传仍在磁盘）。

详见 [ADR-011](docs/superpowers/specs/voxcraft/decisions/ADR-011-async-by-default.md) 与 [05-api.md](docs/superpowers/specs/voxcraft/05-api.md)。

### OpenAI 兼容 API（v0.1.4 起）

无状态客户端（CLI、SDK、AI 编排工具）可直接用 OpenAI 协议访问 ASR / TTS：

```http
POST /v1/audio/transcriptions   # 对齐 OpenAI Whisper
POST /v1/audio/speech           # 对齐 OpenAI TTS
```

HTTP 层同步返回（内核仍异步；入口等到 Job 终态再回包），默认超时 10 分钟。每个响应带 `X-VoxCraft-Job-Id` 头便于追溯。

```python
from openai import OpenAI
client = OpenAI(base_url="http://voxcraft.local:8001/v1", api_key="sk-local")

# ASR（多种 response_format：json / text / srt / vtt / verbose_json）
with open("sample.mp3", "rb") as f:
    r = client.audio.transcriptions.create(model="whisper-1", file=f)
    print(r.text)

# TTS
audio = client.audio.speech.create(model="tts-1", voice="alloy", input="你好")
audio.stream_to_file("out.mp3")
```

错误响应走 OpenAI envelope：`{"error": {"message", "type", "code"}}`。

Clone / Separate 不在 OpenAI 标准内，请用 VoxCraft 原生异步端点。详见 [ADR-012](docs/superpowers/specs/voxcraft/decisions/ADR-012-openai-compat.md)。

## 部署（Docker）

### 前置

- Linux（推荐 Ubuntu 22.04 / Debian 12）
- NVIDIA GPU + 驱动 ≥ 535
- `docker` + `docker compose` + `nvidia-container-toolkit`

### 启动

```bash
git clone <repo> voxcraft
cd voxcraft

# 环境变量模板
cp .env.example .env
# 按需编辑 .env（如 OPENAI_API_KEY，用于未来翻译能力）

# 下载模型到 ./models/（按需，Mock 测试可跳过）
bash scripts/download_models.sh

# 一键启动（首次构建约 5-10 分钟）
docker compose up -d

# 查看日志
docker compose logs -f voxcraft
```

访问：
- UI：`http://<host>:8001/`（自动重定向到 `/ui/`）
- API 文档：`http://<host>:8001/docs`
- 健康：`http://<host>:8001/health`

### 无 GPU 环境

编辑 `docker-compose.yml`，注释 `deploy.resources.reservations` 整段；Whisper 可用 CPU（`compute_type=int8`，速度变慢）。

### 数据持久化

- `./models/` → 容器内 `/models`（模型权重）
- `./data/` → 容器内 `/data`（SQLite + 产物音频）

容器重启数据不丢失；删除 `./data/` 即清空所有配置与历史。

## 开发（本地）

### 后端

```bash
uv sync --all-extras
uv run uvicorn voxcraft.main:app --reload --port 8001
```

### 前端

```bash
cd web
pnpm install
pnpm dev          # Vite 开发服务器（:5173 代理 API 到 :8001）
```

### 测试

```bash
uv run pytest -v -m "not slow"        # 单元 + 集成
uv run pytest -v -m slow              # 含真模型 E2E（需模型文件）
cd web && pnpm build                  # 前端类型 + 生产构建
```

## 项目结构

```
voxcraft/
├── pyproject.toml       # Python 依赖（uv 管理）
├── Dockerfile           # 多阶段：Node 构建 + Python CUDA 运行时
├── docker-compose.yml   # 一键启动
├── src/voxcraft/        # 后端
├── web/                 # 前端 (React + Semi + Vite)
├── migrations/          # Alembic
├── scripts/             # 模型下载等
├── tests/               # unit / integration / e2e
└── docs/                # 设计 Spec + Plan（本地沉淀，不入 git）
```

## License

- 代码：MIT
- 集成的第三方模型权重各有独立条款（如 IndexTTS 为非商业许可）；仅限自托管 / 非商业场景使用
- 设计文档（docs/）仅作本地沉淀
