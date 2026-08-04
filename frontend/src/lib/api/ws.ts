/**
 * WebSocket client for ATLAS live streams.
 *
 * Connects to /ws/ticks and /ws/terminal-events with the JWT appended as
 * ?token= (WS cannot set headers). Auto-reconnects with exponential backoff.
 */

import { useEffect, useRef, useState } from "react";

import { getAccessToken, WS_URL } from "./client";
import { syncAccount } from "./endpoints";
import type { AccountState, TickStream } from "./types";

type WSKind = "ticks" | "terminal-events" | "account";

function buildUrl(kind: WSKind): string | null {
  const token = getAccessToken();
  if (!token) return null;
  // If WS_URL is unset/empty, resolve a same-origin ws(s) URL against the page.
  let base = WS_URL;
  if (!base && typeof window !== "undefined") {
    const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
    base = `${proto}//${window.location.host}`;
  }
  return `${base}/ws/${kind}?token=${encodeURIComponent(token)}`;
}

interface WSManager {
  ws: WebSocket | null;
  open: boolean;
}

const managers: Partial<Record<WSKind, WSManager>> = {};
const subscribers: Partial<Record<WSKind, Set<(msg: Record<string, unknown>) => void>>> = {};

function ensure(kind: WSKind): WSManager {
  let mgr: WSManager = managers[kind] ?? { ws: null, open: false };
  if (mgr.open) return mgr;

  const url = buildUrl(kind);
  if (!url) return managers[kind] ?? { ws: null, open: false };

  if (!subscribers[kind]) subscribers[kind] = new Set();
  if (mgr.ws) {
    try {
      mgr.ws.close();
    } catch {
      /* noop */
    }
  }

  let attempt = 0;
  const connect = () => {
    const ws = new WebSocket(buildUrl(kind) as string);
    mgr = { ws, open: true };
    managers[kind] = mgr;

    ws.onopen = () => {
      attempt = 0;
      if (kind === "ticks") {
        // Subscribe to all symbols by default; the hook can refine.
        ws.send(JSON.stringify({ symbols: [] }));
      }
    };
    ws.onmessage = (ev) => {
      try {
        const data = JSON.parse(ev.data) as Record<string, unknown>;
        for (const cb of subscribers[kind] ?? []) cb(data);
      } catch {
        /* ignore non-JSON */
      }
    };
    ws.onclose = () => {
      if (mgr) mgr.open = false;
      // Only auto-reconnect if there are still subscribers.
      if ((subscribers[kind]?.size ?? 0) > 0) {
        attempt += 1;
        const delay = Math.min(15_000, 500 * 2 ** attempt);
        setTimeout(connect, delay);
      }
    };
    ws.onerror = () => {
      try {
        ws.close();
      } catch {
        /* noop */
      }
    };
  };
  connect();
  return mgr;
}

function subscribe(kind: WSKind, cb: (msg: Record<string, unknown>) => void): () => void {
  if (!subscribers[kind]) subscribers[kind] = new Set();
  subscribers[kind].add(cb);
  ensure(kind);
  return () => {
    subscribers[kind]?.delete(cb);
  };
}

/**
 * Subscribe to live ticks for a set of symbols. Returns the latest tick per
 * symbol and a running buffer (for sparkline-style charts).
 */
export function useTicks(symbols: string[] = []): {
  latest: Record<string, TickStream>;
  buffer: TickStream[];
} {
  const [latest, setLatest] = useState<Record<string, TickStream>>({});
  const [buffer, setBuffer] = useState<TickStream[]>([]);
  const bufRef = useRef<TickStream[]>([]);

  // biome-ignore lint/correctness/useExhaustiveDependencies: subscribe on the joined symbol key so array identity changes don't re-subscribe mid-stream
  useEffect(() => {
    const symSet = new Set(symbols);
    const unsub = subscribe("ticks", (msg) => {
      const tick = msg as unknown as TickStream;
      if (tick.type === "ping") return;
      if (!tick.symbol) return;
      if (symSet.size > 0 && !symSet.has(tick.symbol)) return;
      setLatest((prev) => ({ ...prev, [tick.symbol as string]: tick }));
      const next = [...bufRef.current, tick].slice(-200);
      bufRef.current = next;
      setBuffer(next);
    });
    return unsub;
  }, [symbols.join(",")]);

  return { latest, buffer };
}

/** Subscribe to terminal lifecycle / execution / risk events. */
export function useTerminalEvents(): Record<string, unknown>[] {
  const [events, setEvents] = useState<Record<string, unknown>[]>([]);
  const ref = useRef<Record<string, unknown>[]>([]);

  useEffect(() => {
    const unsub = subscribe("terminal-events", (msg) => {
      const next = [msg, ...ref.current].slice(0, 100);
      ref.current = next;
      setEvents(next);
    });
    return unsub;
  }, []);

  return events;
}

/**
 * Live account state for a connected MT5 terminal.
 *
 * Seeds from `POST /api/v1/terminals/{id}/sync-account` (the bridge asks the
 * terminal for its current balance/equity/margin), then merges live
 * `evt.account.update` events streamed over /ws/account.
 *
 * Pass `null` when no terminal is connected — the hook becomes a no-op.
 */
export function useAccount(terminalId: string | null): {
  account: AccountState | null;
  loading: boolean;
  error: Error | null;
} {
  const [account, setAccount] = useState<AccountState | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<Error | null>(null);

  // Seed via REST whenever the selected terminal changes.
  useEffect(() => {
    if (!terminalId) {
      setAccount(null);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);
    syncAccount(terminalId)
      .then((res) => {
        if (cancelled) return;
        const a = res.account;
        if (a && typeof a.balance === "number") {
          setAccount({ ...(a as unknown as AccountState), terminal_id: terminalId });
        }
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(err instanceof Error ? err : new Error(String(err)));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [terminalId]);

  // Merge live updates from /ws/account, scoped to this terminal.
  useEffect(() => {
    if (!terminalId) return;
    const unsub = subscribe("account", (msg) => {
      const data = msg as unknown as AccountState & { type?: string };
      if (data.type === "ping") return;
      if (data.terminal_id !== terminalId) return;
      if (typeof data.balance !== "number") return;
      setAccount({
        terminal_id: data.terminal_id,
        balance: Number(data.balance),
        equity: Number(data.equity),
        margin: Number(data.margin),
        free_margin: Number(data.free_margin),
        currency: data.currency,
        leverage: Number(data.leverage),
      });
    });
    return unsub;
  }, [terminalId]);

  return { account, loading, error };
}
