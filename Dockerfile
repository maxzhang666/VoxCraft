# syntax=docker/dockerfile:1.7
# VoxCraft App Image：FROM voxcraft-base + 前端构建产物 + 项目源码。
# 整体 ~50MB（base 已含 .venv + GPT-SoVITS 全部 deps，本镜像只是薄壳）。
# 大头镜像只在 pyproject/uv.lock/Dockerfile.base 改动时由 docker-build-base 流水线
# 重建——日常 src commit 客户端只拉这层 ~50MB 增量。

# Global ARG：必须放在所有 FROM 之前才能被后续 `FROM ${BASE_IMAGE}` 引用，
# 中间位置（两个 FROM 之间）的 ARG 既不是 global 也不在 stage 内，
# default 与 --build-arg 都不会被应用，导致 "base name should not be blank"。
ARG BASE_IMAGE=ghcr.io/maxzhang666/voxcraft-base:latest

# -------- Stage 1: Web build --------
FROM node:22-alpine AS web-build

WORKDIR /web
RUN corepack enable

COPY web/package.json web/pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile

COPY web/ ./
RUN pnpm build

# -------- Stage 2: Compose on top of base --------
FROM ${BASE_IMAGE}

WORKDIR /app

# src 是高频改动，单独 layer；migrations / alembic.ini 几乎不动，跟 src 同层即可
COPY src ./src
COPY alembic.ini ./
COPY migrations ./migrations
COPY --from=web-build /web/dist ./static

EXPOSE 8001

CMD ["uvicorn", "voxcraft.main:app", "--host", "0.0.0.0", "--port", "8001"]
