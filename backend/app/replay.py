"""Strategy replay: let the agents trade a stretch of the past, one decision at a time.

For each date on the grid the full agent team analyses the ticker as of that
day (TradingAgents serves data point-in-time), the decision is sized with your
trading rules against a separate simulated account, and filled at the first
close after the decision date, as TradingAgents' own backtest does. The result
is an equity curve against buy-and-hold over the same days.

Each date is a full analysis, so a replay costs about one run per date. Replays
keep their own memory log, so they never feed lessons into your live runs.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Any

from tradingagents.portfolio import PortfolioContext

from .agents import RunError, RunManager
from .db import Database, dumps, loads, utcnow
from .market import MarketData, MarketDataError, clean_symbol, today_iso
from .policy import plan_order
from .settings_store import SettingsStore

logger = logging.getLogger(__name__)

MAX_STEPS = 20


def grid(start: str, end: str, every_n_days: int) -> list[str]:
    from tradingagents.backtest import iter_grid

    return iter_grid(start, end, every_n_days)


class ReplayService:
    def __init__(self, db: Database, runs: RunManager, market: MarketData, settings: SettingsStore,
                 ta_home: Path):
        self.db = db
        self.runs = runs
        self.market = market
        self.settings = settings
        self.ta_home = ta_home
        self._cancel: dict[int, threading.Event] = {}

    def recover(self) -> None:
        self.db.execute("UPDATE replays SET status = 'failed', error = 'interrupted by a server restart' "
                        "WHERE status IN ('queued', 'running')")

    def _decode(self, row: dict[str, Any] | None) -> dict[str, Any] | None:
        if row is None:
            return None
        out = dict(row)
        out["steps"] = loads(row["steps"], [])
        out["summary"] = loads(row["summary"], None)
        return out

    def get(self, replay_id: int) -> dict[str, Any] | None:
        return self._decode(self.db.query_one("SELECT * FROM replays WHERE id = ?", (replay_id,)))

    def list(self, limit: int = 30) -> list[dict[str, Any]]:
        return [self._decode(r) for r in self.db.query("SELECT * FROM replays ORDER BY id DESC LIMIT ?", (limit,))]

    def create(self, ticker: str, start: str, end: str, every_n_days: int,
               starting_cash: float = 10_000.0) -> dict[str, Any]:
        symbol = clean_symbol(ticker)
        try:
            dates = grid(start, end, every_n_days)
        except ValueError as exc:
            raise RunError(str(exc)) from exc
        if not dates:
            raise RunError("the date range has no analysis dates")
        if dates[-1] >= today_iso():
            raise RunError("replay dates must be before today, so each decision has a next close")
        if len(dates) > MAX_STEPS:
            raise RunError(f"{len(dates)} dates is too many for one replay; keep it to {MAX_STEPS} "
                           "(each date is a full analysis)")
        if not (100 <= starting_cash <= 10_000_000):
            raise RunError("starting cash must be between 100 and 10,000,000")
        self.runs.preflight(self.settings.get())
        replay_id = self.db.execute(
            "INSERT INTO replays(ticker, start_date, end_date, every_n_days, starting_cash, status, created_at) "
            "VALUES(?,?,?,?,?, 'queued', ?)",
            (symbol, start, end, every_n_days, starting_cash, utcnow()))
        self._cancel[replay_id] = threading.Event()
        threading.Thread(target=self._safe_run, args=(replay_id, dates), daemon=True,
                         name=f"replay-{replay_id}").start()
        return self.get(replay_id)

    def cancel(self, replay_id: int) -> dict[str, Any]:
        replay = self.get(replay_id)
        if not replay:
            raise RunError("no such replay")
        if replay["status"] not in ("queued", "running"):
            raise RunError(f"replay is already {replay['status']}")
        self._cancel.setdefault(replay_id, threading.Event()).set()
        active = self.db.query_one("SELECT id FROM runs WHERE replay_id = ? AND status = 'running'", (replay_id,))
        if active:
            self.runs.cancel(active["id"])
        return self.get(replay_id)

    def _safe_run(self, replay_id: int, dates: list[str]) -> None:
        try:
            self._run(replay_id, dates)
        except Exception as exc:
            logger.exception("replay %s crashed", replay_id)
            self.db.execute("UPDATE replays SET status = 'failed', error = ?, finished_at = ? WHERE id = ?",
                            (f"{type(exc).__name__}: {exc}", utcnow(), replay_id))

    def _run(self, replay_id: int, dates: list[str]) -> None:
        replay = self.get(replay_id)
        symbol, cash0 = replay["ticker"], replay["starting_cash"]
        cancel = self._cancel.setdefault(replay_id, threading.Event())
        self.db.execute("UPDATE replays SET status = 'running' WHERE id = ?", (replay_id,))
        try:
            closes = self.market.daily_closes(symbol, dates[0], today_iso())
        except MarketDataError as exc:
            raise RunError(str(exc)) from exc
        if not closes:
            raise RunError(f"no price history for {symbol} over the replay")

        memory_log = self.ta_home / "replays" / str(replay_id) / "trading_memory.md"
        memory_log.parent.mkdir(parents=True, exist_ok=True)
        settings = self.settings.get()
        cash, qty, avg = cash0, 0.0, 0.0
        slip, bps, flat = settings.slippage_bps / 10_000, settings.commission_bps / 10_000, settings.commission_per_trade
        steps: list[dict[str, Any]] = []

        for d in dates:
            if cancel.is_set():
                break
            entry = next(((cd, c) for cd, c in closes if cd > d), None)
            step: dict[str, Any] = {"date": d}
            if entry is None:
                step.update(status="skipped", note="no trading day after this date yet")
                steps.append(step)
                continue
            entry_date, price = entry
            book = PortfolioContext.model_validate({
                "cash": round(cash, 2), "currency": "USD",
                "positions": [{"ticker": symbol, "quantity": qty, "average_price": round(avg, 4)}] if qty else [],
            })
            try:
                run = self.runs.create_run(symbol, d, auto_execute=False, source="replay",
                                           replay_id=replay_id, submit=False)
            except RunError as exc:
                step.update(status="failed", note=str(exc))
                steps.append(step)
                break  # budget or key problems will not fix themselves mid-replay
            run = self.runs.execute(run["id"], memory_log_path=memory_log, portfolio=book)
            step["run_id"] = run["id"]
            if run["status"] != "completed":
                step.update(status=run["status"], note=run.get("error"))
                steps.append(step)
                self._save(replay_id, steps)
                if run["status"] == "cancelled":
                    break
                continue

            proposal = run["proposal"] or {}
            equity = cash + qty * price
            plan = plan_order(run["rating"] or "REVIEW", price, equity, cash, qty, settings,
                              trader=proposal.get("trader"), decision=proposal.get("decision"),
                              fractional=True)
            if plan.action == "buy":
                fill = price * (1 + slip)
                fee = flat + plan.quantity * fill * bps
                avg = (qty * avg + plan.quantity * fill) / (qty + plan.quantity)
                qty += plan.quantity
                cash -= plan.quantity * fill + fee
            elif plan.action == "sell":
                fill = price * (1 - slip)
                fee = flat + plan.quantity * fill * bps
                qty -= plan.quantity
                cash += plan.quantity * fill - fee
                if qty <= 1e-9:
                    qty, avg = 0.0, 0.0
            step.update(status="completed", rating=run["rating"], action=plan.action,
                        quantity=plan.quantity, fill_date=entry_date, price=price,
                        cash=cash, position=qty, equity=cash + qty * price, reason=plan.reason,
                        cost_usd=(run["usage"] or {}).get("cost_usd"))
            steps.append(step)
            self._save(replay_id, steps)

        summary = self._summarize(symbol, cash0, cash, qty, steps, closes)
        status = "cancelled" if cancel.is_set() else "completed"
        self.db.execute("UPDATE replays SET status = ?, steps = ?, summary = ?, finished_at = ? WHERE id = ?",
                        (status, dumps(steps), dumps(summary), utcnow(), replay_id))
        self._cancel.pop(replay_id, None)

    def _save(self, replay_id: int, steps: list[dict[str, Any]]) -> None:
        self.db.execute("UPDATE replays SET steps = ? WHERE id = ?", (dumps(steps), replay_id))

    @staticmethod
    def _summarize(symbol: str, cash0: float, cash: float, qty: float, steps: list[dict[str, Any]],
                   closes: list[tuple[str, float]]) -> dict[str, Any]:
        done = [s for s in steps if s.get("status") == "completed"]
        last_date, last_close = closes[-1]
        final_equity = cash + qty * last_close
        summary: dict[str, Any] = {
            "final_equity": final_equity, "return_pct": (final_equity - cash0) / cash0 * 100,
            "marked_at": last_date, "final_price": last_close, "decisions": len(done),
            "trades": sum(1 for s in done if s.get("action") in ("buy", "sell")),
            "ratings": {r: sum(1 for s in done if s.get("rating") == r)
                        for r in ("Buy", "Overweight", "Hold", "Underweight", "Sell", "REVIEW")},
            "cost_usd": round(sum(s.get("cost_usd") or 0 for s in done), 4),
        }
        if not done:
            summary.update(curve=[], buy_hold_return_pct=None, max_drawdown_pct=None)
            return summary

        # Daily equity path from the first fill: hold each step's position until the next.
        first_fill = done[0]["fill_date"]
        fills = {s["fill_date"]: s for s in done}
        bh_price = next(c for d, c in closes if d >= first_fill)
        bh_units = cash0 / bh_price
        c_cash, c_qty, peak, max_dd, curve = cash0, 0.0, cash0, 0.0, []
        for d, close in closes:
            if d < first_fill:
                continue
            if d in fills:
                c_cash, c_qty = fills[d]["cash"], fills[d]["position"]
            eq = c_cash + c_qty * close
            peak = max(peak, eq)
            max_dd = max(max_dd, (peak - eq) / peak * 100 if peak else 0.0)
            curve.append({"date": d, "equity": round(eq, 2), "buy_hold": round(bh_units * close, 2)})
        summary.update(
            curve=curve,
            buy_hold_return_pct=(bh_units * last_close - cash0) / cash0 * 100,
            max_drawdown_pct=max_dd,
            first_fill=first_fill,
        )
        return summary
