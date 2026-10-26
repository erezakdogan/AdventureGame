"""HTTP API for the mobile app.

Every route except /api/health needs ``Authorization: Bearer <token>``; the
token is printed when the server starts (see config.load_access_token).
"""

from __future__ import annotations

import hmac
import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import tradingagents
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, ValidationError

from . import config
from .agents import RunError, RunManager
from .broker import BrokerError, PaperBroker
from .chat import ChatService, test_key
from .db import Database, utcnow
from .fund import FundError, FundService, style_catalog
from .market import MarketData, MarketDataError, YahooMarketData, clean_symbol
from .predictions import PredictionService
from .replay import MAX_STEPS, ReplayService
from .scheduler import Scheduler
from .settings_store import KEY_ENV, SettingsStore
from .usage import MODEL_CATALOG, PRESETS, usage_report

logger = logging.getLogger("papertrader")


@dataclass
class Services:
    db: Database
    settings: SettingsStore
    market: MarketData
    broker: PaperBroker
    runs: RunManager
    chat: ChatService
    replays: ReplayService
    scheduler: Scheduler
    token: str
    predictions: PredictionService
    funds: FundService


def build_services(data_dir: Path | None = None, market: MarketData | None = None, graph_factory=None,
                   start_background: bool = True, token: str | None = None, allocator=None) -> Services:
    data_dir = Path(data_dir) if data_dir else config.DATA_DIR
    data_dir.mkdir(parents=True, exist_ok=True)
    ta_home = data_dir / "tradingagents"
    db = Database(data_dir / "papertrader.sqlite3")
    settings = SettingsStore(db, data_dir / "secrets.json")
    market = market or YahooMarketData()
    broker = PaperBroker(db, market, settings)
    runs = RunManager(db, broker, settings, market, ta_home, graph_factory=graph_factory)
    runs.recover()
    predictions = PredictionService(db, market)
    runs.predictions = predictions
    replays = ReplayService(db, runs, market, settings, ta_home)
    replays.recover()
    funds = FundService(db, broker, market, settings, runs, predictions, allocator=allocator)
    funds.recover()
    scheduler = Scheduler(broker, runs, settings, predictions, funds)
    if start_background:
        scheduler.start()
    return Services(db, settings, market, broker, runs, ChatService(db, runs, settings), replays,
                    scheduler, token or config.load_access_token(), predictions, funds)


# -- request bodies ---------------------------------------------------------


class KeyBody(BaseModel):
    name: Literal["anthropic", "fred", "alpha_vantage"] = "anthropic"
    value: str | None = Field(default=None, max_length=400)


class ResetBody(BaseModel):
    starting_cash: float = 100_000.0


class OrderBody(BaseModel):
    symbol: str
    side: Literal["buy", "sell"]
    quantity: float | None = Field(default=None, gt=0)
    notional: float | None = Field(default=None, gt=0)
    order_type: Literal["market", "limit", "stop"] = "market"
    limit_price: float | None = Field(default=None, gt=0)
    stop_price: float | None = Field(default=None, gt=0)
    note: str | None = Field(default=None, max_length=300)


class SymbolBody(BaseModel):
    symbol: str


class RunBody(BaseModel):
    ticker: str
    trade_date: str | None = None
    auto_execute: bool | None = None
    deep_model: str | None = None
    quick_model: str | None = None
    effort: str | None = None
    analysts: list[str] | None = None
    max_debate_rounds: int | None = None
    max_risk_rounds: int | None = None
    output_language: str | None = None
    share_portfolio: bool | None = None


class ExecuteBody(BaseModel):
    quantity: float | None = Field(default=None, gt=0)


class ChatBody(BaseModel):
    question: str


class FundBody(BaseModel):
    name: str = Field(default="AI Fund", max_length=60)
    starting_cash: float = Field(default=10_000.0, ge=100, le=100_000_000)
    run_now: bool = True
    config: dict[str, Any] = Field(default_factory=dict)


class AmountBody(BaseModel):
    amount: float = Field(gt=0, le=100_000_000)


class ReplayBody(BaseModel):
    ticker: str
    start_date: str
    end_date: str
    every_n_days: int = Field(default=7, ge=1, le=90)
    starting_cash: float = 10_000.0


def create_app(services_factory=build_services) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        services = services_factory()
        app.state.services = services
        if services_factory is build_services:
            logger.warning("PaperTrader API ready. Access token: %s", services.token)
        yield
        services.scheduler.stop()
        services.runs.shutdown()
        services.funds.shutdown()

    app = FastAPI(title="TradingAgents Paper Trader", version=config.APP_VERSION, lifespan=lifespan)
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

    @app.exception_handler(BrokerError)
    @app.exception_handler(FundError)
    @app.exception_handler(RunError)
    @app.exception_handler(MarketDataError)
    async def _user_error(_: Request, exc: Exception):
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    @app.exception_handler(ValidationError)
    async def _validation_error(_: Request, exc: ValidationError):
        msgs = "; ".join(f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors())
        return JSONResponse(status_code=400, content={"detail": msgs})

    def svc(request: Request) -> Services:
        return request.app.state.services

    def auth(request: Request, authorization: str | None = Header(default=None)) -> Services:
        services = svc(request)
        supplied = (authorization or "").removeprefix("Bearer ").strip()
        if not supplied or not hmac.compare_digest(supplied, services.token):
            raise HTTPException(status_code=401, detail="missing or wrong access token")
        return services

    S = Depends(auth)

    # -- health & settings --------------------------------------------------

    @app.get("/api/health")
    def health(request: Request) -> dict[str, Any]:
        return {"ok": True, "app_version": config.APP_VERSION,
                "tradingagents_version": tradingagents.__version__, "time": utcnow()}

    @app.get("/api/session")
    def session(s: Services = S) -> dict[str, Any]:
        return {"ok": True, "keys": s.settings.key_status(), "settings": s.settings.get().model_dump()}

    @app.get("/api/settings")
    def get_settings(s: Services = S) -> dict[str, Any]:
        return {"settings": s.settings.get().model_dump(), "keys": s.settings.key_status(),
                "autopilot_message": s.scheduler.last_autopilot_message}

    @app.patch("/api/settings")
    def patch_settings(patch: dict[str, Any], s: Services = S) -> dict[str, Any]:
        return {"settings": s.settings.update(patch).model_dump(), "keys": s.settings.key_status()}


    @app.put("/api/settings/keys")
    def put_key(body: KeyBody, s: Services = S) -> dict[str, Any]:
        value = (body.value or "").strip() or None
        if body.name == "anthropic" and value and not value.startswith("sk-ant-"):
            raise HTTPException(status_code=400, detail="Anthropic API keys start with sk-ant-")
        s.settings.set_key(body.name, value)
        return {"keys": s.settings.key_status()}

    @app.post("/api/settings/keys/test")
    async def check_key(s: Services = S) -> dict[str, Any]:
        key = s.settings.get_key("anthropic")
        if not key:
            return {"ok": False, "message": "No Anthropic API key is saved yet."}
        return await run_in_threadpool(test_key, key, s.settings.get().deep_model)

    @app.get("/api/models")
    def models(_: Services = S) -> dict[str, Any]:
        return {
            "models": [{"id": m, "input_per_mtok": p[0], "output_per_mtok": p[1], "description": p[2]}
                       for m, p in MODEL_CATALOG.items()],
            "presets": PRESETS,
            "efforts": ["low", "medium", "high", "xhigh", "max"],
            "key_names": list(KEY_ENV),
        }

    @app.get("/api/usage")
    def usage(s: Services = S) -> dict[str, Any]:
        report = usage_report(s.db)
        report["monthly_budget_usd"] = s.settings.get().monthly_budget_usd
        return report

    # -- account ------------------------------------------------------------

    @app.get("/api/account")
    async def account(s: Services = S) -> dict[str, Any]:
        return await run_in_threadpool(s.broker.summary)


    @app.post("/api/account/reset")
    async def reset(body: ResetBody, s: Services = S) -> dict[str, Any]:
        await run_in_threadpool(s.broker.reset, body.starting_cash)
        return await run_in_threadpool(s.broker.summary)

    @app.get("/api/account/equity")
    def equity(days: int | None = Query(default=None, ge=1, le=3650), s: Services = S):
        return {"points": s.broker.equity_history(days)}

    # -- orders -------------------------------------------------------------


    @app.get("/api/orders")
    def orders(status: str | None = None, limit: int = Query(default=200, le=1000), s: Services = S):
        return {"orders": s.broker.list_orders(status, limit)}

    @app.post("/api/orders")
    async def place(body: OrderBody, s: Services = S) -> dict[str, Any]:
        return await run_in_threadpool(lambda: s.broker.place_order(**body.model_dump(), source="manual"))

    @app.delete("/api/orders/{order_id}")
    def cancel_order(order_id: int, s: Services = S) -> dict[str, Any]:
        return s.broker.cancel_order(order_id)

    @app.get("/api/trades")
    def trades(symbol: str | None = None, limit: int = Query(default=200, le=1000), s: Services = S):
        return {"trades": s.broker.list_trades(limit, symbol)}

    # -- market data --------------------------------------------------------

    @app.get("/api/market/quote/{symbol}")
    async def quote(symbol: str, s: Services = S) -> dict[str, Any]:
        return (await run_in_threadpool(s.market.quote, symbol)).to_dict()

    @app.get("/api/market/quotes")
    async def quotes(symbols: str, s: Services = S) -> dict[str, Any]:
        out, errors = [], {}
        for sym in [x for x in symbols.split(",") if x.strip()][:40]:
            try:
                out.append((await run_in_threadpool(s.market.quote, sym)).to_dict())
            except MarketDataError as exc:
                errors[sym] = str(exc)
        return {"quotes": out, "errors": errors}

    @app.get("/api/market/history/{symbol}")
    async def history(symbol: str, period: str = "6mo", interval: str = "1d", s: Services = S):
        bars = await run_in_threadpool(s.market.history, symbol, period, interval)
        return {"symbol": clean_symbol(symbol), "bars": [b.__dict__ for b in bars]}

    # -- watchlist ----------------------------------------------------------

    @app.get("/api/watchlist")
    def watchlist(s: Services = S):
        return {"symbols": [r["symbol"] for r in s.db.query("SELECT symbol FROM watchlist ORDER BY added_at")]}


    @app.post("/api/watchlist")
    async def add_watch(body: SymbolBody, s: Services = S):
        q = await run_in_threadpool(s.market.quote, body.symbol)  # proves the symbol exists
        s.db.execute("INSERT OR IGNORE INTO watchlist(symbol, added_at) VALUES(?, ?)", (q.symbol, utcnow()))
        return watchlist(s)

    @app.delete("/api/watchlist/{symbol}")
    def remove_watch(symbol: str, s: Services = S):
        s.db.execute("DELETE FROM watchlist WHERE symbol = ?", (clean_symbol(symbol),))
        return watchlist(s)

    # -- agent runs ---------------------------------------------------------


    @app.post("/api/runs")
    async def start_run(body: RunBody, s: Services = S) -> dict[str, Any]:
        overrides = body.model_dump(exclude={"ticker", "trade_date", "auto_execute"}, exclude_none=True)
        # Validates the symbol against live data before spending tokens.
        await run_in_threadpool(s.market.quote, body.ticker)
        return s.runs.create_run(body.ticker, body.trade_date, body.auto_execute, "manual", overrides)

    @app.get("/api/runs")
    def list_runs(limit: int = Query(default=50, le=500), ticker: str | None = None, s: Services = S):
        return {"runs": s.runs.list_runs(limit, ticker)}

    @app.get("/api/runs/{run_id}")
    def get_run(run_id: int, s: Services = S) -> dict[str, Any]:
        run = s.runs.get_run(run_id)
        if not run:
            raise HTTPException(status_code=404, detail="no such run")
        return run

    @app.get("/api/runs/{run_id}/events")
    def run_events(run_id: int, after: int = 0, s: Services = S):
        return {"events": s.runs.events(run_id, after)}

    @app.post("/api/runs/{run_id}/cancel")
    def cancel_run(run_id: int, s: Services = S):
        return s.runs.cancel(run_id)

    @app.delete("/api/runs/{run_id}")
    def delete_run(run_id: int, s: Services = S):
        s.runs.delete_run(run_id)
        return {"ok": True}


    @app.post("/api/runs/{run_id}/plan")
    async def refresh_plan(run_id: int, s: Services = S):
        """The decision re-sized against the account and price as they are now."""
        from .trading import current_plan

        run = s.runs.get_run(run_id)
        if not run or run["status"] != "completed":
            raise HTTPException(status_code=400, detail="the run has not finished")
        p = run["proposal"] or {}
        plan = await run_in_threadpool(current_plan, s.broker, s.settings.get(), run["ticker"],
                                       run["rating"] or "REVIEW", p.get("trader"), p.get("decision"))
        return plan.to_dict()

    @app.post("/api/runs/{run_id}/execute")
    async def execute(run_id: int, body: ExecuteBody, s: Services = S):
        orders = await run_in_threadpool(s.runs.execute_proposal, run_id, body.quantity)
        return {"orders": orders, "run": s.runs.get_run(run_id)}


    @app.get("/api/runs/{run_id}/chat")
    def chat_history(run_id: int, s: Services = S):
        return {"messages": s.chat.history(run_id)}

    @app.post("/api/runs/{run_id}/chat")
    async def chat(run_id: int, body: ChatBody, s: Services = S):
        return await run_in_threadpool(s.chat.ask, run_id, body.question)

    # -- track record ------------------------------------------------------

    @app.get("/api/predictions")
    async def predictions(source: str | None = None, fund_id: int | None = None, ticker: str | None = None,
                          status: str | None = None, run_id: int | None = None,
                          limit: int = Query(default=100, le=500), s: Services = S):
        rows = await run_in_threadpool(lambda: s.predictions.list(source, fund_id, ticker, status, limit,
                                                                  run_id=run_id))
        return {"predictions": rows}

    @app.get("/api/predictions/stats")
    def prediction_stats(source: str | None = None, fund_id: int | None = None, ticker: str | None = None,
                         s: Services = S):
        return s.predictions.stats(source, fund_id, ticker)

    @app.post("/api/predictions/evaluate")
    async def evaluate_predictions(s: Services = S):
        return {"scored": await run_in_threadpool(s.predictions.evaluate_due)}

    # -- AI funds ------------------------------------------------------------

    @app.get("/api/funds/catalog")
    def fund_catalog(_: Services = S):
        return style_catalog()

    @app.get("/api/funds")
    async def list_funds(s: Services = S):
        return {"funds": await run_in_threadpool(s.funds.list)}

    @app.post("/api/funds")
    async def create_fund(body: FundBody, s: Services = S):
        if body.run_now:
            s.runs.preflight(s.settings.get())
        return await run_in_threadpool(s.funds.create, body.name, body.starting_cash, body.config, body.run_now)

    @app.get("/api/funds/{fund_id}")
    async def get_fund(fund_id: int, s: Services = S):
        return await run_in_threadpool(s.funds.summary, fund_id)

    @app.patch("/api/funds/{fund_id}")
    def update_fund(fund_id: int, patch: dict[str, Any], s: Services = S):
        return s.funds.update(fund_id, patch)

    @app.delete("/api/funds/{fund_id}")
    def delete_fund(fund_id: int, s: Services = S):
        s.funds.delete(fund_id)
        return {"ok": True}

    @app.post("/api/funds/{fund_id}/cycle")
    def run_fund_cycle(fund_id: int, s: Services = S):
        s.funds.get(fund_id)
        s.runs.preflight(s.settings.get())
        s.funds.run_cycle_async(fund_id, trigger="manual")
        return {"ok": True}

    @app.post("/api/funds/{fund_id}/deposit")
    async def deposit(fund_id: int, body: AmountBody, s: Services = S):
        return await run_in_threadpool(s.funds.deposit, fund_id, body.amount)

    @app.get("/api/funds/{fund_id}/cycles")
    def fund_cycles(fund_id: int, limit: int = Query(default=30, le=200), s: Services = S):
        return {"cycles": s.funds.cycles(fund_id, limit)}

    @app.get("/api/fund-cycles/{cycle_id}")
    def fund_cycle(cycle_id: int, s: Services = S):
        return s.funds.cycle(cycle_id)

    @app.get("/api/funds/{fund_id}/equity")
    def fund_equity(fund_id: int, days: int | None = Query(default=None, ge=1, le=3650), s: Services = S):
        fund = s.funds.get(fund_id)
        return {"points": s.funds.fund_broker(fund).equity_history(days), "benchmark_start": fund["benchmark_start"],
                "benchmark_symbol": fund["benchmark_symbol"]}

    @app.get("/api/funds/{fund_id}/trades")
    def fund_trades(fund_id: int, limit: int = Query(default=200, le=1000), s: Services = S):
        return {"trades": s.funds.fund_broker(s.funds.get(fund_id)).list_trades(limit)}

    @app.get("/api/funds/{fund_id}/orders")
    def fund_orders(fund_id: int, status: str | None = None, s: Services = S):
        return {"orders": s.funds.fund_broker(s.funds.get(fund_id)).list_orders(status)}

    @app.delete("/api/funds/{fund_id}/orders/{order_id}")
    def cancel_fund_order(fund_id: int, order_id: int, s: Services = S):
        return s.funds.fund_broker(s.funds.get(fund_id)).cancel_order(order_id)

    # -- replays ------------------------------------------------------------


    @app.post("/api/replays")
    async def start_replay(body: ReplayBody, s: Services = S):
        await run_in_threadpool(s.market.quote, body.ticker)
        return s.replays.create(body.ticker, body.start_date, body.end_date, body.every_n_days,
                                body.starting_cash)

    @app.get("/api/replays")
    def list_replays(s: Services = S):
        return {"replays": s.replays.list(), "max_steps": MAX_STEPS}

    @app.get("/api/replays/{replay_id}")
    def get_replay(replay_id: int, s: Services = S):
        r = s.replays.get(replay_id)
        if not r:
            raise HTTPException(status_code=404, detail="no such replay")
        return r

    @app.post("/api/replays/{replay_id}/cancel")
    def cancel_replay(replay_id: int, s: Services = S):
        return s.replays.cancel(replay_id)

    return app


app = create_app()
