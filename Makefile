.PHONY: setup setup-frontend dev dev-frontend dev-all test test-e2e build up down clean

# 只同步后端依赖（服务器场景）
setup:
	./scripts/dev.sh setup

# 只同步前端依赖（本地场景）
setup-frontend:
	./scripts/dev.sh setup-frontend

# 默认：仅后端（服务器场景最常用）
dev:
	./scripts/dev.sh backend

# 仅前端（Mac 本地开发；Vite 代理到后端）
# 远程后端： VITE_BACKEND_URL=http://<server>:8001 make dev-frontend
dev-frontend:
	./scripts/dev.sh frontend

# 同机一体跑：后端 + 前端
dev-all:
	./scripts/dev.sh all

# 全部测试（跳过 slow 真模型）
test:
	uv run pytest -v -m "not slow"

# 含真模型的 E2E 测试
test-e2e:
	uv run pytest -v -m slow

# Docker 构建
build:
	docker compose build

# Docker 一键启动
up:
	docker compose up -d

down:
	docker compose down

# 清理临时产物
clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
