import pytest

from app.broker import BrokerError
from app.policy import parse_decision, parse_trader, plan_order
from app.settings_store import Settings

from .conftest import decision_text, trader_text


def test_market_buy_and_sell_with_costs(services, market):
    services.settings.update({"slippage_bps": 10, "commission_per_trade": 1.0})
    b = services.broker
    o = b.place_order("AAPL", "buy", quantity=10)
    assert o["status"] == "filled"
    assert o["fill_price"] == pytest.approx(200.2)
    assert b.account()["cash"] == pytest.approx(100_000 - 2002 - 1)
    assert b.position("AAPL")["avg_price"] == pytest.approx(200.2)

    market.prices["AAPL"] = 220.0
    s = b.place_order("AAPL", "sell", quantity=4)
    assert s["status"] == "filled"
    trade = b.list_trades(1)[0]
    assert trade["realized_pnl"] == pytest.approx((219.78 - 200.2) * 4 - 1)
    assert b.position("AAPL")["quantity"] == pytest.approx(6)
    summary = b.summary()
    assert summary["equity"] == pytest.approx(summary["cash"] + 6 * 220.0)


def test_no_shorting_and_cash_checks(services):
    b = services.broker
    with pytest.raises(BrokerError, match="does not sell short"):
        b.place_order("AAPL", "sell", quantity=1)
    o = b.place_order("AAPL", "buy", quantity=10_000)
    assert o["status"] == "rejected" and "insufficient cash" in o["reject_reason"]
    with pytest.raises(BrokerError):
        b.place_order("AAPL", "buy")


def test_notional_and_fractional(services):
    services.settings.update({"slippage_bps": 0})
    o = services.broker.place_order("AAPL", "buy", notional=1000)
    assert o["quantity"] == pytest.approx(5)
    services.settings.update({"allow_fractional": False})
    o = services.broker.place_order("AAPL", "buy", notional=500)
    assert o["quantity"] == 2
    # Crypto trades in fractions even when fractional shares are off.
    o = services.broker.place_order("BTC-USD", "buy", notional=1000)
    assert o["quantity"] == pytest.approx(0.02)


def test_limit_and_stop_orders_wait_then_fill(services, market):
    services.settings.update({"slippage_bps": 0})
    b = services.broker
    lim = b.place_order("AAPL", "buy", quantity=5, order_type="limit", limit_price=190)
    assert lim["status"] == "open"
    market.prices["AAPL"] = 189.0
    b.process_open_orders()
    lim = b.order(lim["id"])
    assert lim["status"] == "filled" and lim["fill_price"] == pytest.approx(189.0)

    stop = b.place_order("AAPL", "sell", quantity=5, order_type="stop", stop_price=180)
    target = b.place_order("AAPL", "sell", quantity=5, order_type="limit", limit_price=250)
    assert stop["status"] == target["status"] == "open"
    market.prices["AAPL"] = 179.0
    b.process_open_orders()
    assert b.order(stop["id"])["status"] == "filled"
    # The position is gone, so the take-profit is cancelled rather than left dangling.
    assert b.order(target["id"])["status"] == "cancelled"
    assert b.position("AAPL") is None


def test_reset(services):
    services.broker.place_order("AAPL", "buy", quantity=1)
    services.broker.reset(5000)
    s = services.broker.summary()
    assert s["cash"] == 5000 and s["positions"] == [] and services.broker.list_orders() == []


def test_parse_reports():
    t = parse_trader(trader_text("Buy", 180.0))
    assert t == {"action": "Buy", "entry_price": 199.5, "stop_loss": 180.0, "position_sizing": "5% of portfolio"}
    assert parse_trader(trader_text("Hold", None))["stop_loss"] is None
    d = parse_decision(decision_text("Overweight", 1234.5))
    assert d["price_target"] == 1234.5 and d["time_horizon"] == "3-6 months"
    assert parse_decision(decision_text("Hold", None))["price_target"] is None


@pytest.mark.parametrize(
    ("rating", "held", "action", "qty"),
    [
        ("Buy", 0, "buy", 100),        # 20% of 100k at $200
        ("Overweight", 0, "buy", 50),  # half the maximum
        ("Overweight", 60, "none", 0),  # already above the Overweight target: no trimming
        ("Buy", 60, "buy", 40),
        ("Hold", 60, "none", 0),
        ("Underweight", 60, "sell", 30),
        ("Sell", 60, "sell", 60),
        ("Sell", 0, "none", 0),
        ("REVIEW", 60, "none", 0),
    ],
)
def test_plan_order(rating, held, action, qty):
    cfg = Settings(slippage_bps=0, allow_fractional=False)
    plan = plan_order(rating, 200.0, 100_000, 100_000 - held * 200, held, cfg,
                      trader={"stop_loss": 180.0}, decision={"price_target": 260.0})
    assert plan.action == action
    assert plan.quantity == qty
    if action == "buy":
        assert plan.stop_loss == 180.0
        assert plan.take_profit is None  # take-profit is off by default


def test_plan_caps_to_cash_and_skips_bad_stop():
    cfg = Settings(slippage_bps=0, allow_fractional=False, use_take_profit=True)
    plan = plan_order("Buy", 200.0, 100_000, 1_000, 0, cfg, trader={"stop_loss": 250.0},
                      decision={"price_target": 150.0})
    assert plan.quantity == 5
    assert plan.stop_loss is None and plan.take_profit is None
    assert any("stop-loss" in n for n in plan.notes)


def test_friendly_errors():
    from app.agents import friendly_error

    assert "API key" in friendly_error(RuntimeError("Error code: 401 - {'type': 'authentication_error'}"))
    assert friendly_error(ValueError("boom")) == "ValueError: boom"
