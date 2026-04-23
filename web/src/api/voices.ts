import { api } from "./client";
import type { Voice } from "@/types/api";

export const listVoices = () =>
  api.get<{ voices: Voice[] }>("/tts/voices").then((r) => r.data.voices);
