/**
 * Typed ATLAS REST endpoint wrappers. Each maps to a backend router under
 * /api/v1. All functions throw ApiError on failure.
 */

import { apiFetch } from "./client";
import type {
  AnalysisOut,
  AuditLog,
  AvailableStrategy,
  Backtest,
  Broker,
  Candle,
  KillSwitch,
  Notification,
  OpenPosition,
  Order,
  PerformanceSummary,
  PlaceOrderRequest,
  Position,
  RiskEvent,
  Signal,
  Strategy,
  Symbol as SymbolT,
  SystemStatus,
  Terminal,
  Trade,
  User,
} from "./types";

// ── Terminals ────────────────────────────────────────────────────────────
export const getMe = () =>
  apiFetch<{
    user_id: string;
    org_id: string;
    email: string;
    display_name: string;
    role: string;
    auth_method: string;
  }>("/api/v1/auth/me");

export const listTerminals = (status?: string) => apiFetch<Terminal[]>("/api/v1/terminals", { query: { status } });
export const getTerminal = (id: string) => apiFetch<Terminal>(`/api/v1/terminals/${id}`);
export const syncPositions = (id: string) =>
  apiFetch<{ status: string; received: string }>(`/api/v1/terminals/${id}/sync-positions`, {
    method: "POST",
  });
export const syncAccount = (id: string) =>
  apiFetch<{ status: string; account: Record<string, unknown> }>(`/api/v1/terminals/${id}/sync-account`, {
    method: "POST",
  });
export const flattenTerminal = (id: string) =>
  apiFetch<{ terminal_id: string; positions_closed: number; orders_cancelled: number }>(
    `/api/v1/terminals/${id}/flatten`,
    { method: "POST" },
  );

// ── Orders ───────────────────────────────────────────────────────────────
export const listOrders = (status?: string, limit = 100) =>
  apiFetch<Order[]>("/api/v1/orders", { query: { status, limit } });
export const getOrder = (id: string) => apiFetch<Order>(`/api/v1/orders/${id}`);
export const placeOrder = (req: PlaceOrderRequest) =>
  apiFetch<{
    order_id: string;
    client_order_id: string;
    broker_order_id: string | null;
    status: string;
    filled_volume: number;
    avg_fill_price: number | null;
    rejection_reason: string | null;
  }>("/api/v1/orders", { method: "POST", body: req });
export const cancelOrder = (id: string) =>
  apiFetch<{ order_id: string; status: string }>(`/api/v1/orders/${id}/cancel`, {
    method: "POST",
  });

// ── Positions ────────────────────────────────────────────────────────────
export const listPositions = (status = "all", limit = 200) =>
  apiFetch<{ positions?: Position[]; total?: number }>("/api/v1/positions", { query: { status, limit } }).then(
    (r) => r.positions ?? [],
  );
export const getPosition = (id: string) => apiFetch<Position>(`/api/v1/positions/${id}`);
export const closePosition = (id: string, volume?: number) =>
  apiFetch<{ position_id: string; status: string }>(`/api/v1/positions/${id}/close`, {
    method: "POST",
    body: { volume: volume ?? null },
  });
export const modifyPosition = (id: string, body: { stop_loss?: number; take_profit?: number }) =>
  apiFetch<{ position_id: string; status: string }>(`/api/v1/positions/${id}/modify`, {
    method: "POST",
    body,
  });

// ── Trades (the ledger / "books") ─────────────────────────────────────────
export const listTrades = (query: { symbol?: string; strategy_id?: string; limit?: number } = {}) =>
  apiFetch<{ trades?: Trade[]; total?: number }>("/api/v1/trades", { query }).then((r) => r.trades ?? []);

// ── Signals ───────────────────────────────────────────────────────────────
export const listSignals = (query: { symbol?: string; strategy_id?: string; limit?: number } = {}) =>
  apiFetch<{ signals?: Signal[]; total?: number }>("/api/v1/signals", { query }).then((r) => r.signals ?? []);

// ── Risk ──────────────────────────────────────────────────────────────────
export const getKillSwitch = () => apiFetch<KillSwitch>("/api/v1/risk/kill-switch");
export const engageKillSwitch = () => apiFetch<KillSwitch>("/api/v1/risk/kill-switch/engage", { method: "POST" });
export const releaseKillSwitch = () => apiFetch<KillSwitch>("/api/v1/risk/kill-switch/release", { method: "POST" });
export const listRiskEvents = (query: { severity?: string; rule?: string; resolved?: boolean; limit?: number } = {}) =>
  apiFetch<{ events?: RiskEvent[]; total?: number }>("/api/v1/risk-events", { query }).then((r) => r.events ?? []);

// ── Strategies ─────────────────────────────────────────────────────────────
export const listStrategies = () => apiFetch<Strategy[]>("/api/v1/strategies");
export const listAvailableStrategies = () => apiFetch<AvailableStrategy[]>("/api/v1/strategies/available");
export const createStrategy = (body: {
  name: string;
  slug: string;
  kind: string;
  config?: Record<string, unknown>;
  description?: string;
}) => apiFetch<Strategy>("/api/v1/strategies", { method: "POST", body });
export const activateStrategy = (id: string) =>
  apiFetch<Strategy>(`/api/v1/strategies/${id}/activate`, { method: "POST" });
export const deactivateStrategy = (id: string) =>
  apiFetch<Strategy>(`/api/v1/strategies/${id}/deactivate`, { method: "POST" });

// ── Backtests ─────────────────────────────────────────────────────────────
export const listBacktests = (limit = 50) => apiFetch<Backtest[]>("/api/v1/backtests", { query: { limit } });
export const getBacktest = (id: string) => apiFetch<Backtest>(`/api/v1/backtests/${id}`);
export const runBacktest = (body: {
  strategy_id: string;
  symbol: string;
  timeframe: string;
  start: string;
  end: string;
  initial_capital?: number;
  config?: Record<string, unknown>;
}) =>
  apiFetch<{ backtest_id: string; status: string; queued: boolean }>("/api/v1/backtests", {
    method: "POST",
    body,
  });

// ── Brokers ───────────────────────────────────────────────────────────────
export const listBrokers = () => apiFetch<Broker[]>("/api/v1/brokers");
export const createBroker = (body: {
  name: string;
  code: string;
  adapter_kind?: string;
  credentials?: Record<string, unknown>;
}) => apiFetch<Broker>("/api/v1/brokers", { method: "POST", body });
export const deactivateBroker = (id: string) =>
  apiFetch<Broker>(`/api/v1/brokers/${id}/deactivate`, { method: "PATCH" });

// ── Market data ───────────────────────────────────────────────────────────
export const listSymbols = () => apiFetch<SymbolT[]>("/api/v1/market-data/symbols");
export const getCandles = (symbol: string, timeframe = "M15", limit = 500) =>
  apiFetch<Candle[]>(`/api/v1/market-data/candles/${symbol}`, { query: { timeframe, limit } });

// ── AI ────────────────────────────────────────────────────────────────────
export const analyze = (body: { symbol: string; timeframe?: string; features?: Record<string, unknown> }) =>
  apiFetch<AnalysisOut>("/api/v1/ai/analyze", { method: "POST", body });
export const assistantChat = (message: string, context: Record<string, unknown> = {}) =>
  apiFetch<{ reply: string }>("/api/v1/ai/assistant/chat", { method: "POST", body: { message, context } });

// ── Analytics ─────────────────────────────────────────────────────────────
export const getPerformance = (days = 30) =>
  apiFetch<PerformanceSummary>("/api/v1/analytics/performance", { query: { days } });
export const getOpenPositions = () => apiFetch<OpenPosition[]>("/api/v1/analytics/positions/open");

// ── Admin ──────────────────────────────────────────────────────────────────
export const getSystemStatus = () => apiFetch<SystemStatus>("/api/v1/admin/status");
export const listUsers = () => apiFetch<User[]>("/api/v1/admin/users");
export const createUser = (body: { email: string; password: string; display_name: string; role?: string }) =>
  apiFetch<User>("/api/v1/admin/users", { method: "POST", body });
export const activateUser = (id: string) => apiFetch<User>(`/api/v1/admin/users/${id}/activate`, { method: "PATCH" });
export const deactivateUser = (id: string) =>
  apiFetch<User>(`/api/v1/admin/users/${id}/deactivate`, { method: "PATCH" });
export const listAuditLogs = (query: { action?: string; limit?: number } = {}) =>
  apiFetch<AuditLog[]>("/api/v1/admin/audit-logs", { query });

// ── Notifications ─────────────────────────────────────────────────────────
export const listNotifications = (query: { channel?: string; status?: string; mine?: boolean; limit?: number } = {}) =>
  apiFetch<Notification[]>("/api/v1/notifications", { query });
