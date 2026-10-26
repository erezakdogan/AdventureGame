"""Market data for the paper broker and the charts: quotes and price history.

Yahoo Finance (through yfinance, which TradingAgents already depends on) serves
every market TradingAgents covers. Quotes are cached briefly so a screen that
polls, plus the order checker, do not hammer Yahoo.
"""

from __future__ import annotations

import logging
import math
import threading
import time
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from typing import Protocol

from tradingagents.dataflows.symbols import crypto_base, normalize_symbol

logger = logging.getLogger(__name__)


class MarketDataError(RuntimeError):
    """A quote or history could not be fetched; the message is shown to the user."""


@dataclass
class Quote:
    symbol: str
    price: float
    previous_close: float | None
    change: float | None
    change_pct: float | None
    currency: str | None
    name: str | None
    asset_type: str
    ts: float

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Bar:
    t: str  # ISO date or datetime
    o: float
    h: float
    l: float  # noqa: E741 - OHLC field names
    c: float
    v: float


def clean_symbol(raw: str) -> str:
    symbol = normalize_symbol(raw or "")
    if not symbol or len(symbol) > 24:
        raise MarketDataError(f"not a valid ticker: {raw!r}")
    return symbol


def asset_type_of(symbol: str) -> str:
    return "crypto" if crypto_base(symbol) else "stock"


class MarketData(Protocol):
    def quote(self, symbol: str) -> Quote: ...

    def history(self, symbol: str, period: str = "6mo", interval: str = "1d") -> list[Bar]: ...

    def daily_closes(self, symbol: str, start: str, end: str) -> list[tuple[str, float]]: ...


_PERIODS = {"1d", "5d", "1mo", "3mo", "6mo", "1y", "2y", "5y", "ytd", "max"}
_INTERVALS = {"5m", "15m", "30m", "60m", "1h", "1d", "1wk", "1mo"}


def _finite(value) -> float | None:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


class YahooMarketData:
    def __init__(self, quote_ttl: float = 20.0):
        self.quote_ttl = quote_ttl
        self._quotes: dict[str, Quote] = {}
        self._names: dict[str, str | None] = {}
        self._lock = threading.Lock()

    def _ticker(self, symbol: str):
        import yfinance as yf

        return yf.Ticker(symbol)

    def quote(self, symbol: str) -> Quote:
        symbol = clean_symbol(symbol)
        with self._lock:
            cached = self._quotes.get(symbol)
        if cached and time.time() - cached.ts < self.quote_ttl:
            return cached
        try:
            t = self._ticker(symbol)
            info = t.fast_info
            price = _finite(info.get("last_price"))
            prev = _finite(info.get("previous_close"))
            currency = info.get("currency")
            if price is None:
                hist = t.history(period="5d", interval="1d")
                if hist.empty:
                    raise MarketDataError(f"no price data for {symbol}")
                price = float(hist["Close"].iloc[-1])
                if prev is None and len(hist) > 1:
                    prev = float(hist["Close"].iloc[-2])
        except MarketDataError:
            raise
        except Exception as exc:  # yfinance raises many shapes
            logger.warning("quote %s failed: %s", symbol, exc)
            if cached:
                return cached  # stale beats nothing for a portfolio screen
            raise MarketDataError(f"could not fetch a quote for {symbol}: {exc}") from exc

        name = self._names.get(symbol)
        if symbol not in self._names:
            try:
                info_full = t.get_info() or {}
                name = info_full.get("shortName") or info_full.get("longName")
            except Exception:
                name = None
            self._names[symbol] = name

        change = price - prev if prev else None
        quote = Quote(
            symbol=symbol, price=price, previous_close=prev, change=change,
            change_pct=(change / prev * 100) if change is not None and prev else None,
            currency=currency, name=name, asset_type=asset_type_of(symbol), ts=time.time(),
        )
        with self._lock:
            self._quotes[symbol] = quote
        return quote

    def history(self, symbol: str, period: str = "6mo", interval: str = "1d") -> list[Bar]:
        symbol = clean_symbol(symbol)
        if period not in _PERIODS or interval not in _INTERVALS:
            raise MarketDataError("unsupported period or interval")
        try:
            df = self._ticker(symbol).history(period=period, interval=interval, auto_adjust=False)
        except Exception as exc:
            raise MarketDataError(f"could not fetch history for {symbol}: {exc}") from exc
        if df.empty:
            raise MarketDataError(f"no history for {symbol}")
        intraday = interval not in ("1d", "1wk", "1mo")
        bars = []
        for ts, row in df.iterrows():
            close = _finite(row.get("Close"))
            if close is None:
                continue
            bars.append(Bar(
                t=ts.isoformat() if intraday else ts.strftime("%Y-%m-%d"),
                o=_finite(row.get("Open")) or close, h=_finite(row.get("High")) or close,
                l=_finite(row.get("Low")) or close, c=close, v=_finite(row.get("Volume")) or 0.0,
            ))
        return bars

    def daily_closes(self, symbol: str, start: str, end: str) -> list[tuple[str, float]]:
        """Daily closes from ``start`` through ``end`` inclusive."""
        symbol = clean_symbol(symbol)
        end_excl = (date.fromisoformat(end) + timedelta(days=1)).isoformat()
        try:
            df = self._ticker(symbol).history(start=start, end=end_excl, interval="1d", auto_adjust=False)
        except Exception as exc:
            raise MarketDataError(f"could not fetch history for {symbol}: {exc}") from exc
        out = []
        for ts, row in df.iterrows():
            close = _finite(row.get("Close"))
            if close is not None:
                out.append((ts.strftime("%Y-%m-%d"), close))
        return out


def today_iso() -> str:
    return datetime.now().date().isoformat()
