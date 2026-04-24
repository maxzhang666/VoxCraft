import { createBrowserRouter, Navigate } from "react-router-dom";

// Vite 把 base 注入到 import.meta.env.BASE_URL：dev="/", prod="/ui/"；
// Router basename 不带末尾斜杠。
const BASENAME = import.meta.env.BASE_URL.replace(/\/$/, "") || "/";

import { MainLayout } from "@/layouts/MainLayout";
import { SettingsLayout } from "@/layouts/SettingsLayout";
import { AsrPage } from "@/pages/asr/AsrPage";
import { CloningPage } from "@/pages/cloning/CloningPage";
import { Dashboard } from "@/pages/Dashboard";
import { SeparatorPage } from "@/pages/separator/SeparatorPage";
import { TtsPage } from "@/pages/tts/TtsPage";
import { VideoTranslatePage } from "@/pages/video-translate/VideoTranslatePage";
import { GlobalJobsQueue } from "@/pages/settings/GlobalJobsQueue";
import { LlmConfig } from "@/pages/settings/LlmConfig";
import { ModelsLibrary } from "@/pages/settings/ModelsLibrary";
import { ModelsManage } from "@/pages/settings/ModelsManage";
import { SystemDiagnosis } from "@/pages/settings/SystemDiagnosis";

export const router = createBrowserRouter(
  [
    {
      path: "/",
      element: <MainLayout />,
      children: [
        { index: true, element: <Dashboard /> },
        { path: "asr", element: <AsrPage /> },
        { path: "tts", element: <TtsPage /> },
        { path: "cloning", element: <CloningPage /> },
        { path: "separator", element: <SeparatorPage /> },
        { path: "video-translate", element: <VideoTranslatePage /> },
        {
          path: "settings",
          element: <SettingsLayout />,
          children: [
            { index: true, element: <Navigate to="models" replace /> },
            { path: "models", element: <ModelsManage /> },
            { path: "models-library", element: <ModelsLibrary /> },
            { path: "llm", element: <LlmConfig /> },
            { path: "system", element: <SystemDiagnosis /> },
            { path: "jobs", element: <GlobalJobsQueue /> },
          ],
        },
      ],
    },
  ],
  { basename: BASENAME },
);
