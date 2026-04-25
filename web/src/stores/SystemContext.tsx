import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

import { getHealth } from "@/api/system";
import { useSse } from "@/hooks/useSse";

export interface SystemState {
  version: string;
  activeProvider: { kind: string; name: string } | null;
  queueSize: number;
  gpu: {
    usedMb: number;
    totalMb: number;
    available: boolean;
    name: string | null;
  };
  sseConnected: boolean;
}

interface SystemContextValue extends SystemState {
  refresh: () => Promise<void>;
}

const INITIAL: SystemState = {
  version: "0.1.0",
  activeProvider: null,
  queueSize: 0,
  gpu: { usedMb: 0, totalMb: 0, available: false, name: null },
  sseConnected: false,
};

const Ctx = createContext<SystemContextValue | null>(null);

export function SystemProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<SystemState>(INITIAL);

  const refresh = useCallback(async () => {
    try {
      const h = await getHealth();
      setState((s) => ({
        ...s,
        gpu: {
          available: h.gpu.available,
          usedMb: h.gpu.used_mb,
          totalMb: h.gpu.total_mb,
          name: h.gpu.name,
        },
      }));
    } catch {
      // ignore；错误已由 axios 拦截器提示
    }
  }, []);

  const onEvent = useCallback((ev: { type: string; payload: any }) => {
    setState((s) => {
      if (ev.type === "model_loaded") {
        return {
          ...s,
          activeProvider: {
            kind: ev.payload.kind,
            name: ev.payload.name,
          },
          sseConnected: true,
        };
      }
      if (ev.type === "model_unloaded") {
        return { ...s, activeProvider: null };
      }
      if (ev.type === "queue_size_changed") {
        return { ...s, queueSize: ev.payload.size ?? 0 };
      }
      if (ev.type === "ping") {
        return { ...s, sseConnected: true };
      }
      return s;
    });
  }, []);

  useSse([], onEvent);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const value = useMemo<SystemContextValue>(
    () => ({ ...state, refresh }),
    [state, refresh]
  );

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useSystem(): SystemContextValue {
  const v = useContext(Ctx);
  if (!v) throw new Error("useSystem must be used within SystemProvider");
  return v;
}
