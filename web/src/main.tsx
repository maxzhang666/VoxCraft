import React from "react";
import ReactDOM from "react-dom/client";
import { RouterProvider } from "react-router-dom";
import { LocaleProvider } from "@douyinfe/semi-ui";
import zhCN from "@douyinfe/semi-ui/lib/es/locale/source/zh_CN";

import { router } from "@/routes";
import { SystemProvider } from "@/stores/SystemContext";
import "@/styles/global.scss";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <LocaleProvider locale={zhCN}>
      <SystemProvider>
        <RouterProvider router={router} />
      </SystemProvider>
    </LocaleProvider>
  </React.StrictMode>
);
