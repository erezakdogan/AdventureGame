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
  benchmark?: number | null;
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
  source: 'manual' | 'autopilot' | 'replay' | 'fund';
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

export interface Prediction {
  id: number;
  created_at: string;
  source: string;
  run_id: number | null;
  fund_id: number | null;
  cycle_id: number | null;
  ticker: string;
  direction: 'up' | 'down' | 'flat';
  rating: Rating | null;
  entry_price: number;
  target_price: number | null;
  stop_price: number | null;
  horizon_text: string | null;
  horizon_hours: number;
  due_at: string;
  confidence: number | null;
  rationale: string | null;
  status: 'open' | 'scored' | 'no_data';
  scored_at: string | null;
  price_at_due: number | null;
  return_pct: number | null;
  progress_pct: number | null;
  accuracy_pct: number | null;
  peak_progress_pct: number | null;
  hit_target: number | null;
  hit_target_at: string | null;
  hit_stop: number | null;
  direction_correct: number | null;
  target_error_pct: number | null;
  score: number | null;
  note: string | null;
  time_left_hours: number;
  current_price?: number;
  current_return_pct?: number;
  current_progress_pct?: number;
}

export interface PredictionStats {
  total: number;
  open: number;
  scored: number;
  avg_accuracy_pct: number | null;
  avg_precision_pct: number | null;
  target_hit_rate_pct: number | null;
  direction_rate_pct: number | null;
  avg_peak_reach_pct: number | null;
  stop_hit_rate_pct: number | null;
  avg_return_pct: number | null;
  by_direction: Record<'up' | 'down' | 'flat', { count: number; avg_accuracy_pct: number | null; direction_rate_pct: number | null }>;
  recent_accuracy: { id: number; ticker: string; accuracy_pct: number | null; scored_at: string }[];
}

export type FundStyle = 'hourly' | 'day' | 'swing' | 'position' | 'custom';

export interface FundConfig {
  style: FundStyle;
  interval_minutes: number;
  universe: string[];
  max_positions: number;
  max_position_pct: number;
  cash_reserve_pct: number;
  model: string;
  effort: string | null;
  deep_dive: number;
  market_hours_only: boolean;
  flatten_at_close: boolean;
  use_stop_loss: boolean;
  use_take_profit: boolean;
  allow_fractional: boolean;
  include_news: boolean;
  instructions: string;
  benchmark: string | null;
}

export interface Fund {
  id: number;
  name: string;
  account_id: number;
  style: FundStyle;
  style_label: string;
  config: FundConfig;
  status: 'active' | 'paused';
  benchmark_symbol: string | null;
  benchmark_start: number | null;
  created_at: string;
  last_cycle_at: string | null;
  next_cycle_at: string | null;
  last_error: string | null;
  running: boolean;
  equity: number;
  cash: number;
  starting_cash: number;
  total_pnl: number;
  total_pnl_pct: number;
  day_pnl: number;
  realized_pnl: number;
  commissions_paid: number;
  trade_count: number;
  closed_trades: number;
  win_rate_pct: number | null;
  max_drawdown_pct: number;
  benchmark_now: number | null;
  benchmark_return_pct: number | null;
  cycles: number;
  claude_cost_usd: number;
  accuracy: Partial<PredictionStats>;
  positions?: Position[];
  quote_errors?: string[];
}

export interface FundDecision {
  ticker: string;
  action: 'buy' | 'add' | 'hold' | 'trim' | 'sell' | 'avoid';
  target_weight_pct?: number;
  expected_price?: number;
  horizon_hours?: number;
  stop_loss?: number | null;
  confidence?: number;
  rationale?: string;
  price?: number | null;
  executed: string;
  side?: 'buy' | 'sell' | null;
  quantity?: number | null;
  fill_price?: number | null;
  expected_move_pct?: number | null;
  error?: string;
}

export interface FundCycle {
  id: number;
  fund_id: number;
  trigger: string;
  status: 'running' | 'completed' | 'failed' | 'skipped';
  started_at: string;
  finished_at: string | null;
  equity_before: number | null;
  equity_after: number | null;
  market_view: string | null;
  decisions: FundDecision[];
  orders: Order[];
  run_ids: number[];
  usage: RunUsage;
  error: string | null;
}

export interface FundCatalog {
  styles: { id: FundStyle; label: string; interval_minutes: number; horizon_hours: [number, number]; flatten: boolean; brief: string }[];
  universes: Record<string, string[]>;
}
