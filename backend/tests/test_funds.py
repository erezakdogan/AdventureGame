import sqlite3
from datetime import UTC, datetime, timedelta

import pytest

from app.db import Database
from app.fund import NY, FundConfig, frame_features
from app.market import Bar

from .conftest import wait_for

OPEN_TIME = datetime(2026, 10, 27, 15, 0, tzinfo=UTC)  # Tuesday 11:00 New York


def decision(ticker, action, weight, expected, hours=24, stop=None, confidence=0.7):
    return {"ticker": ticker, "action": action, "target_weight_pct": weight, "expected_price": expected,
            "horizon_hours": hours, "stop_loss": stop, "confidence": confidence, "rationale": f"{ticker} reason"}


def plan(*decisions):
    return {"market_view": "Constructive tape.", "decisions": list(decisions)}


@pytest.fixture()
def fund(services):
    services.settings.set_key("anthropic", "sk-ant-test-" + "z" * 30)
    services.settings.update({"slippage_bps": 0})
    return services.funds.create("Test fund", 10_000, {
        "style": "swing", "universe": ["AAPL", "NVDA", "BTC-USD"], "max_positions": 2, "max_position_pct": 40,
        "cash_reserve_pct": 10}, run_now=False)


def test_cycle_buys_within_limits_and_records_forecasts(services, fund, allocator):
    allocator.plans = [plan(
        decision("AAPL", "buy", 50, 220, stop=190, confidence=0.9),   # capped at 40%
        decision("NVDA", "buy", 30, 110, confidence=0.8),
        decision("BTC-USD", "buy", 30, 55_000, confidence=0.5),      # third position: over the limit
    )]
    cycle = services.funds.run_cycle(fund["id"], now=OPEN_TIME)
    assert cycle["status"] == "completed", cycle["error"]
    s = services.funds.summary(fund["id"])
    pos = {p["symbol"]: p for p in s["positions"]}
    assert set(pos) == {"AAPL", "NVDA"}
    assert pos["AAPL"]["market_value"] == pytest.approx(4000, rel=0.01)
    assert pos["NVDA"]["market_value"] == pytest.approx(3000, rel=0.01)
    assert s["cash"] >= 10_000 * 0.10 - 1

    orders = services.funds.fund_broker(fund).list_orders("open")
    kinds = {(o["symbol"], o["source"]) for o in orders}
    assert ("AAPL", "fund-stop") in kinds and ("AAPL", "fund-target") in kinds and ("NVDA", "fund-target") in kinds

    preds = services.predictions.list(fund_id=fund["id"], live=False)
    assert {p["ticker"] for p in preds} == {"AAPL", "NVDA"}
    aapl = next(p for p in preds if p["ticker"] == "AAPL")
    assert aapl["target_price"] == 220 and aapl["stop_price"] == 190 and aapl["direction"] == "up"
    assert aapl["cycle_id"] == cycle["id"] and aapl["confidence"] == 0.9

    # The main paper account is a separate wallet.
    assert services.broker.positions() == []
    assert "AAPL" in allocator.prompts[0] and "beats estimates" in allocator.prompts[0]
    assert cycle["usage"]["cost_usd"] > 0 and s["claude_cost_usd"] > 0


def test_second_cycle_sells_and_sees_track_record(services, fund, allocator, market):
    allocator.plans = [plan(decision("AAPL", "buy", 30, 220)), plan(decision("AAPL", "sell", 0, 180))]
    services.funds.run_cycle(fund["id"], now=OPEN_TIME)
    market.prices["AAPL"] = 210.0
    cycle = services.funds.run_cycle(fund["id"], now=OPEN_TIME + timedelta(days=1))
    s = services.funds.summary(fund["id"])
    assert s["positions"] == [] and s["realized_pnl"] > 0
    assert services.funds.fund_broker(fund).list_orders("open") == []  # protective orders cancelled
    sold = next(d for d in cycle["decisions"] if d["ticker"] == "AAPL")
    assert sold["executed"] == "filled" and sold["side"] == "sell"
    down = [p for p in services.predictions.list(fund_id=fund["id"], live=False) if p["direction"] == "down"]
    assert len(down) == 1 and down[0]["target_price"] == 180
    assert "Your open forecasts" in allocator.prompts[1]
    assert s["win_rate_pct"] == 100


def test_take_profit_fills_before_the_next_check(services, fund, allocator, market):
    allocator.plans = [plan(decision("AAPL", "buy", 30, 220)), plan(decision("AAPL", "sell", 0, 215))]
    services.funds.run_cycle(fund["id"], now=OPEN_TIME)
    market.prices["AAPL"] = 225.0  # through the 220 take-profit
    cycle = services.funds.run_cycle(fund["id"], now=OPEN_TIME + timedelta(days=1))
    assert [(o["source"], o["status"]) for o in cycle["orders"]] == [("fund-target", "filled")]
    assert next(d for d in cycle["decisions"] if d["ticker"] == "AAPL")["executed"] == "not held"


def test_unknown_tickers_and_hold_are_ignored(services, fund, allocator):
    allocator.plans = [plan(decision("TSLA", "buy", 30, 300), decision("AAPL", "hold", 0, 200))]
    cycle = services.funds.run_cycle(fund["id"], now=OPEN_TIME)
    assert services.funds.summary(fund["id"])["positions"] == []
    assert all(d["ticker"] != "TSLA" for d in cycle["decisions"])


def test_day_style_flattens_before_close(services, allocator):
    services.settings.set_key("anthropic", "sk-ant-test-" + "z" * 30)
    f = services.funds.create("Day", 10_000, {"style": "day", "universe": ["AAPL"]}, run_now=False)
    assert f["config"]["flatten_at_close"] is True
    allocator.plans = [plan(decision("AAPL", "buy", 20, 205, hours=3))]
    services.funds.run_cycle(f["id"], now=OPEN_TIME)
    assert services.funds.fund_broker(f).positions()
    close = datetime(2026, 10, 27, 15, 50, tzinfo=NY)
    cycle = services.funds.run_cycle(f["id"], now=close)
    assert services.funds.fund_broker(f).positions() == []
    assert "End of session" in cycle["market_view"]
    assert len(allocator.prompts) == 1  # closing needs no Claude call


def test_schedule_times(services, fund):
    svc = services.funds
    cfg = FundConfig.model_validate(fund["config"])
    nxt = svc._next_time("swing", cfg, OPEN_TIME)
    assert nxt.astimezone(NY).strftime("%a %H:%M") == "Wed 10:00"
    hourly = FundConfig.model_validate({"style": "hourly", "interval_minutes": 60, "universe": ["AAPL"],
                                        "flatten_at_close": True})
    assert svc._next_time("hourly", hourly, OPEN_TIME) == OPEN_TIME + timedelta(hours=1)
    late = datetime(2026, 10, 27, 15, 20, tzinfo=NY).astimezone(UTC)
    assert svc._next_time("hourly", hourly, late).astimezone(NY).strftime("%H:%M") == "15:45"
    friday_close = datetime(2026, 10, 30, 16, 30, tzinfo=NY).astimezone(UTC)
    assert svc._next_time("hourly", hourly, friday_close).astimezone(NY).strftime("%a %H:%M") == "Mon 09:45"
    crypto = FundConfig.model_validate({"style": "hourly", "interval_minutes": 60, "universe": ["BTC-USD"]})
    assert svc._next_time("hourly", crypto, friday_close) == friday_close + timedelta(hours=1)


def test_frame_features():
    closes = [100 + i for i in range(30)]
    f = frame_features([Bar(t=str(i), o=c, h=c + 1, l=c - 1, c=c, v=1000) for i, c in enumerate(closes)])
    assert f["chg_1"] == pytest.approx((129 - 128) / 128 * 100)
    assert f["rsi14"] == 100.0 and f["vs_sma20"] > 0 and f["from_high"] < 0


def test_fund_api(client, services, allocator):
    client.put("/api/settings/keys", json={"name": "anthropic", "value": "sk-ant-test-" + "y" * 30})
    catalog = client.get("/api/funds/catalog").json()
    assert {s["id"] for s in catalog["styles"]} >= {"hourly", "day", "swing", "position"}
    assert client.post("/api/funds", json={"name": "X", "config": {"style": "weird"}}).status_code == 400
    assert client.post("/api/funds", json={"name": "X", "config": {"universe": []}}).status_code == 400

    allocator.plans = [plan(decision("AAPL", "buy", 20, 230))]
    r = client.post("/api/funds", json={"name": "Crypto & tech", "starting_cash": 25_000,
                                        "config": {"style": "hourly", "universe": ["AAPL", "BTC-USD"],
                                                   "market_hours_only": False}})
    assert r.status_code == 200, r.text
    fid = r.json()["id"]
    cycles = wait_for(lambda: [c for c in client.get(f"/api/funds/{fid}/cycles").json()["cycles"]
                               if c["status"] != "running"])
    assert cycles[0]["status"] == "completed", cycles[0]["error"]
    f = client.get(f"/api/funds/{fid}").json()
    assert f["positions"][0]["symbol"] == "AAPL" and f["benchmark_symbol"] == "SPY"
    assert f["accuracy"]["open"] == 1
    assert client.get("/api/funds").json()["funds"][0]["id"] == fid
    assert client.get(f"/api/fund-cycles/{cycles[0]['id']}").json()["market_view"] == "Constructive tape."
    assert len(client.get(f"/api/funds/{fid}/trades").json()["trades"]) == 1
    assert client.get(f"/api/predictions?fund_id={fid}").json()["predictions"][0]["ticker"] == "AAPL"

    dep = client.post(f"/api/funds/{fid}/deposit", json={"amount": 5000}).json()
    assert dep["starting_cash"] == 30_000
    assert client.patch(f"/api/funds/{fid}", json={"status": "paused", "max_positions": 3}).json()["status"] == "paused"
    assert client.patch(f"/api/funds/{fid}", json={"max_positions": 99}).status_code == 400
    assert client.delete(f"/api/funds/{fid}").json()["ok"]
    assert client.get("/api/funds").json()["funds"] == []
    assert services.db.query("SELECT * FROM positions WHERE account_id != 1") == []


def test_scheduler_starts_due_funds(services, fund, allocator):
    allocator.plans = [plan(decision("AAPL", "buy", 20, 230))]
    services.db.execute("UPDATE funds SET next_cycle_at = ? WHERE id = ?",
                        ((datetime.now(UTC) - timedelta(minutes=1)).isoformat(timespec="seconds"), fund["id"]))
    assert services.funds.due() == [fund["id"]]
    wait_for(lambda: services.funds.cycles(fund["id"]) and services.funds.cycles(fund["id"])[0]["status"] != "running")
    nxt = services.funds.get(fund["id"])["next_cycle_at"]
    assert nxt > datetime.now(UTC).isoformat()


def test_migrates_single_account_database(tmp_path):
    path = tmp_path / "v1.sqlite3"
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE account (id INTEGER PRIMARY KEY CHECK (id = 1), starting_cash REAL NOT NULL,
            cash REAL NOT NULL, currency TEXT NOT NULL DEFAULT 'USD', created_at TEXT NOT NULL);
        CREATE TABLE positions (symbol TEXT PRIMARY KEY, quantity REAL NOT NULL, avg_price REAL NOT NULL,
            opened_at TEXT NOT NULL, updated_at TEXT NOT NULL);
        CREATE TABLE orders (id INTEGER PRIMARY KEY AUTOINCREMENT, symbol TEXT NOT NULL, side TEXT NOT NULL,
            quantity REAL NOT NULL, order_type TEXT NOT NULL, limit_price REAL, stop_price REAL,
            status TEXT NOT NULL, source TEXT NOT NULL, run_id INTEGER, note TEXT, reject_reason TEXT,
            fill_price REAL, commission REAL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, filled_at TEXT);
        CREATE TABLE trades (id INTEGER PRIMARY KEY AUTOINCREMENT, order_id INTEGER NOT NULL, symbol TEXT NOT NULL,
            side TEXT NOT NULL, quantity REAL NOT NULL, price REAL NOT NULL, commission REAL NOT NULL,
            realized_pnl REAL, source TEXT NOT NULL, run_id INTEGER, ts TEXT NOT NULL);
        CREATE TABLE equity_snapshots (id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL,
            equity REAL NOT NULL, cash REAL NOT NULL);
        INSERT INTO account VALUES (1, 100000, 90000, 'USD', '2026-10-01');
        INSERT INTO positions VALUES ('AAPL', 50, 200, '2026-10-01', '2026-10-01');
        INSERT INTO orders(symbol, side, quantity, order_type, status, source, created_at, updated_at)
            VALUES ('AAPL', 'buy', 50, 'market', 'filled', 'manual', '2026-10-01', '2026-10-01');
    """)
    conn.close()
    db = Database(path)
    assert db.query_one("SELECT kind, cash FROM account WHERE id = 1") == {"kind": "main", "cash": 90000}
    assert db.query("SELECT account_id, symbol FROM positions") == [{"account_id": 1, "symbol": "AAPL"}]
    assert db.query_one("SELECT account_id FROM orders")["account_id"] == 1
    db.execute("INSERT INTO account(name, kind, starting_cash, cash, created_at) VALUES('F', 'fund', 1, 1, 'x')")
    db.close()
    Database(path).close()  # reopening a migrated database is a no-op
