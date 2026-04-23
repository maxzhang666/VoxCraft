import axios, { AxiosError } from "axios";
import { Toast } from "@douyinfe/semi-ui";
import type { ErrorResponse } from "@/types/api";

export const api = axios.create({
  baseURL: "",
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
