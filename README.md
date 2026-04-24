<div align="center">

# VoxCraft

**Self-hosted AI inference service for audio & video.**

Speech recognition · Text-to-speech · Voice cloning · Vocal separation · Video translation — behind one OpenAI-compatible HTTP surface and a first-class web UI.

[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Python 3.13+](https://img.shields.io/badge/python-3.13+-blue.svg)](pyproject.toml)
[![Docker: GHCR](https://img.shields.io/badge/docker-ghcr.io-2496ED.svg)](https://github.com/features/packages)
[![CI](https://img.shields.io/badge/CI-GitHub%20Actions-blue.svg)](.github/workflows/docker-build.yml)

[English](README.md) · [简体中文](README_CN.md)

</div>

---

## Why VoxCraft

Commercial audio-AI platforms (ElevenLabs, OpenAI TTS, Descript) are powerful but come with three costs: **monthly bills, uploaded recordings leaving your network, and vendor-controlled models**. VoxCraft runs the same class of capabilities on your own hardware:

- **Self-hosted by default** — every model runs locally; no egress required
- **Open weights only** — pick your own model library, swap implementations per capability
- **Cost-aware by design** — audio/video inference runs locally (cheap after one-time setup); text tasks (translation, summarization) delegate to any OpenAI-compatible LLM endpoint (tokens are cheap, model ops aren't)
- **API first, UI equal** — HTTP endpoints for automation; a web UI that is a true workspace, not a dashboard

License note: the code is MIT. Integrated model weights carry their own terms (some, such as IndexTTS, are non-commercial). Intended for personal, research, and internal-network use.

## Capabilities

| Capability | Endpoint | Default Provider | Notes |
|-----------|----------|------------------|-------|
| Speech recognition (ASR) | `POST /asr` | faster-whisper | Timestamps, multilingual |
| Text-to-speech (TTS) | `POST /tts` | Piper | CPU-friendly |
| Voice cloning | `POST /tts/clone` | VoxCPM / IndexTTS | Zero-shot from reference audio |
| Vocal separation | `POST /separate` | Demucs | Vocals + instrumental stems |
| **Video translation** | `POST /video-translate` | ASR + LLM + TTS + ffmpeg | One-shot subtitle / dubbed audio / composed video |
| OpenAI-compatible layer | `POST /v1/audio/{transcriptions,speech}` | — | Drop-in for OpenAI SDK clients |
| Admin web UI | `GET /ui/` | React + Semi Design | First-class interactive entry point |

## Quick Start

Pull the pre-built image from GHCR (published by CI on every push to `master`):

```bash
docker run -d --name voxcraft \
  --gpus all \
  -p 8001:8001 \
  -v $(pwd)/models:/models \
  -v $(pwd)/data:/data \
  ghcr.io/OWNER/voxcraft:latest
```

Replace `OWNER` with the GitHub user/org hosting this fork. Then:

- UI → http://localhost:8001/
- OpenAPI docs → http://localhost:8001/docs
- Health → http://localhost:8001/health

See [Deployment](#deployment) for `docker compose`, CPU-only, and production notes.

## Asynchronous API

All business endpoints return **`202 Accepted` immediately**. The actual inference runs in a serial background queue (single-task by design; see [ADR-008](docs/superpowers/specs/voxcraft/decisions/ADR-008-concurrency.md)) and is driven by a scheduler (in-process or subprocess pool; see [ADR-013](docs/superpowers/specs/voxcraft/decisions/ADR-013-process-pool-cancel.md)).

```
POST /asr | /tts | /tts/clone | /separate | /video-translate
  → 202 Accepted
  { "job_id": "...", "status": "pending" }
```

Two ways to obtain results:

1. **Subscribe to SSE** at `GET /admin/events` and watch for `job_status_changed` transitions to `succeeded` — then fetch details (recommended for UIs)
2. **Poll** `GET /jobs/{id}` until `status ∈ {succeeded, failed, cancelled}`

Artifacts are served via `GET /jobs/{id}/output` (single product) or `GET /jobs/{id}/output?key=<name>` (multi-product, e.g. `vocals` / `instrumental` / `subtitle` / `audio` / `video`).

Failed jobs can be re-queued with `POST /jobs/{id}/retry` (the same `job_id` is reused; the original upload must still be on disk). Full contract: [05-api.md](docs/superpowers/specs/voxcraft/05-api.md), [ADR-011](docs/superpowers/specs/voxcraft/decisions/ADR-011-async-by-default.md).

## OpenAI-Compatible Endpoints

For stateless clients (CLIs, SDKs, orchestration tools), VoxCraft exposes a synchronous façade that speaks the OpenAI audio schema:

```python
from openai import OpenAI

client = OpenAI(base_url="http://voxcraft.local:8001/v1", api_key="sk-local")

# Transcription — supports json / text / srt / vtt / verbose_json
with open("sample.mp3", "rb") as f:
    r = client.audio.transcriptions.create(model="whisper-1", file=f)
    print(r.text)

# Speech synthesis
audio = client.audio.speech.create(model="tts-1", voice="alloy", input="Hello, world.")
audio.stream_to_file("out.mp3")
```

The HTTP layer blocks until the job reaches a terminal state (default timeout 10 minutes). Every response carries an `X-VoxCraft-Job-Id` header so the equivalent native `/jobs/{id}` record can be queried. Errors follow the OpenAI envelope: `{"error": {"message", "type", "code"}}`.

Voice cloning and vocal separation have no OpenAI standard; use the native async endpoints. Full contract: [ADR-012](docs/superpowers/specs/voxcraft/decisions/ADR-012-openai-compat.md).

## Video Translation (v0.4.0)

A single orchestrated endpoint that converts a spoken-language video or audio file into the target language — producing subtitles, dubbed audio, and a composed video in one request.

```bash
curl -X POST http://voxcraft.local:8001/video-translate \
  -F "source_file=@lecture.mp4" \
  -F "target_lang=zh" \
  -F "subtitle_mode=soft" \
  -F "clone_voice=true" \
  -F "align_mode=elastic"
# → 202 { "job_id": "...", "status": "pending" }
```

Artifacts (always produced when applicable; retrieved via `GET /jobs/{id}/output?key=<name>`):

| Key | Contents | Availability |
|-----|----------|--------------|
| `subtitle` | Translated SRT | Always |
| `audio` | Translated dubbed audio (wav) | Always |
| `video` | Composed video with replaced audio and embedded subtitles | Video input only |

Key parameters (full reference in [ADR-014](docs/superpowers/specs/voxcraft/decisions/ADR-014-video-translate-orchestration.md)):

- `target_lang` (required), `source_lang` (optional; ASR auto-detects if omitted)
- `subtitle_mode`: `soft` (muxed subtitle track) · `hard` (burned into frames) · `none`
- `clone_voice` (default `true`): reuses the original speaker's voice via a cloning-capable TTS provider
- `align_mode`: `elastic` (default) · `natural` · `strict` — controls how translated speech is fit against the source timeline
- `align_max_speedup` ∈ [1.0, 2.0] (elastic only)
- Provider overrides: `asr_provider_id` / `tts_provider_id` / `llm_provider_id`
- `system_prompt` (≤ 2000 chars) — custom translation prompt; built-in safety suffix is always appended

Prerequisites:

- At least one LLM provider configured (Settings → LLM, or `POST /admin/llm`) — otherwise `LLM_NOT_CONFIGURED`
- For cloning, the selected TTS provider must declare the `clone` capability (VoxCPM, IndexTTS)
- System `ffmpeg` must be available (pre-installed in the Docker image; `brew install ffmpeg` / `apt install ffmpeg fonts-noto-cjk` for local development)

Upload size cap: **2 GiB** by default; configurable via `VOXCRAFT_MAX_UPLOAD_SIZE` (bytes).

## LLM Configuration (v0.3.0)

Text tasks (translation, summarization, subtitle polishing) delegate to any OpenAI-compatible endpoint. Configure providers in the UI (Settings → LLM Config) or via `POST /admin/llm`:

| Scenario | Base URL | Example model |
|----------|----------|---------------|
| OpenAI | `https://api.openai.com/v1` | `gpt-4o-mini` |
| DeepSeek | `https://api.deepseek.com/v1` | `deepseek-chat` |
| Qwen (Aliyun DashScope) | `https://dashscope.aliyuncs.com/compatible-mode/v1` | `qwen-turbo` |
| Ollama (local) | `http://localhost:11434/v1` | `qwen2.5:7b` |

> **Security**: API keys are stored **in plaintext** in `data/voxcraft.sqlite` (self-hosted trade-off). Protect the database file: `chmod 600 data/voxcraft.sqlite`, and exclude it from shared backups.

## Deployment

### Prerequisites

- Linux (Ubuntu 22.04 / Debian 12 recommended)
- NVIDIA GPU + driver ≥ 535 (CPU-only deployment is supported with reduced throughput)
- `docker` + `docker compose` + `nvidia-container-toolkit`

### docker compose

```bash
git clone <repo> voxcraft
cd voxcraft

cp .env.example .env
# edit .env as needed

# download models into ./models/ (skip for mock-only testing)
bash scripts/download_models.sh

docker compose up -d
docker compose logs -f voxcraft
```

Endpoints:

- UI: `http://<host>:8001/` (auto-redirects to `/ui/`)
- OpenAPI: `http://<host>:8001/docs`
- Health: `http://<host>:8001/health`

### CPU-only

Comment out `deploy.resources.reservations` in `docker-compose.yml`. Whisper falls back to int8 on CPU (slower but functional).

### Persistence

- `./models/` → `/models` (model weights)
- `./data/` → `/data` (SQLite config + job artifacts)

Delete `./data/` to reset all state.

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
uv run pytest -v -m "not slow"        # unit + integration (~10s)
uv run pytest -v -m slow              # incl. real-model E2E (requires weights)
cd web && pnpm build                  # TS check + production bundle
```

## Project Layout

```
voxcraft/
├── pyproject.toml          # Python dependencies (uv managed)
├── Dockerfile              # Multi-stage: Node frontend → Python CUDA runtime
├── docker-compose.yml
├── src/voxcraft/           # Backend
│   ├── api/                #   REST + OpenAI-compatible + SSE
│   ├── providers/          #   ASR / TTS / cloning / separator / (LLM client)
│   ├── runtime/            #   Scheduler + worker subprocess pool
│   ├── video/              #   Video translation orchestrator + ffmpeg glue
│   ├── db/                 #   SQLModel + Alembic
│   └── llm/                #   OpenAI-compatible LLM client
├── web/                    # Frontend (React + Semi Design + Vite)
├── migrations/             # Alembic revisions
├── scripts/                # Model downloaders, housekeeping
└── tests/                  # unit / integration / e2e
```

## Architecture & Decisions

Design documents and Architecture Decision Records live in `docs/superpowers/`:

- Entry point: [docs/superpowers/specs/voxcraft/README.md](docs/superpowers/specs/voxcraft/README.md)
- ADR index: [docs/superpowers/specs/voxcraft/decisions/](docs/superpowers/specs/voxcraft/decisions/)

> `docs/` is intentionally git-ignored in the upstream repository (internal design corpus). The published code is self-explanatory via source comments; the ADRs are reference-only for maintainers.

## Roadmap

Current release: **v0.4.0** — video translation orchestration ([CHANGELOG](CHANGELOG.md)).

Upcoming (see roadmap):

- **v0.5**: observability polish (Prometheus, structured job audit)
- **v1.0**: stabilization — full test coverage, running-job cancellation propagation

## Contributing

This is a small, opinionated project. Issues and PRs are welcome if they align with the design principles in [01-positioning.md](docs/superpowers/specs/voxcraft/01-positioning.md). Significant architecture changes require a new ADR.

## License

- Source code: [MIT](LICENSE)
- Integrated third-party model weights carry their own terms (notably IndexTTS is non-commercial). Redistribution and commercial use require reviewing the license of each model you ship
- Design documentation under `docs/` is retained locally and not published with the repository
