import { api } from "./client";

export interface ProxySettings {
  hf_endpoint: string;
  https_proxy: string;
  http_proxy: string;
  no_proxy: string;
}

export const getProxy = () =>
  api.get<ProxySettings>("/admin/settings/proxy").then((r) => r.data);

export const updateProxy = (payload: ProxySettings) =>
  api.put<ProxySettings>("/admin/settings/proxy", payload).then((r) => r.data);
