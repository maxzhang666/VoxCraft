# syntax=docker/dockerfile:1.7
# VoxCraft 两阶段构建（cloning 已下线，py-build 不再必要）
# - Stage 1 (web-build): Node 22 构建前端
# - Stage 2 (runtime):   Python slim 直接装依赖；分三层让 torch ~3GB 独立成一个
#                         跨 build 稳定的 layer，业务代码改动只产生 ~15MB 新 layer
#
# 单 image 架构 + reproducibility 三层措施（SOURCE_DATE_EPOCH build-arg +
# Dockerfile mtime touch + workflow outputs rewrite-timestamp=true）让 layer
# blob 跨 build 字节稳定，CI cache 与 client docker pull 都能精准命中。
#
# 镜像分层（从底到上、跨 build 稳定度从高到低）：
#   ① python:3.11-slim-bookworm + apt deps (ffmpeg/libsndfile/CJK 字体) ≈ 350MB
#   ② torch + torchaudio + nvidia-cu12-* + triton                       ≈ 3GB
#   ③ 项目其余 Python 依赖（fastapi / faster-whisper / piper / demucs / ...）≈ 150MB
#   ④ 项目源码 + migrations + 静态前端                                   ≈ 15MB
#
# 客户端 docker pull 增量逻辑：
# - 第一次：3.5GB 全下
# - 仅业务代码改动：只下层 ④ ~15MB
# - 改 pyproject（不动 torch）：下层 ③+④ ~150MB
# - 升 torch（罕见）：下层 ②+③+④ 全重下

# -------- Stage 1: Web build --------
FROM node:22-alpine AS web-build

WORKDIR /web
RUN corepack enable

COPY web/package.json web/pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile

COPY web/ ./
RUN pnpm build


# -------- Stage 2: Runtime --------
FROM python:3.11-slim-bookworm AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/app/.venv/bin:$PATH" \
    PYTHONPATH=/app/src \
    NVIDIA_VISIBLE_DEVICES=all \
    NVIDIA_DRIVER_CAPABILITIES=compute,utility \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=0

# UV_COMPILE_BYTECODE=0：不让 uv 预编译 .pyc。原因：.pyc 头部嵌入 source mtime，
# 而 source mtime 来自 docker COPY 时刻——每次构建都不同，让 .venv 字节漂移。
# 容器首次 import 时 Python 会 lazy 编译 .py → __pycache__，长驻 uvicorn 仅
# 冷启动多 1-2s。

RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      ca-certificates curl ffmpeg libsndfile1 fonts-noto-cjk \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# === Layer ②：torch + CUDA runtime（~3GB，跨 build 稳定）===
# uv 用 bind mount 形式注入，install 完后 uv 二进制不留在镜像里。
# torch 版本通过 ARG 锁——pyproject 与本行必须保持一致；pyproject 升 torch 时
# 同步改这里，否则 layer ③ 的 uv sync 会把新 torch 整套重装到 ③ 里，layer ②
# 就白做了。当前与 uv.lock 一致：torch 2.6.0 / torchaudio 2.6.0。
ARG TORCH_VERSION=2.6.0
ARG TORCHAUDIO_VERSION=2.6.0
RUN --mount=type=cache,target=/root/.cache/uv,id=uv-cache \
    --mount=type=bind,from=ghcr.io/astral-sh/uv:0.5,source=/uv,target=/usr/local/bin/uv \
    uv venv /app/.venv \
 && uv pip install --python /app/.venv/bin/python \
      "torch==${TORCH_VERSION}" "torchaudio==${TORCHAUDIO_VERSION}" \
 && find /app/.venv \( -type f -o -type d \) -exec touch -h -d @0 {} +

# === Layer ③：项目其余 Python 依赖（~150MB）===
# uv sync --frozen 会照 lockfile 校验已装 torch 的版本，匹配则跳过；只把 fastapi
# / pydantic / faster-whisper / piper / demucs 等装进 .venv。任何 pyproject /
# uv.lock 改动都让这一层失效但不波及 layer ②。
COPY pyproject.toml uv.lock README.md ./
RUN --mount=type=cache,target=/root/.cache/uv,id=uv-cache \
    --mount=type=bind,from=ghcr.io/astral-sh/uv:0.5,source=/uv,target=/usr/local/bin/uv \
    uv sync --frozen --no-dev --no-install-project \
 && find /app/.venv \( -type f -o -type d \) -exec touch -h -d @0 {} +
# Reproducible .venv：uv sync 在 wheel install 时写 *.dist-info/INSTALLER 等
# metadata，mtime 是 build 时刻。touch 到 epoch 0 让 mtime 稳定，配合
# workflow 的 SOURCE_DATE_EPOCH=1 + outputs rewrite-timestamp=true，layer
# blob 跨 build 字节级 reproducible。

# === Layer ④：源码 + 迁移 + 静态前端（~15MB，每次代码改动重做）===
COPY src ./src
COPY alembic.ini ./
COPY migrations ./migrations
COPY --from=web-build /web/dist ./static

EXPOSE 8001

CMD ["uvicorn", "voxcraft.main:app", "--host", "0.0.0.0", "--port", "8001"]
