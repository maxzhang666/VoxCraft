# syntax=docker/dockerfile:1.7
# VoxCraft 三阶段构建（单 image 架构）
# - Stage 1 (web-build): Node 22 构建前端
# - Stage 2 (py-build):  Python slim + uv + 装 Python 依赖 + git clone GPT-SoVITS
# - Stage 3 (runtime):   Python slim + .venv + 静态资源 + 项目源码
#
# 单 image 架构 + reproducibility 三层措施（SOURCE_DATE_EPOCH build-arg +
# Dockerfile mtime touch + workflow outputs rewrite-timestamp=true）让 layer
# blob 跨 build 字节稳定。pyproject/uv.lock 不变时：
# - CI 全 cache 命中 ~3 min
# - client docker pull 全 layer Already exists，0 字节下载

# -------- Stage 1: Web build --------
FROM node:22-alpine AS web-build

WORKDIR /web
RUN corepack enable

COPY web/package.json web/pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile

COPY web/ ./
RUN pnpm build

# -------- Stage 2: Python build --------
FROM python:3.11-slim-bookworm AS py-build

# UV_COMPILE_BYTECODE=0：不让 uv 预编译 .pyc。原因：.pyc 头部嵌入 source mtime，
# 而 source mtime 来自 docker COPY 时刻——每次构建都不同，让 .venv 字节漂移。
# 容器首次 import 时 Python 会 lazy 编译 .py → __pycache__，长驻 uvicorn 仅
# 冷启动多 1-2s。
ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=0

# build-essential + python3-dev：voxcpm/GPT-SoVITS 部分 transitive deps 在
# linux+py3.11 上没有预编 wheel 需要 sdist 编译。
# git：用于 git clone GPT-SoVITS 源码到 /opt（import-from-tree 风格，不发 PyPI）。
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      build-essential python3-dev git \
 && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.5 /uv /uvx /usr/local/bin/

WORKDIR /app

# uv wheel cache 走 BuildKit cache mount 持久化：layer cache miss 也能跨 build
# 复用 wheel，不再从 PyPI 重下 ~4GB。
COPY pyproject.toml uv.lock README.md ./
RUN --mount=type=cache,target=/root/.cache/uv,id=uv-cache \
    uv sync --frozen --no-dev --no-install-project \
 && find /app/.venv \( -type f -o -type d \) -exec touch -h -d @0 {} +
# Reproducible .venv：uv sync 在 wheel install 时写 *.dist-info/INSTALLER 等
# metadata，mtime 是 build 时刻。touch 到 epoch 0 让 mtime 稳定，配合
# workflow 的 SOURCE_DATE_EPOCH=1 + outputs rewrite-timestamp=true，layer
# blob 跨 build 字节级 reproducible。

# GPT-SoVITS：仓库无 PyPI 包，git clone 到 /opt + runtime PYTHONPATH 注入。
# rm -rf .git 清 git 元数据；rm -rf GPT_SoVITS/pretrained_models 清掉
# .gitignore 占位文件，让 runtime Provider 能 symlink 该路径到 user model_dir。
ARG GPT_SOVITS_COMMIT=ea2d2a81667239d37615697e8f0056e35bab2db6
RUN git clone --depth 1 https://github.com/RVC-Boss/GPT-SoVITS.git /opt/GPT-SoVITS \
 && cd /opt/GPT-SoVITS \
 && git fetch --depth 1 origin "$GPT_SOVITS_COMMIT" \
 && git checkout "$GPT_SOVITS_COMMIT" \
 && rm -rf .git GPT_SoVITS/pretrained_models \
 && find /opt/GPT-SoVITS \( -type f -o -type d \) -exec touch -h -d @0 {} +

# 源码 + 配置仅复制不安装；项目代码靠 runtime PYTHONPATH=/app/src 加载
COPY src ./src
COPY alembic.ini ./
COPY migrations ./migrations

# -------- Stage 3: Runtime --------
FROM python:3.11-slim-bookworm AS runtime

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

# 拆分 COPY 让 .venv 与 src 各成 layer：.venv 仅 pyproject/uv.lock 改动时变，
# src 每次代码改动重做（仅 ~10MB）。py-build 与 runtime 共用 python:3.11-slim，
# venv shebang /usr/local/bin/python3.11 在两阶段一致。
COPY --from=py-build /app/.venv /app/.venv
COPY --from=py-build /app/src /app/src
COPY --from=py-build /app/migrations /app/migrations
COPY --from=py-build /app/alembic.ini /app/alembic.ini
COPY --from=py-build /opt/GPT-SoVITS /opt/GPT-SoVITS
COPY --from=web-build /web/dist ./static

# Runtime ENV 一律放 COPY 之后：调整 ENV（PYTHONPATH / TORCHDYNAMO_DISABLE）
# 不应让 .venv layer cache 失效。新加 ENV 一律在此追加。
# - PYTHONPATH: /app/src 项目代码 + /opt/GPT-SoVITS 仓库根（默认 cwd）
#   + /opt/GPT-SoVITS/GPT_SoVITS（GPT-SoVITS 用扁平 import：from AR.* /
#   from module.* / from TTS_infer_pack.* import ...，需要这层在 sys.path）
# - TORCHDYNAMO_DISABLE=1: voxcpm 内部 torch.compile 在 dynamo trace einops 0.8.2
#   的 unbound builtin 调用时挂；进程级 kill switch 让 dynamo 全程不 trace
ENV PYTHONPATH=/app/src:/opt/GPT-SoVITS:/opt/GPT-SoVITS/GPT_SoVITS \
    TORCHDYNAMO_DISABLE=1

EXPOSE 8001

CMD ["uvicorn", "voxcraft.main:app", "--host", "0.0.0.0", "--port", "8001"]
