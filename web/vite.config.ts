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
    // Semi UI 整包 ~885kB 为第三方库固有体积（已独立 chunk，缓存命中率高），
    // 按需引入属大规模重构超出当前范围——调大 warning 阈值消除无效告警。
    chunkSizeWarningLimit: 1000,
    // 拆包：Semi UI / React 生态 / 其他第三方分别独立 chunk
    // 原因：单 chunk 1.4MB 导致首屏加载慢；拆后可并发下载 + 缓存命中率高
    //
    // Semi UI 按需引入未做：`@douyinfe/semi-ui` 的 index.js 入口 re-export
    // 所有组件，Rollup 自动 tree-shake 无效（尝试 moduleSideEffects=false 无改善）。
    // 真正减小需要将全部 import 改为深路径形式：
    //   - import { Button } from "@douyinfe/semi-ui/lib/es/button";
    //   - import "@douyinfe/semi-ui/lib/es/button/button.css";
    // 约 20-30 处改动 + 每处配套 CSS import，属较大重构。留给 v0.3+。
    // 当前 Semi 独立 chunk 886KB (gzip 238KB) 通过浏览器缓存摊销可接受。
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (!id.includes("node_modules")) return;
          if (id.includes("@douyinfe/")) return "semi";
          if (
            id.includes("/react/") ||
            id.includes("/react-dom/") ||
            id.includes("/react-router") ||
            id.includes("/scheduler/")
          ) {
            return "react-vendor";
          }
          return "vendor";
        },
      },
    },
  },
}));
