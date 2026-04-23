#!/usr/bin/env bash
# VoxCraft 本地/服务器开发启动器
#
# 用法：
#   ./scripts/dev.sh                 # 默认：仅后端（服务器场景最常用）
#   ./scripts/dev.sh backend         # 同上，显式写法
#   ./scripts/dev.sh frontend        # 仅前端（Mac 本地开发；Vite 代理后端）
#   ./scripts/dev.sh all             # 同机一体跑：后端 + 前端
#   ./scripts/dev.sh setup           # 只同步后端依赖，不启动
#   ./scripts/dev.sh setup-frontend  # 只同步前端依赖，不启动
#
# 模式化工具链：
#   backend / setup        → 只需 uv（缺失时自动装）
#   frontend / setup-front → 只需 node + pnpm（node 需人工前置）
#   all                    → 同时需要
#
# 远程后端开发（本地前端 + 服务器后端）：
#   VITE_BACKEND_URL=http://<server-ip>:8001 ./scripts/dev.sh frontend

set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO"

MODE="${1:-backend}"

# --- 工具安装函数（按需调用） ----------------------------------------------

ensure_uv() {
    command -v uv >/dev/null 2>&1 && return 0
    echo "📦 uv 未安装，通过官方独立二进制脚本自动安装（不触碰系统 Python）..."
    curl -LsSf https://astral.sh/uv/install.sh | sh >/dev/null 2>&1 || true
    export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
    command -v uv >/dev/null 2>&1 || {
        echo "❌ uv 自动安装失败"
        echo "   手动（独立二进制，推荐）：curl -LsSf https://astral.sh/uv/install.sh | sh"
        echo "   Homebrew：brew install uv"
        echo "   （不建议 pip install uv —— 会占用 Python 环境）"
        exit 1
    }
    echo "✅ uv $(uv --version)"
}

ensure_node() {
    command -v node >/dev/null 2>&1 || {
        echo "❌ 缺少 Node.js（建议 22+）"
        echo "   macOS ：brew install node"
        echo "   Linux ：nvm install 22 / 包管理器"
        echo "   官方  ：https://nodejs.org/"
        exit 1
    }
}

ensure_pnpm() {
    command -v pnpm >/dev/null 2>&1 && return 0
    echo "📦 pnpm 未安装，通过 corepack 自动激活..."
    if command -v corepack >/dev/null 2>&1; then
        corepack enable >/dev/null 2>&1 || true
        corepack prepare pnpm@latest --activate >/dev/null 2>&1 || true
    fi
    if ! command -v pnpm >/dev/null 2>&1 && command -v npm >/dev/null 2>&1; then
        echo "↩️  回退到 npm install -g pnpm"
        npm install -g pnpm >/dev/null 2>&1 || true
    fi
    command -v pnpm >/dev/null 2>&1 || {
        echo "❌ pnpm 自动激活失败"
        echo "   手动：corepack enable && corepack prepare pnpm@latest --activate"
        exit 1
    }
    echo "✅ pnpm $(pnpm --version)"
}

# --- 依赖同步 ---------------------------------------------------------------

sync_backend() {
    ensure_uv
    # uv sync 默认在项目根创建 ./.venv/，所有依赖都装到此虚拟环境；
    # uv 还会自动下载独立 Python（若系统缺 3.13）到 ~/.local/share/uv/python/，
    # 同样不会污染系统 Python。
    if [ ! -d .venv ] \
       || [ pyproject.toml -nt .venv ] \
       || [ uv.lock -nt .venv ]; then
        echo "📦 同步 Python 依赖到项目虚拟环境 ./.venv/ （隔离，不污染系统）..."
        uv sync --all-extras
        echo "   venv 路径: $PWD/.venv"
        echo "   Python   : $(./.venv/bin/python --version 2>/dev/null || echo '待创建')"
    fi
}

sync_frontend() {
    ensure_node
    ensure_pnpm
    if [ ! -d web/node_modules ] \
       || [ web/package.json -nt web/node_modules ] \
       || [ web/pnpm-lock.yaml -nt web/node_modules ]; then
        echo "📦 同步前端依赖..."
        (cd web && pnpm install)
    fi
}

# --- 运行前准备 -------------------------------------------------------------

load_env() {
    mkdir -p data models
    if [ -f .env ]; then
        # shellcheck disable=SC1091
        set -a && source .env && set +a
    fi
}

# --- 启动 -------------------------------------------------------------------

start_backend() {
    echo "🚀 后端 http://0.0.0.0:${VOXCRAFT_PORT:-8001}  (uvicorn --reload)"
    exec uv run uvicorn voxcraft.main:app \
        --reload \
        --host 0.0.0.0 \
        --port "${VOXCRAFT_PORT:-8001}"
}

start_frontend() {
    local proxy_target="${VITE_BACKEND_URL:-http://localhost:8001}"
    echo "🚀 前端 http://localhost:5173  (API 代理 → ${proxy_target})"
    exec bash -c "cd web && VITE_BACKEND_URL='${proxy_target}' pnpm dev"
}

case "$MODE" in
    setup)
        sync_backend
        echo "✅ 后端依赖就绪"
        ;;
    setup-frontend)
        sync_frontend
        echo "✅ 前端依赖就绪"
        ;;
    backend)
        sync_backend
        load_env
        start_backend
        ;;
    frontend)
        sync_frontend
        start_frontend
        ;;
    all)
        sync_backend
        sync_frontend
        load_env
        (cd web && VITE_BACKEND_URL="${VITE_BACKEND_URL:-http://localhost:${VOXCRAFT_PORT:-8001}}" pnpm dev) &
        WEB_PID=$!
        trap 'kill $WEB_PID 2>/dev/null || true' EXIT INT TERM
        echo "🚀 后端 http://localhost:${VOXCRAFT_PORT:-8001}"
        echo "🚀 前端 http://localhost:5173"
        echo "   Ctrl+C 停止两者"
        start_backend
        ;;
    *)
        echo "用法: $0 [backend|frontend|all|setup|setup-frontend]" >&2
        exit 1
        ;;
esac
