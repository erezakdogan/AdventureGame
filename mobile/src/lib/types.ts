// Shapes returned by the backend API (backend/app/main.py).

export type Rating = 'Buy' | 'Overweight' | 'Hold' | 'Underweight' | 'Sell' | 'REVIEW';

export interface Quote {
  symbol: string;
  price: number;
  previous_close: number | null;
  change: number | null;
  change_pct: number | null;
  currency: string | null;
  name: string | null;
  asset_type: 'stock' | 'crypto';
  ts: number;
}

export interface Bar {
  t: string;
  o: number;
  h: number;
  l: number;
  c: number;
  v: number;
}

export interface Position {
  symbol: string;
  name: string | null;
  quantity: number;
  avg_price: number;
  price: number;
  previous_close: number | null;
  market_value: number;
  cost_basis: number;
  unrealized_pnl: number;
  unrealized_pnl_pct: number;
  day_change_pct: number | null;
  weight_pct: number;
  asset_type: string;
  stale: boolean;
  opened_at: string;
}

export interface Account {
  cash: number;
  starting_cash: number;
  currency: string;
  equity: number;
  market_value: number;
  total_pnl: number;
  total_pnl_pct: number;
  day_pnl: number;
  realized_pnl: number;
  commissions_paid: number;
  positions: Position[];
  quote_errors: string[];
  created_at: string;
}

export interface EquityPoint {
  ts: string;
  equity: number;
  cash: number;
}

export interface Order {
  id: number;
  symbol: string;
  side: 'buy' | 'sell';
  quantity: number;
  order_type: 'market' | 'limit' | 'stop';
  limit_price: number | null;
  stop_price: number | null;
  status: 'open' | 'filled' | 'cancelled' | 'rejected';
  source: string;
  run_id: number | null;
  note: string | null;
  reject_reason: string | null;
  fill_price: number | null;
  commission: number | null;
  created_at: string;
  filled_at: string | null;
}

export interface Trade {
  id: number;
  order_id: number;
  symbol: string;
  side: 'buy' | 'sell';
  quantity: number;
  price: number;
  commission: number;
  realized_pnl: number | null;
  source: string;
  run_id: number | null;
  ts: string;
}

export interface OrderPlan {
  rating: Rating;
  action: 'buy' | 'sell' | 'none';
  quantity: number;
  reference_price: number | null;
  estimated_value: number;
  reason: string;
  stop_loss: number | null;
  take_profit: number | null;
  notes: string[];
}

export interface Proposal {
  rating: Rating;
  trader: {
    action: string | null;
    entry_price: number | null;
    stop_loss: number | null;
    position_sizing: string | null;
  };
  decision: {
    executive_summary: string | null;
    price_target: number | null;
    time_horizon: string | null;
  };
  memory_note: string | null;
  plan?: OrderPlan | null;
}

export type AgentStatus = 'pending' | 'in_progress' | 'completed';

export interface RunUsage {
  cost_usd?: number;
  input_tokens?: number;
  output_tokens?: number;
  calls?: number;
  cost_incomplete?: boolean;
  models?: Record<string, { calls: number; input: number; output: number; cost_usd: number | null }>;
}

export interface RunOptions {
  deep_model: string;
  quick_model: string;
  effort: string | null;
  analysts: string[];
  max_debate_rounds: number;
  max_risk_rounds: number;
  output_language: string;
  share_portfolio: boolean;
}

export interface Run {
  id: number;
  ticker: string;
  trade_date: string;
  asset_type: string;
  status: 'queued' | 'running' | 'completed' | 'failed' | 'cancelled';
  source: 'manual' | 'autopilot' | 'replay';
  replay_id: number | null;
  auto_execute: boolean;
  options: RunOptions;
  agents: Record<string, AgentStatus>;
  teams: Record<string, string>;
  reports?: Record<string, string>;
  rating: Rating | null;
  decision: string | null;
  proposal: Proposal | null;
  executed_order_ids: number[];
  usage: RunUsage;
  error: string | null;
  progress: number;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
}

export interface RunEvent {
  id: number;
  run_id: number;
  ts: string;
  agent: string | null;
  kind: 'status' | 'tool' | 'agent' | 'decision' | 'trade' | 'warning' | 'error';
  text: string;
}

export interface ChatMessage {
  id: number;
  role: 'user' | 'assistant';
  content: string;
  ts?: string;
}

export interface Autopilot {
  enabled: boolean;
  tickers: string[];
  run_time: string;
  timezone: string;
  weekdays_only: boolean;
  auto_execute: boolean;
  last_run_date: string | null;
}

export interface Settings {
  deep_model: string;
  quick_model: string;
  effort: string | null;
  output_language: string;
  analysts: string[];
  max_debate_rounds: number;
  max_risk_rounds: number;
  share_portfolio: boolean;
  auto_execute: boolean;
  max_position_pct: number;
  overweight_fraction: number;
  underweight_trim: number;
  use_stop_loss: boolean;
  use_take_profit: boolean;
  allow_fractional: boolean;
  commission_per_trade: number;
  commission_bps: number;
  slippage_bps: number;
  monthly_budget_usd: number | null;
  max_concurrent_runs: number;
  order_check_seconds: number;
  autopilot: Autopilot;
}

export interface KeyStatus {
  set: boolean;
  preview: string | null;
}

export interface SettingsResponse {
  settings: Settings;
  keys: Record<'anthropic' | 'fred' | 'alpha_vantage', KeyStatus>;
  autopilot_message?: string | null;
}

export interface ModelInfo {
  id: string;
  input_per_mtok: number;
  output_per_mtok: number;
  description: string;
}

export interface Preset {
  id: string;
  label: string;
  quick_model: string;
  deep_model: string;
  description: string;
}

export interface Usage {
  month_start: string;
  month_cost_usd: number;
  all_time_cost_usd: number;
  avg_run_cost_usd: number | null;
  monthly_budget_usd: number | null;
  by_model: { model: string; input_tokens: number; output_tokens: number; cost_usd: number }[];
  by_kind: { kind: string; cost_usd: number; items: number }[];
}

export interface ReplayStep {
  date: string;
  status: string;
  run_id?: number;
  rating?: Rating;
  action?: 'buy' | 'sell' | 'none';
  quantity?: number;
  fill_date?: string;
  price?: number;
  cash?: number;
  position?: number;
  equity?: number;
  reason?: string;
  note?: string;
  cost_usd?: number;
}

export interface Replay {
  id: number;
  ticker: string;
  start_date: string;
  end_date: string;
  every_n_days: number;
  starting_cash: number;
  status: 'queued' | 'running' | 'completed' | 'failed' | 'cancelled';
  steps: ReplayStep[];
  summary: {
    final_equity: number;
    return_pct: number;
    buy_hold_return_pct: number | null;
    max_drawdown_pct: number | null;
    marked_at: string;
    final_price: number;
    decisions: number;
    trades: number;
    ratings: Record<string, number>;
    cost_usd: number;
    curve: { date: string; equity: number; buy_hold: number }[];
  } | null;
  error: string | null;
  created_at: string;
  finished_at: string | null;
}
