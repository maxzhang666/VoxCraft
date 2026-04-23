import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "node:path";

// 支持本地前端 + 远程后端：export VITE_BACKEND_URL=http://server-ip:8001
const BACKEND = process.env.VITE_BACKEND_URL || "http://localhost:8001";

// /asr /tts 等路径既是前端路由也是后端端点；浏览器刷新（Accept: text/html）
// 应由 SPA 接管，API 调用（Accept: application/json 等）才转给后端。
const apiOrSpa = {
  target: BACKEND,
  changeOrigin: true,
  bypass(req: { method?: string; headers: { accept?: string } }) {
    if (req.method === "GET" && req.headers.accept?.includes("text/html")) {
      return "/index.html";
    }
  },
};

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: { "@": path.resolve(__dirname, "src") },
  },
  server: {
    port: 5173,
    proxy: {
      "/asr": apiOrSpa,
      "/tts": apiOrSpa,
      "/separate": apiOrSpa,
      "/jobs": BACKEND,
      "/admin": BACKEND,
      "/health": BACKEND,
      "/models": BACKEND,
    },
  },
  build: {
    outDir: "dist",
    sourcemap: true,
  },
});
