<div align="center">

# VoxCraft

**Self-hosted AI inference for audio & video.**

Transcribe · Synthesize · Clone voices · Separate vocals · Translate video speech

[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Python 3.13+](https://img.shields.io/badge/python-3.13+-blue.svg)](pyproject.toml)
[![Docker](https://img.shields.io/badge/docker-ghcr.io-2496ED.svg)](Dockerfile)

[English](README.md) · [简体中文](README_CN.md)

</div>

---

## Why VoxCraft

Commercial audio-AI platforms are powerful but expensive, opaque, and ship your recordings to someone else's servers. VoxCraft runs the same class of capabilities on your own hardware with open-source models.

- No per-minute billing, no data egress
- Open weights only; each capability can swap engines
- Audio / video inference stays local; text tasks (translation, summarization) call any OpenAI-compatible LLM — your choice, your key
- HTTP API and Web UI are first-class entry points — both work for humans and for automation

## Features

| Capability | Endpoint | Default engine | Notes |
|-----------|----------|----------------|-------|
| Speech recognition | `POST /asr` | faster-whisper | Multilingual, timestamped segments |
| Text-to-speech | `POST /tts` | Piper | CPU-friendly, low latency |
| Voice cloning | `POST /tts/clone` | VoxCPM / IndexTTS | Zero-shot from a few seconds of reference audio |
| Vocal separation | `POST /separate` | Demucs | Vocals + instrumental stems |
| **Video translation** | `POST /video-translate` | ASR + LLM + TTS + ffmpeg | Upload a clip, get subtitles, dubbed audio, and a composed video |
| OpenAI-compatible | `POST /v1/audio/{transcriptions,speech}` | — | Drop-in replacement for OpenAI audio SDK clients |
| Admin Web UI | `GET /ui/` | React + Semi Design | Upload, monitor jobs, manage providers |

## Quick Start

```bash
docker run -d --name voxcraft \
  --gpus all \
  -p 8001:8001 \
  -v $(pwd)/models:/models \
  -v $(pwd)/data:/data \
  ghcr.io/OWNER/voxcraft:latest
```

Replace `OWNER` with the user or organization hosting your fork. Then open:

- Web UI → http://localhost:8001/
- API docs (OpenAPI / Swagger) → http://localhost:8001/docs
- Health → http://localhost:8001/health

No GPU? Run on CPU — see [Deployment](#deployment).

## Usage

All business endpoints are **asynchronous**. Submit returns `202 { job_id, status: "pending" }` immediately; inference runs in a serial background queue. Watch for completion via:

- **Server-Sent Events**: `GET /admin/events` — listen for `job_status_changed`
- **Polling**: `GET /jobs/{id}` until `status` is `succeeded`, `failed`, or `cancelled`

Download artifacts with `GET /jobs/{id}/output` (or `?key=<name>` for multi-product jobs). Failed jobs can be re-queued with `POST /jobs/{id}/retry`.

### Speech recognition

```bash
curl -X POST http://localhost:8001/asr -F "audio=@lecture.mp3" -F "language=en"
```

### Text-to-speech

```bash
curl -X POST http://localhost:8001/tts \
  -H "Content-Type: application/json" \
  -d '{"text": "Hello, world.", "voice_id": "piper-zh"}'
```

### Voice cloning

```bash
curl -X POST http://localhost:8001/tts/clone \
  -F "text=Speak with this voice." \
  -F "reference_audio=@speaker.wav"
```

### Vocal separation

```bash
curl -X POST http://localhost:8001/separate -F "audio=@song.mp3"
# Retrieve stems:
# GET /jobs/{id}/output?key=vocals
# GET /jobs/{id}/output?key=instrumental
```

### Video translation

Translate a video or audio file end-to-end: subtitles, dubbed audio, and (for video input) a composed video with replaced audio and embedded subtitles.

```bash
curl -X POST http://localhost:8001/video-translate \
  -F "source_file=@lecture.mp4" \
  -F "target_lang=zh" \
  -F "subtitle_mode=soft" \
  -F "clone_voice=true" \
  -F "align_mode=elastic"
```

Artifacts:

| Key | Contents | When |
|-----|----------|------|
| `subtitle` | Translated SRT | Always |
| `audio` | Dubbed audio (wav) | Always |
| `video` | Composed video | Video input only |

Main parameters:

- `target_lang` (required), `source_lang` (optional; ASR auto-detects)
- `subtitle_mode`: `soft` · `hard` (burned in) · `none`
- `clone_voice` (default `true`): reuse the original speaker's voice (requires a cloning-capable TTS engine)
- `align_mode`: `elastic` · `natural` · `strict` — how translated speech fits the source timeline
- `align_max_speedup` ∈ [1.0, 2.0] (elastic only)
- Provider overrides: `asr_provider_id` / `tts_provider_id` / `llm_provider_id`
- `system_prompt` (≤ 2000 chars): custom translation prompt; a fixed safety suffix is always appended

Prerequisites: at least one LLM provider configured (see [LLM configuration](#llm-configuration)); `ffmpeg` available on the host (the Docker image ships it). Upload limit defaults to 2 GiB — adjust via `VOXCRAFT_MAX_UPLOAD_SIZE` (bytes).

### OpenAI-compatible endpoints

For stateless clients (OpenAI SDK, LangChain, orchestration tools), VoxCraft exposes a synchronous façade speaking the OpenAI audio schema:

```python
from openai import OpenAI

client = OpenAI(base_url="http://localhost:8001/v1", api_key="sk-local")

with open("sample.mp3", "rb") as f:
    r = client.audio.transcriptions.create(model="whisper-1", file=f)
    print(r.text)

audio = client.audio.speech.create(model="tts-1", voice="alloy", input="Hello.")
audio.stream_to_file("out.mp3")
```

- Supported response formats for transcriptions: `json`, `text`, `srt`, `vtt`, `verbose_json`
- Default request timeout: 10 minutes (override via your client)
- Every response carries `X-VoxCraft-Job-Id` for tracing back to the native `/jobs/{id}` record
- Errors follow the OpenAI envelope: `{ "error": { "message", "type", "code" } }`

Voice cloning and vocal separation are not part of the OpenAI standard — use the native endpoints above.

## LLM Configuration

Text tasks delegate to any OpenAI-compatible endpoint. Add providers in Settings → **LLM Config**, or via `POST /admin/llm`:

| Scenario | Base URL | Example model |
|----------|----------|---------------|
| OpenAI | `https://api.openai.com/v1` | `gpt-4o-mini` |
| DeepSeek | `https://api.deepseek.com/v1` | `deepseek-chat` |
| Qwen (Aliyun DashScope) | `https://dashscope.aliyuncs.com/compatible-mode/v1` | `qwen-turbo` |
| Ollama (local) | `http://localhost:11434/v1` | `qwen2.5:7b` |

The **LLM Config** page has a "Fetch models" button that calls `/v1/models` on the endpoint and populates the model dropdown — no need to memorize model ids.

> **Security**: API keys are stored in **plain text** in `data/voxcraft.sqlite` (a self-hosted trade-off). Protect the file: `chmod 600 data/voxcraft.sqlite` and exclude it from shared backups.

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `VOXCRAFT_PORT` | `8001` | HTTP listen port |
| `VOXCRAFT_DB` | `./data/voxcraft.sqlite` | SQLite config + job database |
| `VOXCRAFT_OUTPUT_DIR` | `./data/outputs` | Job artifacts directory |
| `VOXCRAFT_MODELS_DIR` | `./models` | Model weights cache |
| `VOXCRAFT_MAX_UPLOAD_SIZE` | `2147483648` (2 GiB) | Upload size limit for `/video-translate` |
| `VOXCRAFT_LOG_LEVEL` | `INFO` | Log level |
| `VOXCRAFT_PREFERRED_SOURCE` | `hf` | Default model source (`hf` / `ms`) |

## Deployment

### docker compose

```bash
git clone <your-fork> voxcraft
cd voxcraft
cp .env.example .env          # edit as needed

# download default model weights (optional; the UI also offers a download page)
bash scripts/download_models.sh

docker compose up -d
docker compose logs -f voxcraft
```

Prerequisites for the reference setup:

- Linux host (Ubuntu 22.04 / Debian 12 recommended)
- NVIDIA GPU + driver ≥ 535 (optional; see CPU-only below)
- `docker` + `docker compose` + `nvidia-container-toolkit`

### CPU-only

Comment out `deploy.resources.reservations` in `docker-compose.yml`. Whisper falls back to int8 on CPU (slower but functional). Some heavier models (VoxCPM, Demucs) may be impractical without a GPU.

### Data persistence

- `./models/` → `/models` — model weights cache
- `./data/` → `/data` — SQLite state + job artifacts

Delete `./data/` to reset all configuration and history.

## Development

### Backend

```bash
uv sync --all-extras
uv run uvicorn voxcraft.main:app --reload --port 8001
```

### Frontend

```bash
cd web
pnpm install
pnpm dev          # Vite dev server on :5173, API proxied to :8001
```

### Tests

```bash
uv run pytest -v -m "not slow"        # unit + integration
uv run pytest -v -m slow              # includes real-model E2E (requires weights)
cd web && pnpm build                  # TypeScript check + production bundle
```

## Project Layout

```
voxcraft/
├── pyproject.toml          # Python dependencies (managed by uv)
├── Dockerfile              # Multi-stage: Node frontend → Python CUDA runtime
├── docker-compose.yml
├── src/voxcraft/           # Backend
│   ├── api/                #   REST + OpenAI-compatible + SSE
│   ├── providers/          #   ASR / TTS / cloning / separator / LLM client
│   ├── runtime/            #   Scheduler + worker subprocess pool
│   ├── video/              #   Video translation orchestrator + ffmpeg glue
│   ├── db/                 #   SQLModel + Alembic
│   └── llm/                #   OpenAI-compatible LLM client
├── web/                    # Frontend (React + Semi Design + Vite)
├── migrations/             # Alembic revisions
├── scripts/                # Model downloaders, housekeeping
└── tests/                  # unit / integration / e2e
```

## License

- Source code: [MIT](LICENSE)
- Integrated third-party model weights carry their own licenses. Notably **IndexTTS is non-commercial**. Review each model's license before redistribution or commercial use.

Release notes: [CHANGELOG.md](CHANGELOG.md).
