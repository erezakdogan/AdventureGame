"""Running TradingAgents on Claude in the background, with live progress.

A run streams the TradingAgents graph exactly as its own CLI does
(``create_run_state`` -> ``stream_run`` -> ``record_decision``), so the memory
log, reflections and saved state behave the same. Along the way it records
which agent is working, the tools the analysts call, every report as it lands,
and the tokens spent, so the phone can show the firm at work.
"""

from __future__ import annotations

import logging
import os
import threading
import traceback
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path
from typing import Any

from .broker import BrokerError, PaperBroker
from .db import Database, dumps, loads, utcnow
from .market import MarketData, MarketDataError, asset_type_of, clean_symbol, today_iso
from .policy import parse_decision, parse_trader
from .settings_store import Settings, SettingsStore
from .trading import current_plan, execute_plan
from .usage import UsageTracker, month_spend

logger = logging.getLogger(__name__)

ANALYSTS = {
    "market": ("Market Analyst", "market_report"),
    "social": ("Sentiment Analyst", "sentiment_report"),
    "news": ("News Analyst", "news_report"),
    "fundamentals": ("Fundamentals Analyst", "fundamentals_report"),
}
TEAMS = {
    "Market Analyst": "Analyst Team", "Sentiment Analyst": "Analyst Team",
    "News Analyst": "Analyst Team", "Fundamentals Analyst": "Analyst Team",
    "Bull Researcher": "Research Team", "Bear Researcher": "Research Team",
    "Research Manager": "Research Team", "Trader": "Trading Team",
    "Aggressive Analyst": "Risk Management", "Conservative Analyst": "Risk Management",
    "Neutral Analyst": "Risk Management", "Portfolio Manager": "Portfolio Management",
}
LATER_AGENTS = ["Bull Researcher", "Bear Researcher", "Research Manager", "Trader",
                "Aggressive Analyst", "Conservative Analyst", "Neutral Analyst", "Portfolio Manager"]

# Report sections kept per run, in reading order.
REPORT_ORDER = [
    "market_report", "sentiment_report", "news_report", "fundamentals_report",
    "bull_history", "bear_history", "investment_plan", "trader_investment_plan",
    "aggressive_history", "conservative_history", "neutral_history", "final_trade_decision",
]

RUN_OPTION_KEYS = ("deep_model", "quick_model", "effort", "analysts", "max_debate_rounds",
                   "max_risk_rounds", "output_language", "share_portfolio")


class RunError(ValueError):
    """A run that cannot start; the message is shown to the user."""


class RunCancelled(Exception):
    pass


def _tool_agents() -> dict[str, str]:
    try:
        from tradingagents.graph.analyst_execution import ANALYST_NODE_SPECS
    except ImportError:
        return {}
    out = {}
    for spec in ANALYST_NODE_SPECS.values():
        for tool in spec.tools:
            name = getattr(tool, "name", None)
            if name:
                out[name] = spec.agent_node
    return out


TOOL_AGENTS = _tool_agents()


def default_graph_factory(analysts: list[str], config: dict, callbacks: list):
    from tradingagents.graph.trading_graph import TradingAgentsGraph

    return TradingAgentsGraph(selected_analysts=analysts, config=config, callbacks=callbacks)


def build_config(opts: dict[str, Any], ta_home: Path, memory_log_path: Path | None = None) -> dict:
    """A TradingAgents config that runs every agent on Claude with this run's options."""
    from tradingagents.default_config import build_default_config

    config = build_default_config()
    config.update({
        "llm_provider": "anthropic",
        "deep_think_provider": None, "quick_think_provider": None,
        "backend_url": None, "deep_think_backend_url": None, "quick_think_backend_url": None,
        "deep_think_llm": opts["deep_model"],
        "quick_think_llm": opts["quick_model"],
        "anthropic_effort": opts.get("effort"),
        # Current Claude models reject sampling parameters.
        "temperature": None,
        "output_language": opts.get("output_language") or "English",
        "max_debate_rounds": int(opts["max_debate_rounds"]),
        "max_risk_discuss_rounds": int(opts["max_risk_rounds"]),
        "llm_max_retries": 4,
        "checkpoint_enabled": False,
        "results_dir": str(ta_home / "logs"),
        "data_cache_dir": str(ta_home / "cache"),
        "memory_log_path": str(memory_log_path or ta_home / "memory" / "trading_memory.md"),
    })
    return config


def _short(value: Any, limit: int = 160) -> str:
    text = value if isinstance(value, str) else dumps(value)
    return text if len(text) <= limit else text[: limit - 1] + "…"


def friendly_error(exc: Exception) -> str:
    """A run failure in words the user can act on."""
    text = str(exc)
    name = type(exc).__name__
    if "authentication_error" in text or "invalid x-api-key" in text:
        return "Anthropic rejected the API key. Check it in Settings → API key."
    if "permission_error" in text:
        return "Your Anthropic key is not allowed to use this model. Pick another model in Settings."
    if "not_found_error" in text and "model" in text:
        return "The selected Claude model was not found. Pick another model in Settings."
    if "rate_limit" in text or name.endswith("RateLimitError"):
        return "Anthropic rate limit reached. Wait a minute, or lower 'parallel runs' and debate rounds."
    if "credit balance" in text.lower() or "billing" in text.lower():
        return "Your Anthropic account is out of credit. Add credit in the Anthropic Console."
    if "overloaded" in text:
        return "Claude is overloaded right now. Try again shortly."
    return f"{name}: {text[:500]}"


class RunManager:
    def __init__(self, db: Database, broker: PaperBroker, settings: SettingsStore, market: MarketData,
                 ta_home: Path, graph_factory: Callable | None = None):
        self.db = db
        self.broker = broker
        self.settings = settings
        self.market = market
        self.ta_home = ta_home
        self.graph_factory = graph_factory or default_graph_factory
        self.predictions = None  # PredictionService, wired in by build_services
        self._cancel: dict[int, threading.Event] = {}
        self.executor = ThreadPoolExecutor(max_workers=settings.get().max_concurrent_runs,
                                           thread_name_prefix="agents")

    def recover(self) -> None:
        """Runs a restart interrupted cannot resume; say so instead of spinning forever."""
        self.db.execute(
            "UPDATE runs SET status = 'failed', error = 'interrupted by a server restart', finished_at = ? "
            "WHERE status IN ('queued', 'running')", (utcnow(),))

    def shutdown(self) -> None:
        for ev in self._cancel.values():
            ev.set()
        self.executor.shutdown(wait=False, cancel_futures=True)

    # -- creating runs ------------------------------------------------------

    def preflight(self, settings: Settings) -> None:
        if not self.settings.get_key("anthropic"):
            raise RunError("Add your Anthropic API key in Settings before running the agents.")
        budget = settings.monthly_budget_usd
        if budget:
            spent = month_spend(self.db)
            if spent >= budget:
                raise RunError(f"This month's estimated spend ${spent:.2f} reached your ${budget:.2f} "
                               "budget. Raise it in Settings to keep running.")

    def create_run(self, ticker: str, trade_date: str | None = None, auto_execute: bool | None = None,
                   source: str = "manual", overrides: dict[str, Any] | None = None,
                   replay_id: int | None = None, submit: bool = True) -> dict[str, Any]:
        settings = self.settings.get()
        self.preflight(settings)
        symbol = clean_symbol(ticker)
        trade_date = trade_date or today_iso()
        try:
            parsed = date.fromisoformat(trade_date)
        except ValueError as exc:
            raise RunError("date must be YYYY-MM-DD") from exc
        if parsed.isoformat() > today_iso():
            raise RunError("the analysis date cannot be in the future")

        opts = {k: getattr(settings, k) for k in RUN_OPTION_KEYS}
        for k, v in (overrides or {}).items():
            if k in RUN_OPTION_KEYS and v is not None:
                opts[k] = v
        # Validate the overrides the same way saved settings are validated.
        opts = {k: getattr(Settings.model_validate({**settings.model_dump(), **opts}), k)
                for k in RUN_OPTION_KEYS}
        if auto_execute is None:
            auto_execute = settings.auto_execute

        run_id = self.db.execute(
            "INSERT INTO runs(ticker, trade_date, asset_type, status, source, replay_id, auto_execute, "
            "options, agents, created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (symbol, parsed.isoformat(), asset_type_of(symbol), "queued", source, replay_id,
             int(bool(auto_execute)), dumps(opts), dumps(self._initial_agents(opts["analysts"])), utcnow()),
        )
        self._cancel[run_id] = threading.Event()
        self._event(run_id, None, "status", f"Queued analysis of {symbol} for {parsed.isoformat()}")
        if submit:
            self.executor.submit(self._safe_execute, run_id)
        return self.get_run(run_id)

    @staticmethod
    def _initial_agents(analysts: list[str]) -> dict[str, str]:
        agents = {ANALYSTS[a][0]: "pending" for a in ANALYSTS if a in analysts}
        agents.update(dict.fromkeys(LATER_AGENTS, "pending"))
        return agents

    # -- reading runs -------------------------------------------------------

    def _decode(self, row: dict[str, Any] | None, full: bool = True) -> dict[str, Any] | None:
        if row is None:
            return None
        out = dict(row)
        for key, default in (("options", {}), ("agents", {}), ("reports", {}), ("proposal", None),
                             ("executed_order_ids", []), ("usage", {})):
            out[key] = loads(row.get(key), default)
        out["auto_execute"] = bool(row["auto_execute"])
        agents = out["agents"]
        done = sum(1 for s in agents.values() if s == "completed")
        out["progress"] = round(done / len(agents), 3) if agents else 0.0
        out["teams"] = TEAMS
        if not full:
            out.pop("reports", None)
            out["decision"] = (row.get("decision") or "")[:400]
        return out

    def get_run(self, run_id: int) -> dict[str, Any] | None:
        return self._decode(self.db.query_one("SELECT * FROM runs WHERE id = ?", (run_id,)))

    def list_runs(self, limit: int = 50, ticker: str | None = None,
                  include_replays: bool = False) -> list[dict[str, Any]]:
        where, params = [], []
        if ticker:
            where.append("ticker = ?")
            params.append(clean_symbol(ticker))
        if not include_replays:
            where.append("source NOT IN ('replay', 'fund')")
        sql = "SELECT * FROM runs" + (" WHERE " + " AND ".join(where) if where else "")
        rows = self.db.query(sql + " ORDER BY id DESC LIMIT ?", (*params, limit))
        return [self._decode(r, full=False) for r in rows]

    def events(self, run_id: int, after_id: int = 0, limit: int = 500) -> list[dict[str, Any]]:
        return self.db.query(
            "SELECT * FROM run_events WHERE run_id = ? AND id > ? ORDER BY id LIMIT ?",
            (run_id, after_id, limit))

    def delete_run(self, run_id: int) -> None:
        run = self.get_run(run_id)
        if not run:
            raise RunError("no such run")
        if run["status"] in ("queued", "running"):
            raise RunError("cancel the run before deleting it")
        with self.db.transaction() as conn:
            conn.execute("DELETE FROM run_events WHERE run_id = ?", (run_id,))
            conn.execute("DELETE FROM chat_messages WHERE run_id = ?", (run_id,))
            conn.execute("DELETE FROM runs WHERE id = ?", (run_id,))
            conn.execute("DELETE FROM predictions WHERE run_id = ? AND status = 'open'", (run_id,))

    def cancel(self, run_id: int) -> dict[str, Any]:
        run = self.get_run(run_id)
        if not run:
            raise RunError("no such run")
        if run["status"] not in ("queued", "running"):
            raise RunError(f"run is already {run['status']}")
        self._cancel.setdefault(run_id, threading.Event()).set()
        if run["status"] == "queued":
            self._finish(run_id, "cancelled", error="cancelled before it started")
        else:
            self._event(run_id, None, "status", "Cancelling after the current step…")
        return self.get_run(run_id)

    # -- executing ----------------------------------------------------------

    def _event(self, run_id: int, agent: str | None, kind: str, text: str) -> None:
        self.db.execute("INSERT INTO run_events(run_id, ts, agent, kind, text) VALUES(?,?,?,?,?)",
                        (run_id, utcnow(), agent, kind, text))

    def _finish(self, run_id: int, status: str, **fields: Any) -> None:
        sets = ["status = ?", "finished_at = ?"]
        params: list[Any] = [status, utcnow()]
        for k, v in fields.items():
            sets.append(f"{k} = ?")
            params.append(v if isinstance(v, (str, int, float)) or v is None else dumps(v))
        self.db.execute(f"UPDATE runs SET {', '.join(sets)} WHERE id = ?", (*params, run_id))

    def _safe_execute(self, run_id: int) -> None:
        try:
            self.execute(run_id)
        except Exception:  # the thread must never die silently
            logger.exception("run %s crashed", run_id)

    def execute(self, run_id: int, memory_log_path: Path | None = None,
                portfolio: Any = "account") -> dict[str, Any]:
        """Run the agents for ``run_id`` in this thread and return the finished run.

        ``portfolio`` is the book shown to the agents: the paper account by
        default, None for none, or a PortfolioContext (replays pass their own).
        """
        run = self.get_run(run_id)
        if run is None or run["status"] != "queued":
            return run
        cancel = self._cancel.setdefault(run_id, threading.Event())
        if cancel.is_set():
            return run
        opts = run["options"]
        self.db.execute("UPDATE runs SET status = 'running', started_at = ? WHERE id = ?", (utcnow(), run_id))
        self._event(run_id, None, "status",
                    f"Starting: {opts['quick_model']} for the analysts, {opts['deep_model']} for the managers")
        tracker = UsageTracker()
        try:
            if not os.environ.get("ANTHROPIC_API_KEY"):
                raise RunError("no Anthropic API key is set")
            config = build_config(opts, self.ta_home, memory_log_path)
            graph = self.graph_factory(list(opts["analysts"]), config, [tracker])
            if portfolio == "account":
                book = self.broker.portfolio_context() if opts.get("share_portfolio") else None
            else:
                book = portfolio
            state = self._stream(run_id, run, graph, book, cancel)

            try:
                graph.record_decision(run["ticker"], run["trade_date"], state)
            except Exception as exc:
                logger.warning("record_decision failed for run %s: %s", run_id, exc)
                self._event(run_id, None, "warning", f"Could not write the memory log: {exc}")

            from tradingagents.agents.rating import run_rating

            rating = run_rating(state)
            decision = state.get("final_trade_decision") or ""
            trader = parse_trader(state.get("trader_investment_plan") or "")
            pm = parse_decision(decision)
            proposal = {"rating": rating, "trader": trader, "decision": pm,
                        "memory_note": state.get("memory_note") or None}
            if run["source"] not in ("replay", "fund"):
                proposal["plan"] = self._plan(run["ticker"], rating, trader, pm)
            usage = tracker.summary()
            self._finish(run_id, "completed", rating=rating, decision=decision, proposal=proposal, usage=usage)
            # A fund's deep-dive analyses feed its own trades, which record their own forecasts.
            if self.predictions is not None and run["source"] != "fund":
                try:
                    pred_id = self.predictions.record_from_run(self.get_run(run_id), proposal)
                    if pred_id:
                        self._event(run_id, "Portfolio Manager", "status",
                                    "Forecast recorded in the track record; it is scored when its horizon ends")
                except Exception as exc:  # the forecast log must never fail a finished run
                    logger.warning("could not record prediction for run %s: %s", run_id, exc)
            self._event(run_id, "Portfolio Manager", "decision",
                        f"Final rating: {rating} (≈${usage['cost_usd']:.2f} in Claude usage)")

            if run["auto_execute"] and run["source"] not in ("replay", "fund"):
                if run["trade_date"] == today_iso():
                    self._auto_execute(run_id)
                else:
                    self._event(run_id, None, "warning",
                                "Not auto-executed: the analysis date is in the past.")
        except RunCancelled:
            self._finish(run_id, "cancelled", error="cancelled by user", usage=tracker.summary())
            self._event(run_id, None, "status", "Run cancelled")
        except Exception as exc:
            logger.warning("run %s failed: %s\n%s", run_id, exc, traceback.format_exc())
            message = friendly_error(exc)
            self._finish(run_id, "failed", error=message, usage=tracker.summary())
            self._event(run_id, None, "error", message)
        finally:
            tracker.persist(self.db, "run", run_id)
            self._cancel.pop(run_id, None)
        return self.get_run(run_id)

    def _stream(self, run_id: int, run: dict[str, Any], graph: Any, book: Any,
                cancel: threading.Event) -> dict[str, Any]:
        init = graph.create_run_state(run["ticker"], run["trade_date"], run["asset_type"], book)
        args = graph.propagator.get_graph_args()
        agents = dict(run["agents"])
        for name in agents:
            if TEAMS[name] == "Analyst Team":
                agents[name] = "in_progress"
        self.db.execute("UPDATE runs SET agents = ? WHERE id = ?", (dumps(agents), run_id))
        state: dict[str, Any] = {}
        seen: set = set()
        reports: dict[str, str] = {}

        for messages, chunk in graph.stream_run(init, **args):
            if cancel.is_set():
                raise RunCancelled()
            for msg in messages or []:
                key = getattr(msg, "id", None) or id(msg)
                if key in seen:
                    continue
                seen.add(key)
                for call in getattr(msg, "tool_calls", None) or []:
                    name = call.get("name") if isinstance(call, dict) else getattr(call, "name", "")
                    cargs = call.get("args") if isinstance(call, dict) else getattr(call, "args", {})
                    self._event(run_id, TOOL_AGENTS.get(name), "tool", f"{name}({_short(cargs, 120)})")
            if not chunk:
                continue
            for k, v in chunk.items():
                if k == "messages":
                    continue
                if v or k not in state:
                    state[k] = v
            new_agents = self._agent_status(state, agents)
            new_reports = self._reports(state)
            if new_agents != agents or new_reports != reports:
                for name, status in new_agents.items():
                    if status != agents.get(name) and status == "completed":
                        self._event(run_id, name, "agent", f"{name} finished")
                    elif status != agents.get(name) and status == "in_progress":
                        self._event(run_id, name, "agent", f"{name} is working")
                agents, reports = new_agents, new_reports
                self.db.execute("UPDATE runs SET agents = ?, reports = ? WHERE id = ?",
                                (dumps(agents), dumps(reports), run_id))
        if not state.get("final_trade_decision"):
            raise RuntimeError("the graph ended without a final decision")
        return state

    @staticmethod
    def _reports(state: dict[str, Any]) -> dict[str, str]:
        debate = state.get("investment_debate_state") or {}
        risk = state.get("risk_debate_state") or {}
        flat = {
            **{k: state.get(k) for k in ("market_report", "sentiment_report", "news_report",
                                         "fundamentals_report", "investment_plan",
                                         "trader_investment_plan", "final_trade_decision")},
            "bull_history": debate.get("bull_history"), "bear_history": debate.get("bear_history"),
            "aggressive_history": risk.get("aggressive_history"),
            "conservative_history": risk.get("conservative_history"),
            "neutral_history": risk.get("neutral_history"),
        }
        return {k: flat[k].strip() for k in REPORT_ORDER if isinstance(flat.get(k), str) and flat[k].strip()}

    @staticmethod
    def _agent_status(state: dict[str, Any], agents: dict[str, str]) -> dict[str, str]:
        out = dict(agents)
        analysts_done = True
        for name, report_key in ANALYSTS.values():
            if name not in out:
                continue
            if state.get(report_key):
                out[name] = "completed"
            else:
                out[name] = "in_progress"
                analysts_done = False
        debate = state.get("investment_debate_state") or {}
        risk = state.get("risk_debate_state") or {}
        plan = state.get("investment_plan")
        trader = state.get("trader_investment_plan")
        final = state.get("final_trade_decision")

        def mark(name: str, done: bool, started: bool) -> None:
            out[name] = "completed" if done else ("in_progress" if started else "pending")

        debated = bool(debate.get("bull_history")) and bool(debate.get("bear_history"))
        mark("Bull Researcher", bool(plan) or debated, analysts_done)
        mark("Bear Researcher", bool(plan) or debated, analysts_done)
        mark("Research Manager", bool(plan), debated)
        mark("Trader", bool(trader), bool(plan))
        for name, key in (("Aggressive Analyst", "aggressive_history"),
                          ("Conservative Analyst", "conservative_history"),
                          ("Neutral Analyst", "neutral_history")):
            mark(name, bool(final) or bool(risk.get(key)), bool(trader))
        mark("Portfolio Manager", bool(final),
             all(risk.get(k) for k in ("aggressive_history", "conservative_history", "neutral_history")))
        return out

    # -- decisions to orders ------------------------------------------------

    def _plan(self, ticker: str, rating: str, trader: dict, pm: dict) -> dict[str, Any] | None:
        try:
            return current_plan(self.broker, self.settings.get(), ticker, rating, trader, pm).to_dict()
        except MarketDataError as exc:
            return {"action": "none", "rating": rating, "quantity": 0, "reason": f"no quote: {exc}",
                    "notes": [], "reference_price": None, "estimated_value": 0,
                    "stop_loss": None, "take_profit": None}

    def _auto_execute(self, run_id: int) -> None:
        try:
            orders = self.execute_proposal(run_id, source="autopilot")
            if orders:
                o = orders[0]
                self._event(run_id, "Trader", "trade",
                            f"Auto-executed: {o['side']} {o['quantity']:g} {o['symbol']} → {o['status']}")
            else:
                self._event(run_id, "Trader", "trade", "Auto-execute: no order needed")
        except (BrokerError, MarketDataError, RunError) as exc:
            self._event(run_id, "Trader", "warning", f"Auto-execute failed: {exc}")

    def execute_proposal(self, run_id: int, quantity: float | None = None,
                         source: str = "agent") -> list[dict[str, Any]]:
        """Size the run's decision against the account as it is now, and trade it."""
        run = self.get_run(run_id)
        if not run:
            raise RunError("no such run")
        if run["status"] != "completed":
            raise RunError("the run has not finished")
        if run["executed_order_ids"]:
            raise RunError("this decision was already executed")
        proposal = run["proposal"] or {}
        plan = current_plan(self.broker, self.settings.get(), run["ticker"], run["rating"] or "REVIEW",
                            proposal.get("trader"), proposal.get("decision"))
        if quantity is not None:
            if plan.action == "none":
                raise RunError(f"nothing to execute: {plan.reason}")
            plan.quantity = quantity
        orders = execute_plan(self.broker, run["ticker"], plan, run_id, source=source)
        proposal["plan"] = plan.to_dict()
        # A plan with nothing to trade is not marked executed, so it can be retried
        # once the account or the price has moved.
        self.db.execute("UPDATE runs SET executed_order_ids = ?, proposal = ? WHERE id = ?",
                        (dumps([o["id"] for o in orders]) if orders else None, dumps(proposal), run_id))
        return orders
