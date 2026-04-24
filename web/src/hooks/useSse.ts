import { useEffect } from "react";
import type { SseEvent } from "@/types/api";

const SSE_URL = "/api/admin/events";

type Handler = (ev: SseEvent) => void;

let singleton: EventSource | null = null;
let refCount = 0;
const listeners = new Map<string, Set<Handler>>();
const wildcard: Set<Handler> = new Set();

function ensureSingleton(): EventSource {
  if (singleton) return singleton;
  const es = new EventSource(SSE_URL);
  es.onmessage = (e) => {
    try {
      const ev: SseEvent = JSON.parse(e.data);
      listeners.get(ev.type)?.forEach((fn) => fn(ev));
      wildcard.forEach((fn) => fn(ev));
    } catch {
      // ignore malformed payload
    }
  };
  es.onerror = () => {
    // 浏览器会自动重连；失败多次后可在 UI 标注"已断线"（留到 SystemContext）
  };
  singleton = es;
  return es;
}

function cleanup(): void {
  if (refCount <= 0 && singleton) {
    singleton.close();
    singleton = null;
    refCount = 0;
    listeners.clear();
    wildcard.clear();
  }
}

/**
 * 订阅 SSE 事件。
 * @param types 关心的事件类型数组；空数组 = 全类型通配。
 */
export function useSse(types: string[], handler: Handler): void {
  useEffect(() => {
    ensureSingleton();
    refCount += 1;

    if (types.length === 0) {
      wildcard.add(handler);
    } else {
      for (const t of types) {
        if (!listeners.has(t)) listeners.set(t, new Set());
        listeners.get(t)!.add(handler);
      }
    }

    return () => {
      if (types.length === 0) {
        wildcard.delete(handler);
      } else {
        for (const t of types) {
          listeners.get(t)?.delete(handler);
        }
      }
      refCount -= 1;
      cleanup();
    };
    // 故意不把 types/handler 放入依赖：handler 应由调用方以 useCallback 稳定引用
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
}
