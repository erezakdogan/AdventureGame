"""Turning the agents' decision into a concrete paper order.

TradingAgents ends with a 5-tier rating from the Portfolio Manager plus the
Trader's proposal (entry, stop-loss, sizing) and a price target. The rules here
map that onto the account, with sizes you control in settings:

- Buy          -> grow the position to ``max_position_pct`` of equity
- Overweight   -> grow it to ``overweight_fraction`` of that maximum
- Hold         -> no trade
- Underweight  -> sell ``underweight_trim`` of the position
- Sell         -> close the position (the account never shorts)

A rating only ever adds on Buy/Overweight and only ever reduces on
Underweight/Sell, so a weaker bullish call never forces a sale.
"""

from __future__ import annotations

import math
import re
from dataclasses import asdict, dataclass, field
from typing import Any

from .settings_store import Settings

_NUM = r"\$?\s*([0-9][0-9,]*(?:\.[0-9]+)?)"


def _field(text: str, label: str) -> str | None:
    m = re.search(rf"\*\*{label}\*\*\s*:\s*(.+)", text or "", re.IGNORECASE)
    return m.group(1).strip() if m else None


def _number(text: str | None) -> float | None:
    if not text or "not provided" in text.lower():
        return None
    m = re.match(_NUM, text.strip())
    if not m:
        return None
    try:
        value = float(m.group(1).replace(",", ""))
    except ValueError:
        return None
    return value if value > 0 and math.isfinite(value) else None


def parse_trader(text: str) -> dict[str, Any]:
    action = _field(text, "Action")
    if not action:
        m = re.search(r"FINAL TRANSACTION PROPOSAL:\s*\**\s*(BUY|HOLD|SELL)", text or "", re.IGNORECASE)
        action = m.group(1).title() if m else None
    return {
        "action": action.split()[0].strip("*").title() if action else None,
        "entry_price": _number(_field(text, "Entry Price")),
        "stop_loss": _number(_field(text, "Stop Loss")),
        "position_sizing": (_field(text, "Position Sizing") or None),
    }


def parse_decision(text: str) -> dict[str, Any]:
    horizon = _field(text, "Time Horizon")
    return {
        "executive_summary": _field(text, "Executive Summary"),
        "price_target": _number(_field(text, "Price Target")),
        "time_horizon": None if not horizon or horizon.lower() == "not provided" else horizon,
    }


@dataclass
class OrderPlan:
    rating: str
    action: str  # "buy", "sell" or "none"
    quantity: float = 0.0
    reference_price: float | None = None
    estimated_value: float = 0.0
    reason: str = ""
    stop_loss: float | None = None
    take_profit: float | None = None
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _floor(qty: float, fractional: bool) -> float:
    return math.floor(qty * 1e4) / 1e4 if fractional else float(math.floor(qty + 1e-9))


def plan_order(
    rating: str,
    price: float,
    equity: float,
    cash: float,
    held_qty: float,
    settings: Settings,
    trader: dict[str, Any] | None = None,
    decision: dict[str, Any] | None = None,
    fractional: bool | None = None,
) -> OrderPlan:
    trader, decision = trader or {}, decision or {}
    fractional = settings.allow_fractional if fractional is None else fractional
    plan = OrderPlan(rating=rating, action="none", reference_price=price)
    max_value = equity * settings.max_position_pct / 100
    held_value = held_qty * price

    if rating in ("Buy", "Overweight"):
        target = max_value * (1.0 if rating == "Buy" else settings.overweight_fraction)
        if held_value >= target * 0.98:
            plan.reason = (f"{rating}: position is already ${held_value:,.0f}, at or above its "
                           f"target of ${target:,.0f} ({target / equity * 100:.1f}% of equity)")
            return plan
        # Leave room for slippage and commission so the order is not rejected.
        unit_cost = price * (1 + settings.slippage_bps / 10_000) * (1 + settings.commission_bps / 10_000)
        affordable = max(cash - settings.commission_per_trade, 0) / unit_cost
        qty = _floor(min((target - held_value) / price, affordable), fractional)
        if qty <= 0:
            plan.reason = f"{rating}: not enough cash to add to the position"
            return plan
        plan.action, plan.quantity = "buy", qty
        plan.reason = (f"{rating}: buy to bring the position to ${target:,.0f} "
                       f"({target / equity * 100:.1f}% of equity)")
        if qty * price < target - held_value - 1:
            plan.notes.append("sized down to the cash available")
        stop = trader.get("stop_loss")
        if settings.use_stop_loss and stop:
            if stop < price:
                plan.stop_loss = stop
            else:
                plan.notes.append(f"trader's stop-loss {stop:g} is not below the price; skipped")
        target_px = decision.get("price_target")
        if settings.use_take_profit and target_px:
            if target_px > price:
                plan.take_profit = target_px
            else:
                plan.notes.append(f"price target {target_px:g} is not above the price; skipped")
    elif rating == "Underweight":
        if held_qty <= 0:
            plan.reason = "Underweight: no position to trim"
            return plan
        qty = _floor(held_qty * settings.underweight_trim, fractional) or held_qty
        plan.action, plan.quantity = "sell", min(qty, held_qty)
        plan.reason = f"Underweight: trim {settings.underweight_trim * 100:.0f}% of the position"
    elif rating == "Sell":
        if held_qty <= 0:
            plan.reason = "Sell: no position to close (this paper account does not short)"
            return plan
        plan.action, plan.quantity = "sell", held_qty
        plan.reason = "Sell: close the whole position"
    elif rating == "Hold":
        plan.reason = "Hold: keep the position as it is"
    else:
        plan.reason = "The decision had no readable rating; review the report before trading"

    plan.estimated_value = plan.quantity * price
    return plan
