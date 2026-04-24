import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "node:path";

// 支持本地前端 + 远程后端：export VITE_BACKEND_URL=http://server-ip:8001
const BACKEND = process.env.VITE_BACKEND_URL || "http://localhost:8001";

// 后端业务 API 统一 /api 前缀，不与前端 SPA 路由（/asr /tts 等）冲突。
// /v1/* 是 OpenAI 兼容层规范路径，独立代理。
//
// base 策略：
//   build（生产）→ "/ui/"，产物里的 <link>/<script> 引用 /ui/assets/...，
//                  与 FastAPI `app.mount("/ui", StaticFiles(...))` 对齐
//   serve（dev）  → "/"，localhost:5173 根路径直接访问不加前缀
// Router 通过 import.meta.env.BASE_URL 取用相同 base 做 basename。
export default defineConfig(({ command }) => ({
  base: command === "build" ? "/ui/" : "/",
  plugins: [react()],
  resolve: {
    alias: { "@": path.resolve(__dirname, "src") },
  },
  server: {
    port: 5173,
    proxy: {
      "/api": BACKEND,
      "/v1": BACKEND,
    },
  },
  build: {
    outDir: "dist",
    sourcemap: true,
    // 不手动 manualChunks：之前的 semi / react-vendor / vendor 三分策略
    // 把 Semi 依赖的 react-is / prop-types 等生态包错分到 vendor，
    // 触发跨 chunk 初始化顺序问题（React.PureComponent undefined）。
    // Rollup 自动按依赖图分包最稳，代价仅是首屏体积略增 —— 与正确性相比可接受。
    chunkSizeWarningLimit: 1200,
  },
}));
