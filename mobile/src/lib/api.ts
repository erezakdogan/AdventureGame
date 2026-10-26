// Typed client for the paper-trading backend. The server URL and access token
// come from the connection screen and live in the device's secure storage.
import * as SecureStore from 'expo-secure-store';
import { Platform } from 'react-native';

import type {
  Account,
  Bar,
  ChatMessage,
  EquityPoint,
  Fund,
  FundCatalog,
  FundConfig,
  FundCycle,
  ModelInfo,
  Order,
  OrderPlan,
  Prediction,
  PredictionStats,
  Preset,
  Quote,
  Replay,
  Run,
  RunEvent,
  Settings,
  SettingsResponse,
  Trade,
  Usage,
} from './types';

export interface Connection {
  url: string;
  token: string;
}

const STORE_KEY = 'papertrader.connection';

// SecureStore has no web implementation; fall back to localStorage there so the
// app can also be tried in a browser with `npx expo start --web`.
export async function loadConnection(): Promise<Connection | null> {
  try {
    const raw =
      Platform.OS === 'web'
        ? globalThis.localStorage?.getItem(STORE_KEY) ?? null
        : await SecureStore.getItemAsync(STORE_KEY);
    return raw ? (JSON.parse(raw) as Connection) : null;
  } catch {
    return null;
  }
}

export async function saveConnection(conn: Connection | null): Promise<void> {
  if (Platform.OS === 'web') {
    if (conn) globalThis.localStorage?.setItem(STORE_KEY, JSON.stringify(conn));
    else globalThis.localStorage?.removeItem(STORE_KEY);
    return;
  }
  if (conn) await SecureStore.setItemAsync(STORE_KEY, JSON.stringify(conn));
  else await SecureStore.deleteItemAsync(STORE_KEY);
}

export function normalizeUrl(url: string): string {
  let u = url.trim().replace(/\/+$/, '');
  if (u && !/^https?:\/\//i.test(u)) u = `http://${u}`;
  return u;
}

export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

let current: Connection | null = null;

export function setActiveConnection(conn: Connection | null) {
  current = conn;
}

async function request<T>(
  method: string,
  path: string,
  body?: unknown,
  conn: Connection | null = current,
  timeoutMs = 30000,
): Promise<T> {
  if (!conn) throw new ApiError('Not connected to a server', 0);
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  let res: Response;
  try {
    res = await fetch(`${conn.url}${path}`, {
      method,
      headers: {
        Authorization: `Bearer ${conn.token}`,
        ...(body !== undefined ? { 'Content-Type': 'application/json' } : {}),
      },
      body: body !== undefined ? JSON.stringify(body) : undefined,
      signal: controller.signal,
    });
  } catch (e) {
    const aborted = (e as Error)?.name === 'AbortError';
    throw new ApiError(
      aborted ? 'The server took too long to answer' : `Cannot reach ${conn.url}. Is the server running?`,
      0,
    );
  } finally {
    clearTimeout(timer);
  }
  const text = await res.text();
  let data: unknown = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = null;
  }
  if (!res.ok) {
    const detail = (data as { detail?: unknown } | null)?.detail;
    const message =
      typeof detail === 'string'
        ? detail
        : Array.isArray(detail)
          ? detail.map((d: { msg?: string }) => d.msg).join('; ')
          : res.status === 401
            ? 'The access token was not accepted'
            : `Request failed (${res.status})`;
    throw new ApiError(message, res.status);
  }
  return data as T;
}

function query(q: Record<string, string | number | undefined>): string {
  const parts = Object.entries(q)
    .filter(([, v]) => v !== undefined && v !== '')
    .map(([k, v]) => `${k}=${encodeURIComponent(String(v))}`);
  return parts.length ? `?${parts.join('&')}` : '';
}

const get = <T>(p: string) => request<T>('GET', p);
const post = <T>(p: string, b: unknown = {}, timeoutMs?: number) =>
  request<T>('POST', p, b, current, timeoutMs);
const patch = <T>(p: string, b: unknown) => request<T>('PATCH', p, b);
const put = <T>(p: string, b: unknown) => request<T>('PUT', p, b);
const del = <T>(p: string) => request<T>('DELETE', p);

export const api = {
  checkConnection: (conn: Connection) =>
    request<{ ok: boolean }>('GET', '/api/session', undefined, conn, 10000),
  health: (conn: Connection) =>
    request<{ ok: boolean; app_version: string; tradingagents_version: string }>(
      'GET',
      '/api/health',
      undefined,
      conn,
      10000,
    ),

  account: () => get<Account>('/api/account'),
  equity: (days?: number) => get<{ points: EquityPoint[] }>(`/api/account/equity${days ? `?days=${days}` : ''}`),
  resetAccount: (starting_cash: number) => post<Account>('/api/account/reset', { starting_cash }),

  orders: (status?: string) => get<{ orders: Order[] }>(`/api/orders${status ? `?status=${status}` : ''}`),
  placeOrder: (o: {
    symbol: string;
    side: 'buy' | 'sell';
    quantity?: number;
    notional?: number;
    order_type: 'market' | 'limit' | 'stop';
    limit_price?: number;
    stop_price?: number;
  }) => post<Order>('/api/orders', o),
  cancelOrder: (id: number) => del<Order>(`/api/orders/${id}`),
  trades: (symbol?: string) =>
    get<{ trades: Trade[] }>(`/api/trades${symbol ? `?symbol=${encodeURIComponent(symbol)}` : ''}`),

  quote: (symbol: string) => get<Quote>(`/api/market/quote/${encodeURIComponent(symbol)}`),
  quotes: (symbols: string[]) =>
    get<{ quotes: Quote[]; errors: Record<string, string> }>(
      `/api/market/quotes?symbols=${encodeURIComponent(symbols.join(','))}`,
    ),
  history: (symbol: string, period: string, interval: string) =>
    get<{ symbol: string; bars: Bar[] }>(
      `/api/market/history/${encodeURIComponent(symbol)}?period=${period}&interval=${interval}`,
    ),

  watchlist: () => get<{ symbols: string[] }>('/api/watchlist'),
  watch: (symbol: string) => post<{ symbols: string[] }>('/api/watchlist', { symbol }),
  unwatch: (symbol: string) => del<{ symbols: string[] }>(`/api/watchlist/${encodeURIComponent(symbol)}`),

  runs: (ticker?: string) =>
    get<{ runs: Run[] }>(`/api/runs${ticker ? `?ticker=${encodeURIComponent(ticker)}` : ''}`),
  run: (id: number) => get<Run>(`/api/runs/${id}`),
  runEvents: (id: number, after = 0) => get<{ events: RunEvent[] }>(`/api/runs/${id}/events?after=${after}`),
  startRun: (body: Record<string, unknown>) => post<Run>('/api/runs', body),
  cancelRun: (id: number) => post<Run>(`/api/runs/${id}/cancel`),
  deleteRun: (id: number) => del<{ ok: boolean }>(`/api/runs/${id}`),
  refreshPlan: (id: number) => post<OrderPlan>(`/api/runs/${id}/plan`),
  executeRun: (id: number, quantity?: number) =>
    post<{ orders: Order[]; run: Run }>(`/api/runs/${id}/execute`, quantity ? { quantity } : {}),
  chat: (id: number) => get<{ messages: ChatMessage[] }>(`/api/runs/${id}/chat`),
  ask: (id: number, question: string) =>
    post<ChatMessage & { cost_usd: number }>(`/api/runs/${id}/chat`, { question }, 180000),

  replays: () => get<{ replays: Replay[]; max_steps: number }>('/api/replays'),
  replay: (id: number) => get<Replay>(`/api/replays/${id}`),
  startReplay: (b: {
    ticker: string;
    start_date: string;
    end_date: string;
    every_n_days: number;
    starting_cash: number;
  }) => post<Replay>('/api/replays', b),
  cancelReplay: (id: number) => post<Replay>(`/api/replays/${id}/cancel`),

  predictions: (q: { source?: string; fund_id?: number; status?: string; run_id?: number; ticker?: string } = {}) =>
    get<{ predictions: Prediction[] }>(`/api/predictions${query(q)}`),
  predictionStats: (q: { source?: string; fund_id?: number; ticker?: string } = {}) =>
    get<PredictionStats>(`/api/predictions/stats${query(q)}`),
  evaluatePredictions: () => post<{ scored: number }>('/api/predictions/evaluate', {}, 120000),

  fundCatalog: () => get<FundCatalog>('/api/funds/catalog'),
  funds: () => get<{ funds: Fund[] }>('/api/funds'),
  fund: (id: number) => get<Fund>(`/api/funds/${id}`),
  createFund: (b: { name: string; starting_cash: number; run_now: boolean; config: Partial<FundConfig> }) =>
    post<Fund>('/api/funds', b),
  updateFund: (id: number, p: Partial<FundConfig> & { name?: string; status?: 'active' | 'paused' }) =>
    patch<Fund>(`/api/funds/${id}`, p),
  deleteFund: (id: number) => del<{ ok: boolean }>(`/api/funds/${id}`),
  runFundCycle: (id: number) => post<{ ok: boolean }>(`/api/funds/${id}/cycle`),
  depositFund: (id: number, amount: number) => post<Fund>(`/api/funds/${id}/deposit`, { amount }),
  fundCycles: (id: number) => get<{ cycles: FundCycle[] }>(`/api/funds/${id}/cycles`),
  fundCycle: (cycleId: number) => get<FundCycle>(`/api/fund-cycles/${cycleId}`),
  fundEquity: (id: number) =>
    get<{ points: EquityPoint[]; benchmark_start: number | null; benchmark_symbol: string | null }>(
      `/api/funds/${id}/equity`,
    ),
  fundTrades: (id: number) => get<{ trades: Trade[] }>(`/api/funds/${id}/trades`),

  settings: () => get<SettingsResponse>('/api/settings'),
  updateSettings: (p: Partial<Settings> | Record<string, unknown>) => patch<SettingsResponse>('/api/settings', p),
  setKey: (name: 'anthropic' | 'fred' | 'alpha_vantage', value: string | null) =>
    put<Pick<SettingsResponse, 'keys'>>('/api/settings/keys', { name, value }),
  testKey: () => post<{ ok: boolean; message: string }>('/api/settings/keys/test'),
  models: () => get<{ models: ModelInfo[]; presets: Preset[]; efforts: string[] }>('/api/models'),
  usage: () => get<Usage>('/api/usage'),
};
