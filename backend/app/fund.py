"""AI funds: a pot of paper money that Claude manages across a universe of tickers.

Each fund owns a separate paper account. On its schedule (hourly, a few times a
day, daily or weekly) a cycle:

1. scores every ticker in its universe on technicals at the style's timeframe
   (trend, momentum, RSI, volatility, distance from highs and lows) and, if
   enabled, the latest headlines;
2. asks Claude, acting as the fund's portfolio manager, for one structured
   allocation: a target weight per ticker plus a forecast (expected price,
   horizon, stop-loss, confidence) and the reasoning; the fund's own track
   record is in the prompt, so it sees how its past forecasts did;
3. optionally sends the strongest new buys through the full TradingAgents team
   and drops any the team does not back;
4. rebalances the account toward the targets (sells first, then buys, within
   the position limits and cash reserve), places protective stops and targets;
5. records a forecast for every trade, which the track record scores when its
   horizon ends.

Day-trading styles can close every position shortly before the US close.
"""

from __future__ import annotations

import logging
import statistics
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, time, timedelta
from typing import Any, Literal
from zoneinfo import ZoneInfo

import anthropic
from pydantic import BaseModel, Field, field_validator

from .agents import RunError, RunManager
from .broker import BrokerError, PaperBroker, create_account, delete_account
from .db import Database, dumps, loads, utcnow
from .market import Bar, MarketData, MarketDataError, asset_type_of, clean_symbol, today_iso
from .predictions import PredictionService
from .settings_store import EFFORT_LEVELS, SettingsStore
from .usage import UsageTracker

logger = logging.getLogger(__name__)

NY = ZoneInfo("America/New_York")
OPEN, CLOSE = time(9, 30), time(16, 0)
FLATTEN_AT = time(15, 45)

Style = Literal["hourly", "day", "swing", "position", "custom"]

STYLES: dict[str, dict[str, Any]] = {
    "hourly": {
        "label": "Hourly trading", "interval_minutes": 60, "horizon": (1, 6),
        "frames": [("5d", "15m"), ("3mo", "1d")], "flatten": True,
        "brief": "an hourly trader: you trade intraday swings and expect each position to play out within "
                 "1 to 6 hours",
    },
    "day": {
        "label": "Day trading", "interval_minutes": 120, "horizon": (2, 7),
        "frames": [("5d", "30m"), ("3mo", "1d")], "flatten": True,
        "brief": "a day trader: you open positions in the morning and midday, expect them to work within "
                 "the same session, and the fund is flat by the close",
    },
    "swing": {
        "label": "Swing trading (daily)", "interval_minutes": 24 * 60, "horizon": (48, 15 * 24),
        "frames": [("6mo", "1d")], "flatten": False,
        "brief": "a swing trader: you review the book once a day and hold positions for days to a few weeks",
    },
    "position": {
        "label": "Long-term (weekly)", "interval_minutes": 7 * 24 * 60, "horizon": (30 * 24, 180 * 24),
        "frames": [("1y", "1d"), ("5y", "1wk")], "flatten": False,
        "brief": "a long-term position investor: you review the book weekly and hold positions for one to six "
                 "months, ignoring day-to-day noise",
    },
    "custom": {
        "label": "Custom interval", "interval_minutes": 240, "horizon": (1, 30 * 24),
        "frames": [("1mo", "1h"), ("6mo", "1d")], "flatten": False,
        "brief": "a tactical trader on a fixed review interval",
    },
}

UNIVERSES = {
    "us_megacaps": ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "AVGO", "JPM", "V", "LLY", "XOM"],
    "us_etfs": ["SPY", "QQQ", "IWM", "DIA", "XLK", "XLF", "XLE", "XLV", "GLD", "TLT"],
    "crypto": ["BTC-USD", "ETH-USD", "SOL-USD", "XRP-USD", "ADA-USD", "DOGE-USD", "AVAX-USD", "LINK-USD"],
    "global": ["SPY", "AAPL", "NVDA", "ASML", "7203.T", "SONY", "AZN.L", "SHEL.L", "0700.HK", "BABA",
               "RELIANCE.NS", "SAP.DE"],
    "ai_semis": ["NVDA", "AMD", "AVGO", "TSM", "ASML", "INTC", "QCOM", "MU", "ARM", "SMCI"],
}


class FundError(ValueError):
    """A fund request the server refuses; the message is shown to the user."""


class FundConfig(BaseModel):
    style: Style = "swing"
    interval_minutes: int = Field(default=240, ge=15, le=7 * 24 * 60)
    universe: list[str] = Field(default_factory=lambda: list(UNIVERSES["us_megacaps"]))
    max_positions: int = Field(default=5, ge=1, le=20)
    max_position_pct: float = Field(default=25.0, gt=0, le=100)
    cash_reserve_pct: float = Field(default=5.0, ge=0, le=90)
    model: str = "claude-opus-5-5"
    effort: str | None = "medium"
    deep_dive: int = Field(default=0, ge=0, le=3)
    market_hours_only: bool = True
    flatten_at_close: bool = False
    use_stop_loss: bool = True
    use_take_profit: bool = True
    allow_fractional: bool = True
    include_news: bool = True
    instructions: str = Field(default="", max_length=1500)
    benchmark: str | None = None

    @field_validator("universe")
    @classmethod
    def _universe(cls, v: list[str]) -> list[str]:
        out = list(dict.fromkeys(clean_symbol(t) for t in v if t and t.strip()))
        if not out:
            raise ValueError("the universe needs at least one ticker")
        if len(out) > 40:
            raise ValueError("keep the universe to 40 tickers or fewer")
        return out

    @field_validator("model")
    @classmethod
    def _model(cls, v: str) -> str:
        if not v.strip().startswith("claude-"):
            raise ValueError("model must be a Claude model ID")
        return v.strip()

    @field_validator("effort")
    @classmethod
    def _effort(cls, v: str | None) -> str | None:
        if v in (None, "", "default"):
            return None
        if v not in EFFORT_LEVELS:
            raise ValueError(f"effort must be one of {', '.join(EFFORT_LEVELS)}")
        return v


# -- what Claude returns -------------------------------------------------------


class TickerDecision(BaseModel):
    ticker: str = Field(description="Ticker exactly as listed in the universe or the current holdings")
    action: Literal["buy", "add", "hold", "trim", "sell", "avoid"] = Field(
        description="buy = open a new position, add = increase a held one, hold = keep as is, "
                    "trim = reduce, sell = close, avoid = do not own")
    target_weight_pct: float = Field(
        description="Desired weight of this ticker as a percentage of total fund equity after this cycle. "
                    "0 for sell and avoid.")
    expected_price: float = Field(
        description="The price you expect at the end of the horizon, in the ticker's quote currency. "
                    "Above the current price if you expect a rise, below it if you expect a fall.")
    horizon_hours: float = Field(description="Hours until you expect the expected_price to be reached")
    stop_loss: float | None = Field(
        default=None, description="Price at which the position should be exited if wrong (below the current "
                                  "price for longs); null if none")
    confidence: float = Field(description="Confidence in this forecast from 0 to 1")
    rationale: str = Field(description="One or two sentences citing the evidence")


class AllocationPlan(BaseModel):
    market_view: str = Field(description="Three to five sentences on the market and how the fund is positioned")
    decisions: list[TickerDecision] = Field(
        description="One entry per ticker in the universe and per current holding")


# -- technical snapshot ----------------------------------------------------------


def _rsi(closes: list[float], n: int = 14) -> float | None:
    if len(closes) <= n:
        return None
    gains = losses = 0.0
    for a, b in zip(closes[-n - 1:-1], closes[-n:], strict=True):
        d = b - a
        gains += max(d, 0)
        losses += max(-d, 0)
    if losses == 0:
        return 100.0
    rs = (gains / n) / (losses / n)
    return 100 - 100 / (1 + rs)


def _pct(a: float, b: float) -> float | None:
    return (a - b) / b * 100 if b else None


def frame_features(bars: list[Bar]) -> dict[str, Any]:
    """Compact, model-readable technicals for one timeframe."""
    closes = [b.c for b in bars]
    if len(closes) < 3:
        return {}
    last = closes[-1]
    rets = [(b - a) / a * 100 for a, b in zip(closes[:-1], closes[1:], strict=True) if a]
    out: dict[str, Any] = {
        "bars": len(closes),
        "chg_1": _pct(last, closes[-2]),
        "chg_5": _pct(last, closes[-6]) if len(closes) > 5 else None,
        "chg_20": _pct(last, closes[-21]) if len(closes) > 20 else None,
        "chg_all": _pct(last, closes[0]),
        "rsi14": _rsi(closes),
        "vol_per_bar": statistics.pstdev(rets[-20:]) if len(rets) >= 5 else None,
        "from_high": _pct(last, max(b.h for b in bars)),
        "from_low": _pct(last, min(b.l for b in bars)),
    }
    for n in (10, 20, 50):
        if len(closes) >= n:
            out[f"vs_sma{n}"] = _pct(last, sum(closes[-n:]) / n)
    vols = [b.v for b in bars[-21:-1] if b.v]
    if vols and bars[-1].v:
        out["volume_vs_avg"] = bars[-1].v / (sum(vols) / len(vols))
    return out


def _fmt(features: dict[str, Any]) -> str:
    parts = []
    for k, v in features.items():
        if v is None:
            continue
        parts.append(f"{k}={v:.2f}" if isinstance(v, float) else f"{k}={v}")
    return ", ".join(parts)


def us_market_open(now: datetime) -> bool:
    local = now.astimezone(NY)
    return local.weekday() < 5 and OPEN <= local.time() < CLOSE


def next_session_time(now: datetime, at: time) -> datetime:
    """The next weekday ``at`` (New York time) strictly after ``now``."""
    local = now.astimezone(NY)
    day = local.date()
    for _ in range(8):
        candidate = datetime.combine(day, at, NY)
        if candidate > local and candidate.weekday() < 5:
            return candidate.astimezone(UTC)
        day += timedelta(days=1)
    return (now + timedelta(days=1)).astimezone(UTC)


class FundService:
    def __init__(self, db: Database, broker: PaperBroker, market: MarketData, settings: SettingsStore,
                 runs: RunManager, predictions: PredictionService, allocator=None):
        self.db = db
        self.broker = broker
        self.market = market
        self.settings = settings
        self.runs = runs
        self.predictions = predictions
        # allocator(fund, prompt, system) -> (AllocationPlan, UsageTracker); swapped out in tests.
        self.allocator = allocator or self._claude_allocate
        self._busy: set[int] = set()
        self._lock = threading.Lock()
        self.executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="fund")

    def recover(self) -> None:
        self.db.execute("UPDATE fund_cycles SET status = 'failed', error = 'interrupted by a server restart', "
                        "finished_at = ? WHERE status = 'running'", (utcnow(),))

    def shutdown(self) -> None:
        self.executor.shutdown(wait=False, cancel_futures=True)

    # -- CRUD ----------------------------------------------------------------

    def _decode(self, row: dict[str, Any] | None) -> dict[str, Any] | None:
        if row is None:
            return None
        out = dict(row)
        out["config"] = loads(row["config"], {})
        out["style_label"] = STYLES.get(row["style"], {}).get("label", row["style"])
        return out

    def get(self, fund_id: int) -> dict[str, Any]:
        fund = self._decode(self.db.query_one("SELECT * FROM funds WHERE id = ?", (fund_id,)))
        if fund is None:
            raise FundError("no such fund")
        return fund

    def fund_broker(self, fund: dict[str, Any]) -> PaperBroker:
        return self.broker.for_account(fund["account_id"], fractional=fund["config"].get("allow_fractional", True))

    def create(self, name: str, starting_cash: float, config: dict[str, Any], run_now: bool = True) -> dict[str, Any]:
        name = (name or "").strip()[:60] or "AI Fund"
        style = config.get("style", "swing")
        if style not in STYLES:
            raise FundError(f"style must be one of {', '.join(STYLES)}")
        defaults = {"interval_minutes": STYLES[style]["interval_minutes"], "flatten_at_close": STYLES[style]["flatten"]}
        cfg = FundConfig.model_validate({**defaults, **config})
        if style != "custom":
            cfg.interval_minutes = STYLES[style]["interval_minutes"]
        crypto_only = all(asset_type_of(t) == "crypto" for t in cfg.universe)
        cfg.benchmark = clean_symbol(cfg.benchmark) if cfg.benchmark else ("BTC-USD" if crypto_only else "SPY")
        try:
            bench = self.market.quote(cfg.benchmark).price
        except MarketDataError:
            bench = None
        account_id = create_account(self.db, name, starting_cash)
        fund_id = self.db.execute(
            "INSERT INTO funds(name, account_id, style, config, status, benchmark_symbol, benchmark_start, "
            "created_at, next_cycle_at) VALUES(?,?,?,?,?,?,?,?,?)",
            (name, account_id, style, dumps(cfg.model_dump()), "active", cfg.benchmark, bench, utcnow(),
             utcnow() if run_now else self._next_time(style, cfg, datetime.now(UTC)).isoformat(timespec="seconds")),
        )
        self.fund_broker(self.get(fund_id)).snapshot(force=True, benchmark=bench)
        if run_now:
            self.run_cycle_async(fund_id, trigger="first")
        return self.get(fund_id)

    def update(self, fund_id: int, patch: dict[str, Any]) -> dict[str, Any]:
        fund = self.get(fund_id)
        if "name" in patch:
            name = str(patch.pop("name")).strip()[:60]
            if name:
                self.db.execute("UPDATE funds SET name = ? WHERE id = ?", (name, fund_id))
                self.db.execute("UPDATE account SET name = ? WHERE id = ?", (name, fund["account_id"]))
        if "status" in patch:
            status = patch.pop("status")
            if status not in ("active", "paused"):
                raise FundError("status must be active or paused")
            self.db.execute("UPDATE funds SET status = ? WHERE id = ?", (status, fund_id))
        patch.pop("style", None)  # a fund keeps its style; create a new one to compare styles
        if patch:
            cfg = FundConfig.model_validate({**fund["config"], **patch})
            if fund["style"] != "custom":
                cfg.interval_minutes = STYLES[fund["style"]]["interval_minutes"]
            self.db.execute("UPDATE funds SET config = ? WHERE id = ?", (dumps(cfg.model_dump()), fund_id))
        fund = self.get(fund_id)
        if fund["status"] == "active":
            nxt = self._next_time(fund["style"], FundConfig.model_validate(fund["config"]), datetime.now(UTC))
            self.db.execute("UPDATE funds SET next_cycle_at = ? WHERE id = ?", (nxt.isoformat(timespec="seconds"), fund_id))
        return self.get(fund_id)

    def delete(self, fund_id: int) -> None:
        fund = self.get(fund_id)
        if fund_id in self._busy:
            raise FundError("a cycle is running; try again when it finishes")
        delete_account(self.db, fund["account_id"])
        with self.db.transaction() as conn:
            conn.execute("DELETE FROM fund_cycles WHERE fund_id = ?", (fund_id,))
            conn.execute("DELETE FROM predictions WHERE fund_id = ?", (fund_id,))
            conn.execute("DELETE FROM funds WHERE id = ?", (fund_id,))

    def deposit(self, fund_id: int, amount: float) -> dict[str, Any]:
        self.fund_broker(self.get(fund_id)).deposit(amount)
        return self.summary(fund_id)

    # -- reading -------------------------------------------------------------

    def summary(self, fund_id: int, with_positions: bool = True) -> dict[str, Any]:
        fund = self.get(fund_id)
        acct = self.fund_broker(fund).summary()
        bench_now = None
        if fund["benchmark_symbol"]:
            try:
                bench_now = self.market.quote(fund["benchmark_symbol"]).price
            except MarketDataError:
                bench_now = None
        sells = self.db.query("SELECT realized_pnl FROM trades WHERE account_id = ? AND side = 'sell'",
                              (fund["account_id"],))
        wins = sum(1 for t in sells if (t["realized_pnl"] or 0) > 0)
        curve = self.fund_broker(fund).equity_history()
        peak, max_dd = 0.0, 0.0
        for p in curve:
            peak = max(peak, p["equity"])
            if peak:
                max_dd = max(max_dd, (peak - p["equity"]) / peak * 100)
        cost = self.db.query_one(
            "SELECT COALESCE(SUM(cost_usd), 0) AS c FROM usage_log WHERE (kind = 'fund' AND ref_id = ?) "
            "OR (kind = 'run' AND ref_id IN (SELECT id FROM runs WHERE source = 'fund' AND replay_id = ?))",
            (fund_id, fund_id))["c"]
        cycles = self.db.query_one("SELECT COUNT(*) AS n FROM fund_cycles WHERE fund_id = ? AND status = 'completed'",
                                   (fund_id,))["n"]
        out = {
            **fund,
            "running": fund_id in self._busy,
            "equity": acct["equity"], "cash": acct["cash"], "starting_cash": acct["starting_cash"],
            "total_pnl": acct["total_pnl"], "total_pnl_pct": acct["total_pnl_pct"], "day_pnl": acct["day_pnl"],
            "realized_pnl": acct["realized_pnl"], "commissions_paid": acct["commissions_paid"],
            "trade_count": acct["trade_count"], "closed_trades": len(sells),
            "win_rate_pct": round(wins / len(sells) * 100, 1) if sells else None,
            "max_drawdown_pct": round(max_dd, 2),
            "benchmark_now": bench_now,
            "benchmark_return_pct": _pct(bench_now, fund["benchmark_start"]) if bench_now and fund["benchmark_start"] else None,
            "cycles": cycles, "claude_cost_usd": round(cost, 4),
            "accuracy": self.predictions.stats(fund_id=fund_id),
        }
        if with_positions:
            out["positions"] = acct["positions"]
            out["quote_errors"] = acct["quote_errors"]
        return out

    def list(self) -> list[dict[str, Any]]:
        out = []
        for row in self.db.query("SELECT id FROM funds ORDER BY id DESC"):
            try:
                s = self.summary(row["id"], with_positions=False)
            except (FundError, BrokerError):
                continue
            s["accuracy"] = {k: s["accuracy"][k] for k in ("scored", "open", "avg_accuracy_pct", "direction_rate_pct")}
            out.append(s)
        return out

    def cycles(self, fund_id: int, limit: int = 30) -> list[dict[str, Any]]:
        rows = self.db.query("SELECT * FROM fund_cycles WHERE fund_id = ? ORDER BY id DESC LIMIT ?", (fund_id, limit))
        return [self._decode_cycle(r) for r in rows]

    def cycle(self, cycle_id: int) -> dict[str, Any]:
        row = self.db.query_one("SELECT * FROM fund_cycles WHERE id = ?", (cycle_id,))
        if not row:
            raise FundError("no such cycle")
        return self._decode_cycle(row)

    @staticmethod
    def _decode_cycle(row: dict[str, Any]) -> dict[str, Any]:
        out = dict(row)
        for k, d in (("decisions", []), ("orders", []), ("run_ids", []), ("usage", {})):
            out[k] = loads(row[k], d)
        return out

    # -- scheduling ----------------------------------------------------------

    def _next_time(self, style: str, cfg: FundConfig, now: datetime) -> datetime:
        crypto_only = all(asset_type_of(t) == "crypto" for t in cfg.universe)
        if not cfg.market_hours_only or crypto_only:
            return now + timedelta(minutes=cfg.interval_minutes)
        if style == "swing":
            return next_session_time(now, time(10, 0))
        if style == "position":
            nxt = next_session_time(now, time(10, 0))
            while nxt.astimezone(NY).weekday() != 0 or nxt - now < timedelta(days=1):
                nxt = next_session_time(nxt, time(10, 0))
                if nxt - now > timedelta(days=8):
                    break
            return nxt
        candidate = now + timedelta(minutes=cfg.interval_minutes)
        local_now = now.astimezone(NY)
        if cfg.flatten_at_close and local_now.weekday() < 5:
            flatten = datetime.combine(local_now.date(), FLATTEN_AT, NY).astimezone(UTC)
            if now < flatten < candidate:
                return flatten
        local = candidate.astimezone(NY)
        cutoff = FLATTEN_AT if cfg.flatten_at_close else CLOSE
        if local.weekday() < 5 and OPEN <= local.time() < cutoff:
            return candidate
        if cfg.flatten_at_close and local.weekday() < 5 and cutoff <= local.time() < CLOSE:
            return datetime.combine(local.date(), FLATTEN_AT, NY).astimezone(UTC)
        return next_session_time(candidate, time(9, 45))

    def due(self, now: datetime | None = None) -> list[int]:
        """Start every active fund whose next cycle time has come. Returns the fund IDs started."""
        now = now or datetime.now(UTC)
        rows = self.db.query("SELECT id FROM funds WHERE status = 'active' AND next_cycle_at <= ?",
                             (now.isoformat(timespec="seconds"),))
        started = []
        for r in rows:
            if r["id"] not in self._busy:
                self.run_cycle_async(r["id"], trigger="schedule")
                started.append(r["id"])
        return started

    def snapshot_all(self) -> None:
        for f in self.db.query("SELECT id FROM funds"):
            fund = self.get(f["id"])
            if not self.fund_broker(fund).positions():
                continue
            try:
                bench = self.market.quote(fund["benchmark_symbol"]).price if fund["benchmark_symbol"] else None
            except MarketDataError:
                bench = None
            self.fund_broker(fund).snapshot(benchmark=bench)

    # -- a cycle -------------------------------------------------------------

    def run_cycle_async(self, fund_id: int, trigger: str = "manual") -> None:
        with self._lock:
            if fund_id in self._busy:
                raise FundError("a cycle is already running for this fund")
            self._busy.add(fund_id)
        self.executor.submit(self._safe_cycle, fund_id, trigger)

    def _safe_cycle(self, fund_id: int, trigger: str) -> None:
        try:
            self.run_cycle(fund_id, trigger, _claimed=True)
        except Exception:
            logger.exception("fund %s cycle crashed", fund_id)

    def run_cycle(self, fund_id: int, trigger: str = "manual", _claimed: bool = False,
                  now: datetime | None = None) -> dict[str, Any]:
        if not _claimed:
            with self._lock:
                if fund_id in self._busy:
                    raise FundError("a cycle is already running for this fund")
                self._busy.add(fund_id)
        now = now or datetime.now(UTC)
        fund = self.get(fund_id)
        cfg = FundConfig.model_validate(fund["config"])
        broker = self.fund_broker(fund)
        # Stops and targets that triggered since the last check fill first, so Claude sees the book as it is.
        pre_fills = broker.process_open_orders()
        equity_before = broker.summary()["equity"]
        cycle_id = self.db.execute(
            "INSERT INTO fund_cycles(fund_id, trigger, status, started_at, equity_before) VALUES(?,?,?,?,?)",
            (fund_id, trigger, "running", utcnow(), equity_before))
        result: dict[str, Any] = {}
        status, error = "completed", None
        try:
            crypto_only = all(asset_type_of(t) == "crypto" for t in cfg.universe)
            local = now.astimezone(NY)
            closing = (cfg.flatten_at_close and not crypto_only and local.weekday() < 5
                       and FLATTEN_AT <= local.time() < CLOSE)
            if closing:
                result = self._flatten(fund, broker, cycle_id)
            elif cfg.market_hours_only and not crypto_only and not us_market_open(now) and trigger == "schedule":
                status = "skipped"
                result = {"market_view": "US market closed; nothing to do until the next session."}
            else:
                result = self._allocate_and_trade(fund, cfg, broker, cycle_id, now)
        except (RunError, FundError, BrokerError, MarketDataError, anthropic.APIError) as exc:
            status, error = "failed", _friendly(exc)
        except Exception as exc:
            logger.exception("fund %s cycle failed", fund_id)
            status, error = "failed", f"{type(exc).__name__}: {exc}"
        finally:
            try:
                bench = self.market.quote(fund["benchmark_symbol"]).price if fund["benchmark_symbol"] else None
            except MarketDataError:
                bench = None
            broker.snapshot(force=True, benchmark=bench)
            equity_after = broker.summary()["equity"]
            nxt = self._next_time(fund["style"], cfg, datetime.now(UTC))
            self.db.execute(
                "UPDATE fund_cycles SET status = ?, finished_at = ?, equity_after = ?, market_view = ?, "
                "decisions = ?, orders = ?, run_ids = ?, usage = ?, error = ? WHERE id = ?",
                (status, utcnow(), equity_after, result.get("market_view"), dumps(result.get("decisions", [])),
                 dumps(pre_fills + result.get("orders", [])), dumps(result.get("run_ids", [])), dumps(result.get("usage", {})),
                 error, cycle_id))
            self.db.execute("UPDATE funds SET last_cycle_at = ?, next_cycle_at = ?, last_error = ? WHERE id = ?",
                            (utcnow(), nxt.isoformat(timespec="seconds"), error, fund_id))
            with self._lock:
                self._busy.discard(fund_id)
        return self.cycle(cycle_id)

    def _flatten(self, fund: dict[str, Any], broker: PaperBroker, cycle_id: int) -> dict[str, Any]:
        orders, decisions = [], []
        for p in broker.positions():
            if asset_type_of(p["symbol"]) == "crypto":
                continue  # crypto trades around the clock; only the stock session closes
            o = broker.place_order(p["symbol"], "sell", quantity=p["quantity"], source="fund",
                                   note="day-trading style: flat before the close")
            orders.append(o)
            decisions.append({"ticker": p["symbol"], "action": "sell", "executed": o["status"],
                              "rationale": "Closing before the bell (day-trading rule)."})
        for o in broker.list_orders("open"):
            if asset_type_of(o["symbol"]) != "crypto":
                broker.cancel_order(o["id"], reason="end of session")
        return {"market_view": "End of session: closed the day's positions.", "decisions": decisions,
                "orders": orders}

    # -- inputs for Claude ---------------------------------------------------

    def _ticker_snapshot(self, symbol: str, frames: list[tuple[str, str]], news: bool) -> dict[str, Any]:
        snap: dict[str, Any] = {"ticker": symbol}
        try:
            q = self.market.quote(symbol)
            snap.update(price=q.price, day_chg=q.change_pct, name=q.name, type=q.asset_type)
        except MarketDataError as exc:
            snap["error"] = str(exc)[:120]
            return snap
        for period, interval in frames:
            try:
                snap[f"{interval}"] = frame_features(self.market.history(symbol, period, interval))
            except MarketDataError:
                continue
        if news:
            headlines = getattr(self.market, "headlines", None)
            if headlines:
                try:
                    snap["news"] = headlines(symbol, 3)
                except Exception:
                    snap["news"] = []
        return snap

    def _prompt(self, fund: dict[str, Any], cfg: FundConfig, broker: PaperBroker, snaps: list[dict[str, Any]],
                now: datetime, deep: dict[str, Any] | None = None) -> tuple[str, str]:
        style = STYLES[fund["style"]]
        lo, hi = style["horizon"]
        acct = broker.summary()
        equity = acct["equity"]
        system = (
            f"You are the portfolio manager of \"{fund['name']}\", a paper-trading fund (simulated money) in an app "
            f"that teaches how trading bots behave. You trade as {style['brief']}. The account is long-only cash: "
            "no shorting, no leverage. Every forecast you give is recorded and later scored against the real price "
            "at your stated horizon, so make expected prices and horizons honest and specific, not optimistic. "
            "Prefer doing nothing over trading on weak evidence; transaction costs are real."
        )
        lines = [
            f"Time: {now.astimezone(NY):%Y-%m-%d %H:%M} New York ({now:%H:%M} UTC). "
            f"US market {'open' if us_market_open(now) else 'closed'}.",
            "",
            "## Rules",
            f"- Equity {equity:,.2f}, cash {acct['cash']:,.2f}. Keep at least {cfg.cash_reserve_pct:g}% in cash.",
            f"- At most {cfg.max_positions} positions, each at most {cfg.max_position_pct:g}% of equity.",
            f"- Forecast horizons for this style: {lo:g} to {hi:g} hours.",
            "- target_weight_pct is the weight you want after this cycle. To keep a holding unchanged, repeat its "
            "current weight with action hold.",
            "- Give an entry for every universe ticker and every holding.",
        ]
        if cfg.instructions.strip():
            lines += ["", "## The owner's instructions", cfg.instructions.strip()]
        lines += ["", "## Current holdings"]
        if acct["positions"]:
            for p in acct["positions"]:
                lines.append(f"- {p['symbol']}: {p['quantity']:g} @ avg {p['avg_price']:.4g}, now {p['price']:.4g}, "
                             f"weight {p['weight_pct']:.1f}%, P&L {p['unrealized_pnl_pct']:+.2f}%, "
                             f"held since {p['opened_at'][:16]}")
        else:
            lines.append("- none (all cash)")
        open_preds = self.predictions.list(fund_id=fund["id"], status="open", limit=15, live=False)
        if open_preds:
            lines += ["", "## Your open forecasts"]
            for p in open_preds:
                lines.append(f"- {p['ticker']} {p['direction']} from {p['entry_price']:.4g} to "
                             f"{p['target_price'] or 0:.4g} by {p['due_at'][:16]} UTC")
        stats = self.predictions.stats(fund_id=fund["id"])
        if stats["scored"]:
            lines += ["", "## Your track record (scored forecasts)",
                      f"- {stats['scored']} scored; average accuracy {stats['avg_accuracy_pct']}%, "
                      f"direction right {stats['direction_rate_pct']}%, target hit rate {stats['target_hit_rate_pct']}%."]
            for p in self.predictions.list(fund_id=fund["id"], status="scored", limit=6, live=False):
                lines.append(f"- {p['ticker']}: expected {p['target_price'] or 0:.4g} from {p['entry_price']:.4g}, "
                             f"got {p['price_at_due']:.4g} (accuracy {p['accuracy_pct'] or 0:.0f}%)")
            lines.append("Calibrate: if your targets overshoot, aim closer; if direction is poor, trade less.")
        lines += ["", "## Universe snapshot",
                  "Fields per timeframe: chg_N = % change over N bars, rsi14, vs_smaN = % above/below the N-bar "
                  "average, vol_per_bar = stdev of bar returns %, from_high/from_low = % from the period extreme."]
        for s in snaps:
            if "error" in s:
                lines.append(f"- {s['ticker']}: no data ({s['error']})")
                continue
            head = f"- {s['ticker']} ({s.get('name') or ''}, {s.get('type')}): price {s['price']:.4g}, today {s.get('day_chg') or 0:+.2f}%"
            frames = [f"  [{k}] {_fmt(v)}" for k, v in s.items() if isinstance(v, dict) and v]
            news = [f"  news: {h}" for h in s.get("news") or []]
            lines += [head, *frames, *news]
        if deep:
            lines += ["", "## Second opinions from the full TradingAgents research team"]
            lines += [f"- {t}: {v}" for t, v in deep.items()]
        lines += ["", "Return the allocation."]
        return system, "\n".join(lines)

    def _claude_allocate(self, fund: dict[str, Any], system: str, prompt: str) -> tuple[AllocationPlan, UsageTracker]:
        cfg = FundConfig.model_validate(fund["config"])
        key = self.settings.get_key("anthropic")
        if not key:
            raise FundError("Add your Anthropic API key in Settings first.")
        client = anthropic.Anthropic(api_key=key, max_retries=3)
        extra: dict[str, Any] = {}
        if cfg.model.startswith(("claude-opus-5", "claude-fable-5-1", "claude-sonnet-5-5")):
            extra = {"betas": ["server-side-fallback-2026-07-01"], "fallbacks": "default"}
        output_config = {"effort": cfg.effort} if cfg.effort and not cfg.model.startswith("claude-haiku-4") else {}
        with_config = {"output_config": output_config} if output_config else {}
        response = client.beta.messages.parse(
            model=cfg.model, max_tokens=16000, system=system,
            messages=[{"role": "user", "content": prompt}],
            output_format=AllocationPlan, **with_config, **extra,
        )
        tracker = UsageTracker()
        u = response.usage
        tracker.add(response.model, u.input_tokens or 0, u.output_tokens or 0,
                    getattr(u, "cache_read_input_tokens", 0) or 0, getattr(u, "cache_creation_input_tokens", 0) or 0)
        if response.stop_reason == "refusal":
            raise FundError("Claude declined to produce an allocation this cycle.")
        if response.parsed_output is None:
            raise FundError(f"Claude's allocation could not be read (stop reason {response.stop_reason}).")
        return response.parsed_output, tracker

    # -- deciding and trading --------------------------------------------------

    def _allocate_and_trade(self, fund: dict[str, Any], cfg: FundConfig, broker: PaperBroker, cycle_id: int,
                            now: datetime) -> dict[str, Any]:
        self.runs.preflight(self.settings.get())
        style = STYLES[fund["style"]]
        held = [p["symbol"] for p in broker.positions()]
        symbols = list(dict.fromkeys(cfg.universe + held))
        with ThreadPoolExecutor(max_workers=8) as pool:
            snaps = list(pool.map(lambda s: self._ticker_snapshot(s, style["frames"], cfg.include_news), symbols))
        priced = {s["ticker"]: s["price"] for s in snaps if "price" in s}
        if not priced:
            raise FundError("no prices could be fetched for the universe")

        system, prompt = self._prompt(fund, cfg, broker, snaps, now)
        plan, tracker = self.allocator(fund, system, prompt)
        run_ids: list[int] = []
        if cfg.deep_dive:
            vetoes, run_ids = self._deep_dive(fund, cfg, broker, plan, held)
            for d in plan.decisions:
                if d.ticker.upper() in vetoes:
                    d.rationale += f" [Not bought: the research team rated it {vetoes[d.ticker.upper()]}.]"
                    d.action, d.target_weight_pct = "avoid", 0.0
        tracker.persist(self.db, "fund", fund["id"])
        decisions, orders = self._execute(fund, cfg, broker, plan, priced, cycle_id)
        return {"market_view": plan.market_view, "decisions": decisions, "orders": orders,
                "run_ids": run_ids, "usage": tracker.summary()}

    def _deep_dive(self, fund: dict[str, Any], cfg: FundConfig, broker: PaperBroker, plan: AllocationPlan,
                   held: list[str]) -> tuple[dict[str, str], list[int]]:
        """Run the full agent team on the strongest new buys; return {ticker: rating} for the ones it rejects."""
        candidates = sorted((d for d in plan.decisions if d.action in ("buy", "add") and d.target_weight_pct > 0
                             and d.ticker.upper() not in held), key=lambda d: -d.confidence)[: cfg.deep_dive]
        vetoes, run_ids = {}, []
        for d in candidates:
            try:
                # Fund deep dives reuse the runs table's replay_id column to point at their fund.
                run = self.runs.create_run(d.ticker, today_iso(), auto_execute=False, source="fund",
                                           replay_id=fund["id"], submit=False)
                run = self.runs.execute(run["id"], portfolio=broker.portfolio_context())
            except (RunError, MarketDataError) as exc:
                logger.info("deep dive on %s skipped: %s", d.ticker, exc)
                continue
            run_ids.append(run["id"])
            if run["status"] == "completed" and run["rating"] not in ("Buy", "Overweight"):
                vetoes[d.ticker.upper()] = run["rating"]
        return vetoes, run_ids

    def _execute(self, fund: dict[str, Any], cfg: FundConfig, broker: PaperBroker, plan: AllocationPlan,
                 priced: dict[str, float], cycle_id: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        acct = broker.summary()
        equity = acct["equity"]
        positions = {p["symbol"]: p for p in acct["positions"]}
        style = STYLES[fund["style"]]
        lo, hi = style["horizon"]
        allowed = set(cfg.universe) | set(positions)

        decisions: dict[str, TickerDecision] = {}
        for d in plan.decisions:
            t = d.ticker.strip().upper()
            if t in allowed and t in priced:
                decisions[t] = d

        # Targets in currency, within the position cap.
        targets: dict[str, float] = {}
        for t, d in decisions.items():
            weight = 0.0 if d.action in ("sell", "avoid") else max(0.0, min(d.target_weight_pct, cfg.max_position_pct))
            targets[t] = equity * weight / 100
        for t in positions:
            targets.setdefault(t, positions[t]["market_value"])  # not mentioned: leave it alone
        # At most max_positions holdings, keeping the most confident.
        keep = sorted((t for t, v in targets.items() if v > 0),
                      key=lambda t: -(decisions[t].confidence if t in decisions else 1.0))
        for t in keep[cfg.max_positions:]:
            targets[t] = 0.0
        # Respect the cash reserve by scaling down growth, never forcing extra sales.
        budget = equity * (1 - cfg.cash_reserve_pct / 100)
        total = sum(targets.values())
        if total > budget:
            growth = {t: v - positions.get(t, {}).get("market_value", 0.0) for t, v in targets.items()}
            excess = total - budget
            grow_total = sum(g for g in growth.values() if g > 0)
            if grow_total > 0:
                factor = max(0.0, 1 - excess / grow_total)
                for t, g in growth.items():
                    if g > 0:
                        targets[t] = positions.get(t, {}).get("market_value", 0.0) + g * factor

        min_trade = max(10.0, equity * 0.005)
        out_decisions, orders = [], []
        targets = {t: v for t, v in targets.items() if t in priced}
        sells = [t for t in targets if targets[t] < positions.get(t, {}).get("market_value", 0.0) - min_trade]
        buys = [t for t in targets if targets[t] > positions.get(t, {}).get("market_value", 0.0) + min_trade]
        for t in sells + buys:
            if t not in priced:
                continue  # no live price this cycle: leave the position as it is
            d = decisions.get(t)
            price = priced[t]
            held_value = positions.get(t, {}).get("market_value", 0.0)
            side = "sell" if t in sells else "buy"
            try:
                if side == "sell":
                    qty = positions[t]["quantity"] if targets[t] <= 0 else (held_value - targets[t]) / price
                    qty = min(qty, positions[t]["quantity"])
                else:
                    cash = broker.account()["cash"]
                    qty = min(targets[t] - held_value, max(cash - 1, 0)) / (price * 1.002)
                if qty * price < min_trade / 2:
                    continue
                order = broker.place_order(t, side, quantity=qty, source="fund",
                                           note=(d.rationale if d else "position limit")[:300])
            except BrokerError as exc:
                out_decisions.append({"ticker": t, "action": d.action if d else side, "executed": "error",
                                      "error": str(exc)})
                continue
            orders.append(order)
            if order["status"] == "filled":
                self._after_fill(fund, cfg, broker, t, side, order, d, cycle_id, lo, hi)

        for t, d in decisions.items():
            order = next((o for o in orders if o["symbol"] == t), None)
            if order:
                executed = order["status"]
            elif d.action in ("sell", "trim") and t not in positions:
                executed = "not held"
            else:
                executed = "no trade"
            out_decisions.append({
                **d.model_dump(), "ticker": t, "price": priced.get(t),
                "executed": executed,
                "side": order["side"] if order else None,
                "quantity": order["quantity"] if order else None,
                "fill_price": order["fill_price"] if order else None,
                "expected_move_pct": _pct(d.expected_price, priced[t]) if priced.get(t) else None,
            })
        return out_decisions, orders

    def _after_fill(self, fund: dict[str, Any], cfg: FundConfig, broker: PaperBroker, ticker: str, side: str,
                    order: dict[str, Any], d: TickerDecision | None, cycle_id: int, lo: float, hi: float) -> None:
        price = order["fill_price"]
        if side == "buy":
            for o in broker.list_orders("open"):
                if o["symbol"] == ticker and o["source"] in ("fund-stop", "fund-target"):
                    broker.cancel_order(o["id"], reason="replaced by a newer allocation")
            held = (broker.position(ticker) or {}).get("quantity", 0.0)
            if d and held > 0:
                if cfg.use_stop_loss and d.stop_loss and d.stop_loss < price:
                    self._safe_order(broker, ticker, held, "stop", d.stop_loss, "fund-stop", "stop-loss")
                if cfg.use_take_profit and d.expected_price > price * 1.001:
                    self._safe_order(broker, ticker, held, "limit", d.expected_price, "fund-target",
                                     "take profit at the forecast")
        if d is None or not price:
            return
        expects_up = d.expected_price > price
        if side == "sell" and expects_up:
            return  # trimming a position it still likes: a sizing choice, not a forecast to score
        if side == "buy" and not expects_up:
            return
        horizon = min(max(d.horizon_hours, lo / 2), hi * 2)
        self.predictions.record(
            source="fund", ticker=ticker, direction="up" if expects_up else "down", entry_price=price,
            target_price=d.expected_price, stop_price=d.stop_loss, horizon_hours=horizon,
            horizon_text=f"{horizon:g} hours", confidence=max(0.0, min(1.0, d.confidence)),
            rationale=d.rationale, fund_id=fund["id"], cycle_id=cycle_id,
        )

    @staticmethod
    def _safe_order(broker: PaperBroker, ticker: str, qty: float, kind: str, price: float, source: str,
                    note: str) -> None:
        try:
            broker.place_order(ticker, "sell", quantity=qty, order_type=kind,
                               stop_price=price if kind == "stop" else None,
                               limit_price=price if kind == "limit" else None, source=source, note=note)
        except BrokerError as exc:
            logger.info("protective %s order for %s skipped: %s", kind, ticker, exc)


def _friendly(exc: Exception) -> str:
    if isinstance(exc, anthropic.AuthenticationError):
        return "Anthropic rejected the API key. Check it in Settings."
    if isinstance(exc, anthropic.RateLimitError):
        return "Anthropic rate limit reached; the next cycle will try again."
    if isinstance(exc, anthropic.APIStatusError):
        return f"Anthropic API error {exc.status_code}: {exc.message}"
    if isinstance(exc, anthropic.APIConnectionError):
        return "Could not reach the Anthropic API."
    return str(exc)


def style_catalog() -> dict[str, Any]:
    return {
        "styles": [{"id": k, "label": v["label"], "interval_minutes": v["interval_minutes"],
                    "horizon_hours": list(v["horizon"]), "flatten": v["flatten"], "brief": v["brief"]}
                   for k, v in STYLES.items()],
        "universes": UNIVERSES,
    }
