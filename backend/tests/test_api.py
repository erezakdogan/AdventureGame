from datetime import datetime
from zoneinfo import ZoneInfo

from app.market import today_iso

from .conftest import FakeGraph, wait_for


def _finished(client, run_id):
    run = client.get(f"/api/runs/{run_id}").json()
    return run if run["status"] not in ("queued", "running") else None


def test_auth_required(client):
    assert client.get("/api/health").status_code == 200
    r = client.get("/api/account", headers={"Authorization": "Bearer wrong"})
    assert r.status_code == 401


def test_key_management_never_returns_the_key(client):
    r = client.put("/api/settings/keys", json={"name": "anthropic", "value": "not-a-key"})
    assert r.status_code == 400
    key = "sk-ant-api03-" + "x" * 40
    r = client.put("/api/settings/keys", json={"name": "anthropic", "value": key})
    assert r.status_code == 200
    body = client.get("/api/settings").text
    assert key not in body
    assert client.get("/api/settings").json()["keys"]["anthropic"]["set"] is True


def test_run_needs_a_key(client):
    r = client.post("/api/runs", json={"ticker": "AAPL"})
    assert r.status_code == 400 and "API key" in r.json()["detail"]


def test_full_run_then_execute(client, services):
    client.put("/api/settings/keys", json={"name": "anthropic", "value": "sk-ant-test-" + "y" * 30})
    client.patch("/api/settings", json={"slippage_bps": 0})
    r = client.post("/api/runs", json={"ticker": "aapl", "max_debate_rounds": 2})
    assert r.status_code == 200, r.text
    run_id = r.json()["id"]
    run = wait_for(lambda: _finished(client, run_id))
    assert run["status"] == "completed", run.get("error")
    assert run["rating"] == "Buy"
    assert run["options"]["max_debate_rounds"] == 2
    assert set(run["agents"].values()) == {"completed"}
    assert run["progress"] == 1.0
    assert run["reports"]["market_report"] == "m"
    assert run["usage"]["cost_usd"] > 0
    plan = run["proposal"]["plan"]
    assert plan["action"] == "buy" and plan["quantity"] == 100 and plan["stop_loss"] == 180.0

    events = client.get(f"/api/runs/{run_id}/events").json()["events"]
    assert any(e["kind"] == "tool" and e["agent"] == "Market Analyst" for e in events)
    assert any(e["kind"] == "decision" for e in events)

    # The agents saw the paper account as their portfolio.
    assert FakeGraph.seen_portfolios[0].cash == 100_000

    r = client.post(f"/api/runs/{run_id}/execute", json={})
    assert r.status_code == 200, r.text
    orders = r.json()["orders"]
    assert orders[0]["status"] == "filled" and orders[0]["quantity"] == 100
    assert orders[1]["order_type"] == "stop" and orders[1]["status"] == "open"
    assert client.post(f"/api/runs/{run_id}/execute", json={}).status_code == 400

    acct = client.get("/api/account").json()
    assert acct["positions"][0]["symbol"] == "AAPL"
    usage = client.get("/api/usage").json()
    assert usage["month_cost_usd"] > 0 and usage["avg_run_cost_usd"] > 0


def test_auto_execute_and_sell(client):
    client.put("/api/settings/keys", json={"name": "anthropic", "value": "sk-ant-test-" + "y" * 30})
    FakeGraph.ratings = ["Buy", "Sell"]
    first = client.post("/api/runs", json={"ticker": "NVDA", "auto_execute": True}).json()
    wait_for(lambda: _finished(client, first["id"]))
    assert client.get("/api/account").json()["positions"][0]["symbol"] == "NVDA"
    second = client.post("/api/runs", json={"ticker": "NVDA", "auto_execute": True}).json()
    run = wait_for(lambda: _finished(client, second["id"]))
    assert run["rating"] == "Sell"
    assert client.get("/api/account").json()["positions"] == []
    # The stop-loss placed after the buy is cancelled once the position is closed.
    assert client.get("/api/orders?status=open").json()["orders"] == []


def test_budget_guard(client, services):
    client.put("/api/settings/keys", json={"name": "anthropic", "value": "sk-ant-test-" + "y" * 30})
    services.db.execute("INSERT INTO usage_log(ts, kind, model, input_tokens, output_tokens, cost_usd) "
                        "VALUES(datetime('now'), 'run', 'claude-opus-5-5', 1, 1, 99.0)")
    services.db.execute("UPDATE usage_log SET ts = ?", (datetime.now().astimezone().isoformat(),))
    client.patch("/api/settings", json={"monthly_budget_usd": 10})
    r = client.post("/api/runs", json={"ticker": "AAPL"})
    assert r.status_code == 400 and "budget" in r.json()["detail"]


def test_settings_validation(client):
    assert client.patch("/api/settings", json={"analysts": []}).status_code == 400
    assert client.patch("/api/settings", json={"deep_model": "gpt-6"}).status_code == 400
    r = client.patch("/api/settings", json={"autopilot": {"tickers": ["aapl", "AAPL", "nvda"], "run_time": "9:05"}})
    assert r.json()["settings"]["autopilot"]["tickers"] == ["AAPL", "NVDA"]
    assert r.json()["settings"]["autopilot"]["run_time"] == "09:05"


def test_orders_and_watchlist_api(client):
    r = client.post("/api/orders", json={"symbol": "AAPL", "side": "buy", "quantity": 2})
    assert r.json()["status"] == "filled"
    r = client.post("/api/orders", json={"symbol": "ZZZZ", "side": "buy", "quantity": 2})
    assert r.status_code == 400
    lim = client.post("/api/orders", json={"symbol": "AAPL", "side": "buy", "quantity": 1,
                                           "order_type": "limit", "limit_price": 1}).json()
    assert client.delete(f"/api/orders/{lim['id']}").json()["status"] == "cancelled"
    assert client.post("/api/watchlist", json={"symbol": "nvda"}).json()["symbols"] == ["NVDA"]
    q = client.get("/api/market/quotes?symbols=NVDA,ZZZZ").json()
    assert q["quotes"][0]["symbol"] == "NVDA" and "ZZZZ" in q["errors"]
    assert len(client.get("/api/market/history/NVDA").json()["bars"]) == 5


def test_autopilot_runs_once_a_day(client, services):
    client.put("/api/settings/keys", json={"name": "anthropic", "value": "sk-ant-test-" + "y" * 30})
    client.patch("/api/settings", json={"autopilot": {"enabled": True, "tickers": ["AAPL"],
                                                      "run_time": "10:00", "timezone": "UTC",
                                                      "weekdays_only": False}})
    early = datetime(2026, 10, 26, 9, 0, tzinfo=ZoneInfo("UTC"))
    late = datetime(2026, 10, 26, 10, 1, tzinfo=ZoneInfo("UTC"))
    assert services.scheduler.autopilot_due(early) == []
    started = services.scheduler.autopilot_due(late)
    assert len(started) == 1
    assert services.scheduler.autopilot_due(late) == []
    run = wait_for(lambda: _finished(client, started[0]))
    assert run["source"] == "autopilot" and run["trade_date"] == today_iso()


def test_replay(client, services, market):
    client.put("/api/settings/keys", json={"name": "anthropic", "value": "sk-ant-test-" + "y" * 30})
    client.patch("/api/settings", json={"slippage_bps": 0})
    market.closes["AAPL"] = [("2026-03-02", 100.0), ("2026-03-03", 100.0), ("2026-03-09", 110.0),
                             ("2026-03-10", 120.0), ("2026-03-16", 90.0), ("2026-03-17", 95.0)]
    FakeGraph.ratings = ["Buy", "Hold", "Sell"]
    r = client.post("/api/replays", json={"ticker": "AAPL", "start_date": "2026-03-02",
                                          "end_date": "2026-03-16", "every_n_days": 7,
                                          "starting_cash": 10_000})
    assert r.status_code == 200, r.text
    rid = r.json()["id"]
    replay = wait_for(lambda: (x := client.get(f"/api/replays/{rid}").json())["status"]
                      not in ("queued", "running") and x)
    assert replay["status"] == "completed", replay.get("error")
    steps = replay["steps"]
    assert [s["rating"] for s in steps] == ["Buy", "Hold", "Sell"]
    # Buy 20% of 10k at the 03-03 close of 100, sell at the 03-17 close of 95.
    assert steps[0]["quantity"] == 20 and steps[0]["fill_date"] == "2026-03-03"
    assert steps[2]["action"] == "sell" and steps[2]["price"] == 95.0
    s = replay["summary"]
    assert s["final_equity"] == 10_000 - 20 * 5
    assert round(s["buy_hold_return_pct"], 2) == -5.0
    # Replay runs never touch the live account or the main runs list.
    assert client.get("/api/account").json()["positions"] == []
    assert client.get("/api/runs").json()["runs"] == []


def test_replay_rejects_future_and_huge_grids(client):
    client.put("/api/settings/keys", json={"name": "anthropic", "value": "sk-ant-test-" + "y" * 30})
    r = client.post("/api/replays", json={"ticker": "AAPL", "start_date": "2020-01-01",
                                          "end_date": "2020-12-31", "every_n_days": 1})
    assert r.status_code == 400 and "too many" in r.json()["detail"]
