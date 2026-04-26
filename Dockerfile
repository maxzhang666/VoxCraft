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
FROM python:3.11-slim-bookworm AS py-build

# UV_COMPILE_BYTECODE=0：不让 uv 预编译 .pyc。原因：.pyc 头部嵌入 source mtime，
# 而 source 的 mtime 来自 docker COPY 时的 host 时间——每次构建都不同，
# 即使 pyproject/uv.lock 字节级未变，.venv 字节也不稳定 → COPY .venv 输出的
# layer blob hash 每次新 → client 强制重下 ~3.2GB。Python 容器首次 import
# 会 lazy 编译 .py → __pycache__，对长驻 uvicorn 进程仅冷启动多 1-2s。
ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=0

# voxcpm 引入的部分 transitive deps（umap-learn / wetext 等）在 linux+py3.11 上
# 可能没有预编 wheel，需要 sdist 源码编译；slim base 默认无 gcc 会让 uv sync 退出 1。
# git：用于 git clone GPT-SoVITS 源码到 /opt（GPT-SoVITS 是 import-from-tree
# 风格，不发 PyPI 包；Python 依赖通过 pyproject 装到 .venv，仓库本身放 /opt 由
# runtime 阶段 PYTHONPATH 注入）。
# 装 build-essential + python3-dev + git 覆盖以上需求；仅 py-build 中间层，
# 不影响 runtime image 大小。
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      build-essential python3-dev git \
 && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.5 /uv /uvx /usr/local/bin/

WORKDIR /app

# 只装第三方依赖，**不**装项目本身。让 .venv 内容只受 pyproject/uv.lock 影响：
# pyproject/uv.lock 不变，.venv 字节级稳定 → runtime 阶段 COPY .venv 那层 hash 不变 →
# 客户端 docker pull 命中缓存层，不重下 ~3.2GB。
# 项目代码靠 runtime 阶段的 PYTHONPATH=/app/src 加载，无需写入 site-packages。
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project

# GPT-SoVITS：仓库无 PyPI 包，但它 import GPT_SoVITS.* 是裸目录形式
# （非 setup.py install），所以 git clone 到 /opt + runtime PYTHONPATH 注入即可。
# 钉到 main HEAD commit hash 避免漂移；shallow clone (depth=1) 节省镜像层。
# Python 依赖（funasr/pytorch-lightning/onnxruntime-gpu/...）已由上面 uv sync 装入 .venv。
ARG GPT_SOVITS_COMMIT=ea2d2a81667239d37615697e8f0056e35bab2db6
RUN git clone --depth 1 https://github.com/RVC-Boss/GPT-SoVITS.git /opt/GPT-SoVITS \
 && cd /opt/GPT-SoVITS \
 && git fetch --depth 1 origin "$GPT_SOVITS_COMMIT" \
 && git checkout "$GPT_SOVITS_COMMIT" \
 && rm -rf .git

# 源码 + 配置仅复制不安装
COPY src ./src
COPY alembic.ini ./
COPY migrations ./migrations

# -------- Stage 3: Runtime --------
FROM python:3.11-slim-bookworm AS runtime

# NVIDIA 驱动能力声明：
# - VISIBLE_DEVICES=all：接受 nvidia-container-toolkit 下发的全部 GPU
# - DRIVER_CAPABILITIES=compute,utility：torch / CTranslate2 仅需 compute；保留 utility 供 nvidia-smi
# compose / k8s 的 capabilities 配置会覆盖这两项，此处提供独立 docker run 场景的默认值
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/app/.venv/bin:$PATH" \
    PYTHONPATH=/app/src:/opt/GPT-SoVITS \
    NVIDIA_VISIBLE_DEVICES=all \
    NVIDIA_DRIVER_CAPABILITIES=compute,utility

RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      ca-certificates curl ffmpeg libsndfile1 fonts-noto-cjk \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 拆分 COPY 让 .venv（大头不变）和 src（小头常变）各成一层：
# - .venv 层 ~3.2GB：仅当 pyproject/uv.lock 变化时失效，日常代码提交 client pull 命中缓存
# - src / migrations / alembic.ini 层：每次代码改动重做，但只有 ~10MB
# - static 层独立：前端改动也不波及 Python 层
# py-build 与 runtime 共用 python:3.11-slim-bookworm，venv shebang 的 /usr/local/bin/python3.11 在两阶段一致
COPY --from=py-build /app/.venv /app/.venv
COPY --from=py-build /app/src /app/src
COPY --from=py-build /app/migrations /app/migrations
COPY --from=py-build /app/alembic.ini /app/alembic.ini
# GPT-SoVITS 仓库仅含 Python 源码（无大模型权重），约 10-20MB；
# 单独一层方便 commit 升级时增量拉
COPY --from=py-build /opt/GPT-SoVITS /opt/GPT-SoVITS
COPY --from=web-build /web/dist ./static

# 故意放在 COPY 之后：调整 runtime ENV（如 TORCHDYNAMO_DISABLE）不应让 .venv 层
# cache 失效。.venv 层一旦失效客户端要重下 ~3.2GB；ENV 改动放末尾让前置层
# 字节级稳定。新加 ENV 一律在此处追加。
# - TORCHDYNAMO_DISABLE=1: voxcpm 内部 torch.compile 在 dynamo trace einops 0.8.2
#   的 unbound builtin 调用时挂；进程级 kill switch 让 dynamo 全程不 trace
ENV TORCHDYNAMO_DISABLE=1

EXPOSE 8001

CMD ["uvicorn", "voxcraft.main:app", "--host", "0.0.0.0", "--port", "8001"]
