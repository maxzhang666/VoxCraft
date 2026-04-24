# syntax=docker/dockerfile:1.7
# VoxCraft 三阶段构建
# - Stage 1 (web-build): Node 22 构建前端
# - Stage 2 (py-build):  Python slim + uv + 安装 Python 依赖（uv cache 仅存于此阶段）
# - Stage 3 (runtime):   Python slim + .venv + 静态资源；由 nvidia-container-toolkit 挂载宿主 driver
#
# 不用 nvidia/cuda:runtime 基础镜像的原因：
# - torch 2.6 wheel 自带 CUDA 12.4 runtime libs（cublas/cudnn/nccl/... 均来自 nvidia-*-cu12 wheel）
# - libcuda.so (driver) 由 nvidia-container-toolkit 从宿主机映射进来
# - 基础镜像的 CUDA runtime libs ~2GB 是冗余的，换 python:slim 净省约 1.5GB
# - CTranslate2 (faster-whisper) 同样自带 CUDA libs，无需系统 CUDA

# -------- Stage 1: Web build --------
FROM node:22-alpine AS web-build

WORKDIR /web
RUN corepack enable

COPY web/package.json web/pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile

COPY web/ ./
RUN pnpm build

# -------- Stage 2: Python build --------
FROM python:3.13-slim-bookworm AS py-build

ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1

COPY --from=ghcr.io/astral-sh/uv:0.5 /uv /uvx /usr/local/bin/

WORKDIR /app

# 优先复制锁文件 + pyproject，利用 layer 缓存
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project

# 再复制源码
COPY src ./src
COPY alembic.ini ./
COPY migrations ./migrations
RUN uv sync --frozen --no-dev

# -------- Stage 3: Runtime --------
FROM python:3.13-slim-bookworm AS runtime

# NVIDIA 驱动能力声明：
# - VISIBLE_DEVICES=all：接受 nvidia-container-toolkit 下发的全部 GPU
# - DRIVER_CAPABILITIES=compute,utility：torch / CTranslate2 仅需 compute；保留 utility 供 nvidia-smi
# compose / k8s 的 capabilities 配置会覆盖这两项，此处提供独立 docker run 场景的默认值
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/app/.venv/bin:$PATH" \
    NVIDIA_VISIBLE_DEVICES=all \
    NVIDIA_DRIVER_CAPABILITIES=compute,utility

RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      ca-certificates curl ffmpeg libsndfile1 fonts-noto-cjk \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# py-build 与 runtime 共用 python:3.13-slim-bookworm，venv shebang 的 /usr/local/bin/python3.13 在两阶段一致
COPY --from=py-build /app /app
COPY --from=web-build /web/dist ./static

EXPOSE 8001

CMD ["uvicorn", "voxcraft.main:app", "--host", "0.0.0.0", "--port", "8001"]
