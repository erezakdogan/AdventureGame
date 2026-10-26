"""Fakes for the network edges: Yahoo prices and the TradingAgents graph.

The fake graph streams the same shapes the real one does (analyst reports from
their own steps, then full top-level states), so the run manager is exercised
end to end without spending tokens.
"""

from __future__ import annotations

import time
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, LLMResult

from app.main import build_services, create_app
from app.market import Bar, MarketDataError, Quote, asset_type_of, clean_symbol

TOKEN = "test-token"


class FakeMarket:
    def __init__(self):
        self.prices = {"AAPL": 200.0, "NVDA": 100.0, "BTC-USD": 50_000.0}
        self.closes: dict[str, list[tuple[str, float]]] = {}

    def quote(self, symbol: str) -> Quote:
        symbol = clean_symbol(symbol)
        if symbol not in self.prices:
            raise MarketDataError(f"no price data for {symbol}")
        p = self.prices[symbol]
        return Quote(symbol, p, p * 0.99, p * 0.01, 1.0, "USD", f"{symbol} Inc", asset_type_of(symbol), time.time())

    def history(self, symbol, period="6mo", interval="1d"):
        p = self.quote(symbol).price
        return [Bar(t=f"2026-01-{d:02d}", o=p, h=p, l=p, c=p, v=1) for d in range(1, 6)]

    def daily_closes(self, symbol, start, end):
        return [(d, c) for d, c in self.closes.get(clean_symbol(symbol), []) if start <= d <= end]


def decision_text(rating: str, target: float | None = 260.0) -> str:
    return (f"**Rating**: {rating}\n\n**Executive Summary**: Build the position gradually.\n\n"
            f"**Investment Thesis**: Strong demand.\n\n**Price Target**: {target or 'not provided'}\n\n"
            "**Time Horizon**: 3-6 months")


def trader_text(action: str = "Buy", stop: float | None = 180.0) -> str:
    return (f"**Action**: {action}\n\n**Reasoning**: Momentum.\n\n**Entry Price**: 199.5\n\n"
            f"**Stop Loss**: {stop if stop else 'not provided'}\n\n**Position Sizing**: 5% of portfolio\n\n"
            f"FINAL TRANSACTION PROPOSAL: **{action.upper()}**")


class FakeGraph:
    ratings: list[str] = ["Buy"]
    seen_portfolios: list = []

    def __init__(self, analysts, config, callbacks):
        self.analysts, self.config, self.callbacks = analysts, config, callbacks
        self.propagator = SimpleNamespace(get_graph_args=lambda: {"config": {}})
        self.recorded = None

    def create_run_state(self, ticker, date, asset_type, portfolio):
        FakeGraph.seen_portfolios.append(portfolio)
        return {"company_of_interest": ticker, "trade_date": date}

    def _usage(self):
        msg = AIMessage(content="x", usage_metadata={"input_tokens": 1000, "output_tokens": 200,
                                                     "total_tokens": 1200},
                        response_metadata={"model_name": "claude-opus-5-5"})
        for cb in self.callbacks:
            cb.on_llm_end(LLMResult(generations=[[ChatGeneration(message=msg)]]))

    def stream_run(self, init, **args):
        rating = FakeGraph.ratings.pop(0) if len(FakeGraph.ratings) > 1 else FakeGraph.ratings[0]
        empty = {"market_report": "", "sentiment_report": "", "news_report": "", "fundamentals_report": "",
                 "investment_plan": "", "trader_investment_plan": "", "final_trade_decision": "",
                 "investment_debate_state": {"bull_history": "", "bear_history": ""},
                 "risk_debate_state": {"aggressive_history": "", "conservative_history": "",
                                       "neutral_history": ""}}
        yield [AIMessage(content="", id="m0")], {**init, **empty}
        call = AIMessage(content="", id="m1",
                         tool_calls=[{"name": "get_stock_data", "args": {"symbol": "X"}, "id": "c1"}])
        yield [call], None
        for key in ("market_report", "sentiment_report", "news_report", "fundamentals_report"):
            self._usage()
            yield [], {key: f"{key} body"}
        state = {**init, **empty, "market_report": "m", "sentiment_report": "s", "news_report": "n",
                 "fundamentals_report": "f",
                 "investment_debate_state": {"bull_history": "bull", "bear_history": "bear"},
                 "investment_plan": "**Recommendation**: Buy"}
        yield [], state
        state = {**state, "trader_investment_plan": trader_text()}
        yield [], state
        state = {**state, "risk_debate_state": {"aggressive_history": "a", "conservative_history": "c",
                                                "neutral_history": "n"},
                 "final_trade_decision": decision_text(rating), "final_rating": rating}
        self._usage()
        yield [], state

    def record_decision(self, ticker, date, state):
        self.recorded = (ticker, date, state.get("final_rating"))


@pytest.fixture()
def market():
    return FakeMarket()


@pytest.fixture()
def services(tmp_path, market, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    FakeGraph.ratings = ["Buy"]
    FakeGraph.seen_portfolios = []
    s = build_services(tmp_path, market=market, graph_factory=FakeGraph, start_background=False, token=TOKEN)
    yield s
    s.runs.shutdown()
    s.db.close()


@pytest.fixture()
def client(services):
    app = create_app(lambda: services)
    with TestClient(app) as c:
        c.headers["Authorization"] = f"Bearer {TOKEN}"
        yield c


def wait_for(fn, timeout=10.0):
    end = time.time() + timeout
    while time.time() < end:
        value = fn()
        if value:
            return value
        time.sleep(0.05)
    raise AssertionError("condition not met in time")
