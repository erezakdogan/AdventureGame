from datetime import UTC, datetime, timedelta

import pytest

from app.market import Bar
from app.predictions import flat_band_pct, parse_horizon_hours, score

from .conftest import wait_for

T0 = datetime(2026, 10, 20, 14, 0, tzinfo=UTC)


def bars(*closes, high=None, low=None, start=T0, step=timedelta(hours=1)):
    """Hourly bars after ``start``; ``high``/``low`` override one bar's extremes as {index: price}."""
    out = []
    for i, c in enumerate(closes):
        h = (high or {}).get(i, c)
        lo = (low or {}).get(i, c)
        out.append(Bar(t=(start + step * (i + 1)).isoformat(), o=c, h=max(h, c), l=min(lo, c), c=c, v=1))
    return out


def pred(direction="up", entry=1.0, target=1.2, stop=None, hours=5):
    return {"created_at": T0.isoformat(), "due_at": (T0 + timedelta(hours=hours)).isoformat(),
            "entry_price": entry, "target_price": target, "stop_price": stop, "direction": direction,
            "horizon_hours": hours}


@pytest.mark.parametrize(("text", "hours"), [
    ("3-6 months", 6 * 730), ("5 hours", 5), ("1 to 2 weeks", 336), ("2 days", 48),
    ("5 trading days", 5 * 24 * 1.4), ("12-18 months", 18 * 730), ("intraday", 6), ("long-term", 8760),
    ("next 90 minutes", 1.5), ("", None), ("not provided", None),
])
def test_parse_horizon(text, hours):
    assert parse_horizon_hours(text) == (pytest.approx(hours) if hours else None)


def test_user_example_sixty_percent():
    # Bought at 1.00 expecting 1.20 in 5 hours; at the deadline it is 1.12.
    r = score(pred(), bars(1.02, 1.05, 1.08, 1.10, 1.12))
    assert r["accuracy_pct"] == pytest.approx(60)
    assert r["score"] == pytest.approx(60)  # precision: 0.08 short of a 0.20 move
    assert r["hit_target"] == 0 and r["direction_correct"] == 1
    assert r["return_pct"] == pytest.approx(12)


def test_overshoot_is_full_accuracy_but_imprecise():
    r = score(pred(), bars(1.1, 1.2, 1.28))
    assert r["accuracy_pct"] == 100
    assert r["score"] == pytest.approx(60)
    assert r["hit_target"] == 1 and r["hit_target_at"]
    assert r["target_error_pct"] == pytest.approx((1.28 - 1.2) / 1.2 * 100)


def test_target_touched_then_given_back():
    r = score(pred(), bars(1.05, 1.15, 1.04, 1.02, 1.03, high={1: 1.21}))
    assert r["hit_target"] == 1
    assert r["peak_progress_pct"] == pytest.approx(105)
    assert r["accuracy_pct"] == pytest.approx(15)


def test_wrong_direction_scores_zero():
    r = score(pred(), bars(0.97, 0.95, 0.9))
    assert r["accuracy_pct"] == 0 and r["progress_pct"] == pytest.approx(-50)
    assert r["direction_correct"] == 0 and r["score"] == 0


def test_down_call_and_stop_before_target():
    r = score(pred("down", entry=100, target=90, stop=104),
              bars(103, 105, 95, 89, 92, high={1: 105}, low={3: 89}))
    assert r["direction_correct"] == 1
    assert r["accuracy_pct"] == pytest.approx(80)
    assert r["hit_stop"] == 1 and r["hit_target"] == 1
    assert "stop-loss traded before the target" in r["note"]


def test_hold_scores_by_staying_in_band():
    band = flat_band_pct(5)
    r = score(pred("flat", entry=100, target=None, hours=5), bars(100.2, 99.9, 100.3))
    assert r["direction_correct"] == 1 and r["accuracy_pct"] == pytest.approx(100 - 0.3 / band * 100)
    r = score(pred("flat", entry=100, target=None, hours=5), bars(103, 105))
    assert r["direction_correct"] == 0 and r["accuracy_pct"] == 0


def test_direction_only_without_target():
    r = score(pred(target=None), bars(1.01, 1.03))
    assert r["direction_correct"] == 1 and "accuracy_pct" not in r and "direction only" in r["note"]


def test_bars_outside_window_ignored():
    early = bars(5.0, start=T0 - timedelta(days=2))
    late = bars(9.0, start=T0 + timedelta(hours=10))
    assert score(pred(), early + late) is None


def test_record_validates_sides(services):
    p = services.predictions
    pid = p.record(source="fund", ticker="AAPL", direction="up", entry_price=100, target_price=90,
                   stop_price=110, horizon_hours=5)
    row = services.db.query_one("SELECT * FROM predictions WHERE id = ?", (pid,))
    assert row["target_price"] is None and row["stop_price"] is None
    assert p.record(source="x", ticker="AAPL", direction="sideways", entry_price=1, horizon_hours=1) is None


def test_evaluate_due_and_stats(services, market):
    p = services.predictions
    created = datetime.now(UTC) - timedelta(hours=8)
    pid = p.record(source="fund", ticker="AAPL", direction="up", entry_price=1.0, target_price=1.2,
                   horizon_hours=5, created_at=created, fund_id=7)
    open_id = p.record(source="fund", ticker="AAPL", direction="up", entry_price=150.0, target_price=250.0,
                       horizon_hours=48, fund_id=7)
    market.bars["AAPL"] = bars(1.05, 1.12, start=created)
    assert p.evaluate_due() == 1
    row = services.db.query_one("SELECT * FROM predictions WHERE id = ?", (pid,))
    assert row["status"] == "scored" and row["accuracy_pct"] == pytest.approx(60)

    live = {r["id"]: r for r in p.list(fund_id=7)}
    assert live[open_id]["status"] == "open"
    assert live[open_id]["current_progress_pct"] == pytest.approx(50)  # 150 -> 200 of a 150 -> 250 call
    stats = p.stats(fund_id=7)
    assert stats["scored"] == 1 and stats["open"] == 1 and stats["avg_accuracy_pct"] == 60
    assert stats["direction_rate_pct"] == 100 and stats["target_hit_rate_pct"] == 0


def test_analysis_records_a_prediction(client):
    client.put("/api/settings/keys", json={"name": "anthropic", "value": "sk-ant-test-" + "y" * 30})
    run = client.post("/api/runs", json={"ticker": "AAPL"}).json()
    wait_for(lambda: client.get(f"/api/runs/{run['id']}").json()["status"] == "completed")
    preds = wait_for(lambda: client.get("/api/predictions?source=analyses").json()["predictions"])
    p = preds[0]
    # FakeGraph's Portfolio Manager: Buy, target 260, horizon 3-6 months; AAPL quotes at 200.
    assert p["direction"] == "up" and p["entry_price"] == 200 and p["target_price"] == 260
    assert p["horizon_hours"] == pytest.approx(6 * 730) and p["run_id"] == run["id"]
    assert p["stop_price"] == 180
    assert client.get(f"/api/predictions?run_id={run['id']}").json()["predictions"][0]["id"] == p["id"]
    stats = client.get("/api/predictions/stats").json()
    assert stats["total"] == 1 and stats["open"] == 1
