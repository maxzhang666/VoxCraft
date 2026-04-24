# syntax=docker/dockerfile:1.7
# VoxCraft 多阶段构建（ADR-005 / ADR-007）
# - Stage 1: Node 22 构建前端（web/dist）
# - Stage 2: CUDA 12.1 + Python 3.13 运行时 + 静态资源

# -------- Stage 1: Web build --------
FROM node:22-alpine AS web-build

WORKDIR /web
RUN corepack enable

COPY web/package.json web/pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile

COPY web/ ./
RUN pnpm build

# -------- Stage 2: Python runtime --------
FROM nvidia/cuda:12.1.1-runtime-ubuntu22.04 AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_INSTALL_DIR=/opt/uv-python \
    PATH="/app/.venv/bin:$PATH"

RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      ca-certificates curl ffmpeg libsndfile1 fonts-noto-cjk \
 && rm -rf /var/lib/apt/lists/*

# uv 作为 Python 安装器 + 依赖管理器
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

# 前端静态资源
COPY --from=web-build /web/dist ./static

EXPOSE 8001

CMD ["uvicorn", "voxcraft.main:app", "--host", "0.0.0.0", "--port", "8001"]
