import axios, { AxiosError } from "axios";
import { Toast } from "@douyinfe/semi-ui";
import type { ErrorResponse } from "@/types/api";

// 所有业务 API 统一 /api 前缀；OpenAI 兼容层 /v1/* 独立，不过这个 client。
export const api = axios.create({
  baseURL: "/api",
  timeout: 60000,
});

api.interceptors.response.use(
  (r) => r,
  (err: AxiosError<ErrorResponse>) => {
    const code = err.response?.data?.error?.code ?? "NETWORK_ERROR";
    const message = err.response?.data?.error?.message ?? err.message;
    Toast.error({ content: `[${code}] ${message}`, duration: 4 });
    return Promise.reject(err);
  }
);
