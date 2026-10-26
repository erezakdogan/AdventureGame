"""Glue between a decision and the broker: size it against the live account, then place it."""

from __future__ import annotations

from typing import Any

from .broker import BrokerError, PaperBroker
from .market import asset_type_of
from .policy import OrderPlan, plan_order
from .settings_store import Settings

PROTECTIVE_SOURCES = ("agent-stop", "agent-target")


def current_plan(broker: PaperBroker, settings: Settings, symbol: str, rating: str,
                 trader: dict[str, Any] | None, decision: dict[str, Any] | None) -> OrderPlan:
    price = broker.market.quote(symbol).price
    summary = broker.summary()
    held = (broker.position(symbol) or {}).get("quantity", 0.0)
    fractional = settings.allow_fractional or asset_type_of(symbol) == "crypto"
    return plan_order(rating, price, summary["equity"], summary["cash"], held, settings,
                      trader=trader, decision=decision, fractional=fractional)


def execute_plan(broker: PaperBroker, symbol: str, plan: OrderPlan, run_id: int | None,
                 source: str = "agent") -> list[dict[str, Any]]:
    """Place the plan's order and, after a buy, its protective stop and target."""
    if plan.action == "none" or plan.quantity <= 0:
        return []
    main = broker.place_order(symbol, plan.action, quantity=plan.quantity, source=source,
                              run_id=run_id, note=plan.reason)
    orders = [main]
    if main["status"] != "filled" or plan.action != "buy":
        return orders

    # The new stop and target cover the whole position and replace earlier ones.
    for o in broker.list_orders("open"):
        if o["symbol"] == symbol and o["source"] in PROTECTIVE_SOURCES:
            broker.cancel_order(o["id"], reason="replaced by a newer agent decision")
    held = (broker.position(symbol) or {}).get("quantity", 0.0)
    for kind, price, src in (("stop", plan.stop_loss, "agent-stop"), ("limit", plan.take_profit, "agent-target")):
        if not price or held <= 0:
            continue
        try:
            orders.append(broker.place_order(
                symbol, "sell", quantity=held, order_type=kind,
                stop_price=price if kind == "stop" else None,
                limit_price=price if kind == "limit" else None,
                source=src, run_id=run_id,
                note="stop-loss from the Trader" if kind == "stop" else "take-profit at the price target",
            ))
        except BrokerError as exc:
            plan.notes.append(f"could not place {kind} order: {exc}")
    return orders
