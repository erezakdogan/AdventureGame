"""The paper broker: a simulated cash account that fills orders at live prices.

Long-only by design (no margin, no shorting): a Sell rating closes or trims a
position, it never opens a short. Market orders fill at the last price plus
slippage; limit and stop orders wait and are checked by the scheduler. Every
fill pays the configured commission, so results resemble a real account rather
than frictionless theory.
"""

from __future__ import annotations

import logging
import math
from datetime import UTC, datetime, timedelta
from typing import Any

from tradingagents.portfolio import PortfolioContext

from .db import Database, utcnow
from .market import MarketData, MarketDataError, asset_type_of, clean_symbol
from .settings_store import SettingsStore

logger = logging.getLogger(__name__)

DEFAULT_STARTING_CASH = 100_000.0
EPS = 1e-9
SIDES = ("buy", "sell")
ORDER_TYPES = ("market", "limit", "stop")
SNAPSHOT_EVERY = timedelta(minutes=15)


class BrokerError(ValueError):
    """An order the broker refuses; the message is shown to the user."""


def _round_qty(qty: float) -> float:
    return math.floor(qty * 1e6 + 1e-6) / 1e6


class PaperBroker:
    def __init__(self, db: Database, market: MarketData, settings: SettingsStore):
        self.db = db
        self.market = market
        self.settings = settings
        if not self.db.query_one("SELECT id FROM account WHERE id = 1"):
            self.db.execute(
                "INSERT INTO account(id, starting_cash, cash, created_at) VALUES(1, ?, ?, ?)",
                (DEFAULT_STARTING_CASH, DEFAULT_STARTING_CASH, utcnow()),
            )

    # -- account ------------------------------------------------------------

    def account(self) -> dict[str, Any]:
        return self.db.query_one("SELECT * FROM account WHERE id = 1")

    def reset(self, starting_cash: float) -> None:
        if not (100 <= starting_cash <= 100_000_000):
            raise BrokerError("starting cash must be between 100 and 100,000,000")
        with self.db.transaction() as conn:
            for table in ("positions", "orders", "trades", "equity_snapshots"):
                conn.execute(f"DELETE FROM {table}")
            conn.execute(
                "UPDATE account SET starting_cash = ?, cash = ?, created_at = ? WHERE id = 1",
                (starting_cash, starting_cash, utcnow()),
            )
        self.snapshot(force=True)

    def positions(self) -> list[dict[str, Any]]:
        return self.db.query("SELECT * FROM positions ORDER BY symbol")

    def position(self, symbol: str) -> dict[str, Any] | None:
        return self.db.query_one("SELECT * FROM positions WHERE symbol = ?", (symbol,))

    def summary(self) -> dict[str, Any]:
        """Cash, equity and every position valued at the latest quote."""
        acct = self.account()
        rows, errors = [], []
        market_value = day_pnl = 0.0
        for p in self.positions():
            price, prev, name, stale = p["avg_price"], None, None, True
            try:
                q = self.market.quote(p["symbol"])
                price, prev, name, stale = q.price, q.previous_close, q.name, False
            except MarketDataError as exc:
                errors.append(str(exc))
            value = p["quantity"] * price
            cost = p["quantity"] * p["avg_price"]
            market_value += value
            if prev:
                day_pnl += p["quantity"] * (price - prev)
            rows.append({
                "symbol": p["symbol"], "name": name, "quantity": p["quantity"],
                "avg_price": p["avg_price"], "price": price, "previous_close": prev,
                "market_value": value, "cost_basis": cost,
                "unrealized_pnl": value - cost,
                "unrealized_pnl_pct": (value - cost) / cost * 100 if cost else 0.0,
                "day_change_pct": (price - prev) / prev * 100 if prev else None,
                "asset_type": asset_type_of(p["symbol"]), "stale": stale,
                "opened_at": p["opened_at"],
            })
        equity = acct["cash"] + market_value
        for r in rows:
            r["weight_pct"] = r["market_value"] / equity * 100 if equity else 0.0
        realized = self.db.query_one("SELECT COALESCE(SUM(realized_pnl), 0) AS r FROM trades")["r"]
        commissions = self.db.query_one("SELECT COALESCE(SUM(commission), 0) AS c FROM trades")["c"]
        start = acct["starting_cash"]
        return {
            "cash": acct["cash"], "starting_cash": start, "currency": acct["currency"],
            "equity": equity, "market_value": market_value,
            "total_pnl": equity - start, "total_pnl_pct": (equity - start) / start * 100 if start else 0.0,
            "day_pnl": day_pnl, "realized_pnl": realized, "commissions_paid": commissions,
            "positions": rows, "quote_errors": errors, "created_at": acct["created_at"],
        }

    def portfolio_context(self) -> PortfolioContext:
        acct = self.account()
        return PortfolioContext.model_validate({
            "cash": round(acct["cash"], 2),
            "currency": acct["currency"],
            "positions": [
                {"ticker": p["symbol"], "quantity": p["quantity"], "average_price": round(p["avg_price"], 4)}
                for p in self.positions()
            ],
        })

    # -- orders -------------------------------------------------------------

    def place_order(
        self,
        symbol: str,
        side: str,
        quantity: float | None = None,
        notional: float | None = None,
        order_type: str = "market",
        limit_price: float | None = None,
        stop_price: float | None = None,
        source: str = "manual",
        run_id: int | None = None,
        note: str | None = None,
    ) -> dict[str, Any]:
        symbol = clean_symbol(symbol)
        side, order_type = side.lower(), order_type.lower()
        if side not in SIDES:
            raise BrokerError("side must be buy or sell")
        if order_type not in ORDER_TYPES:
            raise BrokerError("order type must be market, limit or stop")
        if order_type == "limit" and not (limit_price and limit_price > 0):
            raise BrokerError("a limit order needs a positive limit price")
        if order_type == "stop" and not (stop_price and stop_price > 0):
            raise BrokerError("a stop order needs a positive stop price")
        if (quantity is None) == (notional is None):
            raise BrokerError("give either a quantity or a dollar amount")

        quote = self.market.quote(symbol)  # also proves the symbol exists
        if notional is not None:
            if notional <= 0:
                raise BrokerError("amount must be positive")
            ref = limit_price if order_type == "limit" else quote.price
            quantity = notional / ref
        quantity = self._normalize_qty(symbol, quantity)

        if side == "sell":
            held = (self.position(symbol) or {}).get("quantity", 0.0)
            if quantity > held + EPS:
                raise BrokerError(
                    f"you hold {held:g} {symbol}; this paper account does not sell short"
                )

        now = utcnow()
        order_id = self.db.execute(
            "INSERT INTO orders(symbol, side, quantity, order_type, limit_price, stop_price, status, "
            "source, run_id, note, created_at, updated_at) VALUES(?,?,?,?,?,?, 'open', ?,?,?,?,?)",
            (symbol, side, quantity, order_type, limit_price, stop_price, source, run_id, note, now, now),
        )
        self._try_fill(order_id, quote.price)
        return self.order(order_id)

    def _normalize_qty(self, symbol: str, quantity: float | None) -> float:
        if quantity is None or not math.isfinite(quantity) or quantity <= 0:
            raise BrokerError("quantity must be positive")
        if asset_type_of(symbol) == "stock" and not self.settings.get().allow_fractional:
            quantity = math.floor(quantity + 1e-9)
        else:
            quantity = _round_qty(quantity)
        if quantity <= 0:
            raise BrokerError("quantity rounds to zero; fractional shares are off in settings")
        return quantity

    def order(self, order_id: int) -> dict[str, Any] | None:
        return self.db.query_one("SELECT * FROM orders WHERE id = ?", (order_id,))

    def list_orders(self, status: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
        if status:
            return self.db.query("SELECT * FROM orders WHERE status = ? ORDER BY id DESC LIMIT ?", (status, limit))
        return self.db.query("SELECT * FROM orders ORDER BY id DESC LIMIT ?", (limit,))

    def list_trades(self, limit: int = 200, symbol: str | None = None) -> list[dict[str, Any]]:
        if symbol:
            return self.db.query("SELECT * FROM trades WHERE symbol = ? ORDER BY id DESC LIMIT ?",
                                 (clean_symbol(symbol), limit))
        return self.db.query("SELECT * FROM trades ORDER BY id DESC LIMIT ?", (limit,))

    def cancel_order(self, order_id: int, reason: str = "cancelled by user") -> dict[str, Any]:
        order = self.order(order_id)
        if not order:
            raise BrokerError("no such order")
        if order["status"] != "open":
            raise BrokerError(f"order is already {order['status']}")
        self.db.execute(
            "UPDATE orders SET status = 'cancelled', reject_reason = ?, updated_at = ? WHERE id = ?",
            (reason, utcnow(), order_id),
        )
        return self.order(order_id)

    def process_open_orders(self) -> list[dict[str, Any]]:
        """Check every waiting limit/stop order against its latest quote."""
        filled = []
        for order in self.list_orders("open"):
            try:
                price = self.market.quote(order["symbol"]).price
            except MarketDataError as exc:
                logger.info("skipping order %s: %s", order["id"], exc)
                continue
            if self._try_fill(order["id"], price):
                filled.append(self.order(order["id"]))
        return filled

    def _triggered(self, order: dict[str, Any], price: float) -> bool:
        kind, side = order["order_type"], order["side"]
        if kind == "market":
            return True
        if kind == "limit":
            return price <= order["limit_price"] if side == "buy" else price >= order["limit_price"]
        return price >= order["stop_price"] if side == "buy" else price <= order["stop_price"]

    def _try_fill(self, order_id: int, price: float) -> bool:
        """Fill the order at ``price`` if it is open and triggered. Returns True on a fill."""
        cfg = self.settings.get()
        with self.db.transaction() as conn:
            order = dict(conn.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone())
            if order["status"] != "open" or not self._triggered(order, price):
                return False

            slip = cfg.slippage_bps / 10_000
            side, qty, symbol = order["side"], order["quantity"], order["symbol"]
            fill = price * (1 + slip) if side == "buy" else price * (1 - slip)
            if order["order_type"] == "limit":
                fill = min(fill, order["limit_price"]) if side == "buy" else max(fill, order["limit_price"])
            notional = qty * fill
            commission = cfg.commission_per_trade + notional * cfg.commission_bps / 10_000

            cash = conn.execute("SELECT cash FROM account WHERE id = 1").fetchone()["cash"]
            pos = conn.execute("SELECT * FROM positions WHERE symbol = ?", (symbol,)).fetchone()
            held = pos["quantity"] if pos else 0.0
            now = utcnow()

            def reject(reason: str) -> bool:
                conn.execute(
                    "UPDATE orders SET status = 'rejected', reject_reason = ?, updated_at = ? WHERE id = ?",
                    (reason, now, order_id),
                )
                return False

            realized = None
            if side == "buy":
                if notional + commission > cash + EPS:
                    return reject(f"insufficient cash: needs {notional + commission:,.2f}, have {cash:,.2f}")
                new_qty = held + qty
                avg = ((held * pos["avg_price"]) if pos else 0.0) + qty * fill
                avg /= new_qty
                if pos:
                    conn.execute("UPDATE positions SET quantity = ?, avg_price = ?, updated_at = ? WHERE symbol = ?",
                                 (new_qty, avg, now, symbol))
                else:
                    conn.execute("INSERT INTO positions(symbol, quantity, avg_price, opened_at, updated_at) "
                                 "VALUES(?,?,?,?,?)", (symbol, new_qty, avg, now, now))
                conn.execute("UPDATE account SET cash = cash - ? WHERE id = 1", (notional + commission,))
            else:
                if qty > held + EPS:
                    return reject(f"position is {held:g}, cannot sell {qty:g} (no short selling)")
                qty = min(qty, held)
                realized = (fill - pos["avg_price"]) * qty - commission
                remaining = held - qty
                if remaining <= 1e-6:
                    conn.execute("DELETE FROM positions WHERE symbol = ?", (symbol,))
                    # Nothing left to protect: cancel the position's other exit orders.
                    conn.execute(
                        "UPDATE orders SET status = 'cancelled', reject_reason = 'position closed', "
                        "updated_at = ? WHERE symbol = ? AND side = 'sell' AND status = 'open' AND id != ?",
                        (now, symbol, order_id),
                    )
                else:
                    conn.execute("UPDATE positions SET quantity = ?, updated_at = ? WHERE symbol = ?",
                                 (remaining, now, symbol))
                conn.execute("UPDATE account SET cash = cash + ? WHERE id = 1", (qty * fill - commission,))

            conn.execute(
                "UPDATE orders SET status = 'filled', fill_price = ?, commission = ?, quantity = ?, "
                "filled_at = ?, updated_at = ? WHERE id = ?",
                (fill, commission, qty, now, now, order_id),
            )
            conn.execute(
                "INSERT INTO trades(order_id, symbol, side, quantity, price, commission, realized_pnl, "
                "source, run_id, ts) VALUES(?,?,?,?,?,?,?,?,?,?)",
                (order_id, symbol, side, qty, fill, commission, realized, order["source"], order["run_id"], now),
            )
        self.snapshot(force=True)
        return True

    # -- equity curve -------------------------------------------------------

    def snapshot(self, force: bool = False) -> None:
        last = self.db.query_one("SELECT ts FROM equity_snapshots ORDER BY id DESC LIMIT 1")
        if not force and last and datetime.now(UTC) - datetime.fromisoformat(last["ts"]) < SNAPSHOT_EVERY:
            return
        try:
            s = self.summary()
        except Exception as exc:  # never let a chart point break a fill
            logger.warning("equity snapshot failed: %s", exc)
            return
        self.db.execute("INSERT INTO equity_snapshots(ts, equity, cash) VALUES(?,?,?)",
                        (utcnow(), s["equity"], s["cash"]))

    def equity_history(self, days: int | None = None) -> list[dict[str, Any]]:
        if days:
            since = (datetime.now(UTC) - timedelta(days=days)).isoformat(timespec="seconds")
            return self.db.query("SELECT ts, equity, cash FROM equity_snapshots WHERE ts >= ? ORDER BY id", (since,))
        return self.db.query("SELECT ts, equity, cash FROM equity_snapshots ORDER BY id")
