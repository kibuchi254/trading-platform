/**
 * ATLAS API DTOs — mirror the backend Pydantic response models in `src/platform/api/v1`.
 */

export type UUID = string;

export interface TokenPair {
  access_token: string;
  refresh_token: string;
  token_type: string;
  expires_in: number;
}

export interface ApiKey {
  id: UUID;
  name: string;
  key_prefix: string;
  raw_key: string; // shown once on creation
  scopes: string[];
}

export interface Terminal {
  id: UUID;
  terminal_id: string;
  broker: string | null;
  broker_account: string;
  adapter_kind: string;
  version: string | null;
  status: string; // online | offline | degraded
  last_heartbeat_at: string | null;
  symbols: string[];
  capabilities: Record<string, unknown>;
  is_online: boolean;
}

export interface Order {
  id: UUID;
  client_order_id: string;
  broker_order_id: string | null;
  terminal_id: UUID;
  symbol: string;
  side: string; // buy | sell
  order_type: string; // market | limit | stop | stop_limit
  volume: number;
  price: number | null;
  stop_loss: number | null;
  take_profit: number | null;
  status: string; // pending | submitted | partial | filled | cancelled | rejected
  filled_volume: number;
  avg_fill_price: number | null;
  rejection_reason: string | null;
  created_at: string;
}

export interface PlaceOrderRequest {
  terminal_id: string;
  symbol: string;
  side: "buy" | "sell";
  order_type: "market" | "limit" | "stop" | "stop_limit";
  volume: number;
  price?: number | null;
  stop_loss?: number | null;
  take_profit?: number | null;
  strategy_id?: UUID | null;
  comment?: string | null;
  magic?: number | null;
}

export interface Position {
  id: UUID;
  terminal_id: UUID;
  broker_position_id: string | null;
  symbol: string;
  side: string;
  volume: number;
  open_price: number;
  current_price: number;
  stop_loss: number | null;
  take_profit: number | null;
  swap: number;
  unrealized_pnl: number;
  realized_pnl: number;
  status: string; // open | closed
  opened_at: string;
  closed_at: string | null;
}

export interface Trade {
  id: UUID;
  position_id: UUID;
  strategy_id: UUID | null;
  symbol: string;
  side: string;
  volume: number;
  entry_price: number;
  exit_price: number;
  pnl: number;
  pips: number;
  commission: number;
  swap: number;
  duration_seconds: number;
  opened_at: string;
  closed_at: string;
}

export interface Signal {
  id: UUID;
  strategy_id: UUID;
  terminal_id: UUID;
  symbol: string;
  side: string;
  strength: number;
  timeframe: string;
  price: number;
  source: string;
  meta: Record<string, unknown>;
  created_at: string;
}

export interface RiskEvent {
  id: UUID;
  terminal_id: UUID | null;
  rule: string;
  severity: string;
  action: string;
  details: Record<string, unknown>;
  order_id: UUID | null;
  resolved: boolean;
  resolved_at: string | null;
  created_at: string;
}

export interface Strategy {
  id: UUID;
  name: string;
  slug: string;
  kind: string;
  version: string;
  config: Record<string, unknown>;
  is_active: boolean;
  description: string | null;
}

export interface AvailableStrategy {
  name: string;
  version: string;
  default_config: Record<string, unknown>;
}

export interface Backtest {
  id: UUID;
  strategy_id: UUID;
  symbol: string;
  timeframe: string;
  start: string;
  end: string;
  initial_capital: number;
  final_equity: number | null;
  max_drawdown: number | null;
  sharpe: number | null;
  trades_count: number;
  status: string;
  config: Record<string, unknown>;
  results: Record<string, unknown>;
  created_at: string;
}

export interface Broker {
  id: UUID;
  name: string;
  code: string;
  adapter_kind: string;
  is_active: boolean;
  created_at: string;
}

export interface Symbol {
  id: UUID;
  name: string;
  category: string | null;
  digits: number;
  volume_min: number;
  volume_step: number;
  volume_max: number;
}

export interface Candle {
  ts: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface PerformanceSummary {
  total_trades: number;
  win_rate: number;
  total_pnl: number;
  avg_pnl: number;
  best_trade: number;
  worst_trade: number;
  avg_duration_seconds: number;
}

export interface OpenPosition {
  id: UUID;
  symbol: string;
  side: string;
  volume: number;
  open_price: number;
  current_price: number;
  unrealized_pnl: number;
  opened_at: string;
}

export interface SystemStatus {
  terminals_online: number;
  pending_commands: number;
  risk_kill_switch: boolean;
  env: string;
}

export interface KillSwitch {
  engaged: boolean;
}

export interface AnalysisOut {
  symbol: string;
  modules: Record<string, Record<string, unknown>>;
  composite_score: number;
}

export interface User {
  id: UUID;
  email: string;
  display_name: string;
  role: string;
  is_active: boolean;
  last_login_at: string | null;
  created_at: string;
}

export interface Notification {
  id: UUID;
  user_id: UUID | null;
  channel: string;
  subject: string | null;
  body: string;
  status: string;
  sent_at: string | null;
  error: string | null;
  created_at: string;
}

export interface AuditLog {
  id: number;
  actor_id: UUID | null;
  actor_type: string;
  action: string;
  resource_type: string | null;
  resource_id: string | null;
  ip: string | null;
  user_agent: string | null;
  payload: Record<string, unknown>;
  ts: string;
}

export interface Paginated<T> {
  [key: string]: T[] | unknown;
  total?: number;
}

export interface TickStream {
  type: string;
  terminal_id?: string;
  symbol?: string;
  bid?: number;
  ask?: number;
  last?: number | null;
  volume?: number | null;
  ts?: string;
}

/** Live MT5 account state — balance/equity/margin pushed by the terminal. */
export interface AccountState {
  terminal_id: string;
  balance: number;
  equity: number;
  margin: number;
  free_margin: number;
  currency: string;
  leverage: number;
}
