"""The bot's track record: every forecast it makes, scored when its deadline passes.

A prediction is "TICKER moves from ``entry_price`` to ``target_price`` by
``due_at``". Analyses record one from the Portfolio Manager's rating, price
target and time horizon; the AI fund records one for every trade it makes,
with the target and horizon it states for that trade.

When ``due_at`` has passed, the price path between the forecast and its
deadline is fetched and scored several ways, because one number hides too much:

- **accuracy**: how far the price got toward the target by the deadline,
  clamped to 0-100%. Entry 1.00, target 1.20, price 1.12 at the deadline: 60%.
- **precision**: how close the deadline price landed to the target, with
  overshoot penalised like undershoot. 1.12 or 1.28 both score 60%; a target
  shot far past means the size of the move was misjudged.
- **peak reach / hit target**: the best point reached before the deadline, and
  whether (and when) the target traded at all. A forecast can hit its target
  on day 2 and give it back by day 5.
- **direction**: did the price at least move the predicted way.
- **hit stop**: did it trade through the stated stop-loss first.

A Hold is a forecast that the price stays in a band; it scores by how little
it moved. A call with a direction but no target scores on direction alone.
"""

from __future__ import annotations

import logging
import math
import re
from datetime import UTC, datetime, timedelta
from typing import Any

from .db import Database, utcnow
from .market import Bar, MarketData, MarketDataError, bar_interval, bar_time

logger = logging.getLogger(__name__)

DEFAULT_HORIZON_HOURS = 7 * 24  # five trading days, TradingAgents' own holding period
MAX_HORIZON_HOURS = 2 * 365 * 24

_UNIT_HOURS = {
    "min": 1 / 60, "minute": 1 / 60, "hr": 1, "hour": 1, "h": 1, "day": 24, "d": 24,
    "week": 168, "wk": 168, "w": 168, "month": 730, "mo": 730, "quarter": 2190, "year": 8760, "yr": 8760,
}
_UNIT_RE = r"(minutes?|mins?|hours?|hrs?|h|trading\s+days?|days?|d|weeks?|wks?|w|months?|mo|quarters?|years?|yrs?)"
_NUM = r"(\d+(?:\.\d+)?)"


def _unit_hours(unit: str) -> float:
    unit = unit.lower().strip()
    trading = unit.startswith("trading")
    unit = unit.replace("trading", "").strip().rstrip("s") or "d"
    hours = _UNIT_HOURS.get(unit) or _UNIT_HOURS.get(unit[:3]) or _UNIT_HOURS.get(unit[:2], 24)
    return hours * 1.4 if trading else hours  # 5 trading days ~ 7 calendar days


def parse_horizon_hours(text: str | None) -> float | None:
    """Hours in a horizon such as "3-6 months", "5 hours", "1 to 2 weeks" (the far end of a range)."""
    if not text:
        return None
    t = text.lower()
    m = re.search(rf"{_NUM}\s*(?:-|–|to)\s*{_NUM}\s*{_UNIT_RE}\b", t)
    if m:
        value = float(m.group(2)) * _unit_hours(m.group(3))
    else:
        m = re.search(rf"{_NUM}\s*-?\s*{_UNIT_RE}\b", t)
        if m:
            value = float(m.group(1)) * _unit_hours(m.group(2))
        elif re.search(r"intraday|end of (the )?day|same day", t):
            value = 6.0
        elif "overnight" in t:
            value = 18.0
        elif "short" in t:
            value = 14 * 24.0
        elif "medium" in t or "mid" in t:
            value = 90 * 24.0
        elif "long" in t:
            value = 365 * 24.0
        else:
            return None
    return min(max(value, 0.25), MAX_HORIZON_HOURS)


DIRECTION_OF_RATING = {"Buy": "up", "Overweight": "up", "Hold": "flat", "Underweight": "down", "Sell": "down"}


def _clamp(v: float | None, lo: float = 0.0, hi: float = 100.0) -> float | None:
    return None if v is None else max(lo, min(hi, v))


def flat_band_pct(horizon_hours: float) -> float:
    """How far a Hold may drift and still count as right: 1% intraday, up to 5% over months."""
    return min(5.0, max(1.0, 1.0 + math.log10(max(horizon_hours, 1) / 24 + 1) * 2))


def score(pred: dict[str, Any], bars: list[Bar]) -> dict[str, Any] | None:
    """Score a prediction against the bars from its creation to its deadline; None if no bars."""
    created = datetime.fromisoformat(pred["created_at"])
    due = datetime.fromisoformat(pred["due_at"])
    daily = bars and len(bars[0].t) == 10
    window = []
    for b in bars:
        ts = bar_time(b)
        if daily:
            if created.date() <= ts.date() <= due.date():
                window.append((ts, b))
        elif created - timedelta(minutes=5) <= ts <= due:
            window.append((ts, b))
    if not window:
        return None

    entry, target, stop = pred["entry_price"], pred["target_price"], pred["stop_price"]
    direction = pred["direction"]
    final = window[-1][1].c
    ret = (final - entry) / entry * 100
    out: dict[str, Any] = {"price_at_due": final, "return_pct": ret}

    if direction == "flat":
        band = flat_band_pct(pred["horizon_hours"])
        out.update(direction_correct=int(abs(ret) <= band),
                   accuracy_pct=_clamp(100 - abs(ret) / band * 100),
                   note=f"Hold: scored on staying within ±{band:.1f}%")
    else:
        up = direction == "up"
        out["direction_correct"] = int(ret > 0 if up else ret < 0)
        extreme = max(b.h for _, b in window) if up else min(b.l for _, b in window)
        if stop:
            stop_hit_at = next((ts for ts, b in window if (b.l <= stop if up else b.h >= stop)), None)
            out["hit_stop"] = int(stop_hit_at is not None)
        else:
            stop_hit_at = None
        if target and (target > entry if up else target < entry):
            span = target - entry
            progress = (final - entry) / span * 100
            peak = (extreme - entry) / span * 100
            hit_at = next((ts for ts, b in window if (b.h >= target if up else b.l <= target)), None)
            out.update(
                progress_pct=progress,
                accuracy_pct=_clamp(progress),
                peak_progress_pct=peak,
                hit_target=int(hit_at is not None),
                hit_target_at=hit_at.isoformat(timespec="minutes") if hit_at else None,
                target_error_pct=(final - target) / target * 100,
                score=_clamp(100 - abs(final - target) / abs(span) * 100),
            )
            if hit_at and stop_hit_at and stop_hit_at < hit_at:
                out["note"] = "the stop-loss traded before the target"
        else:
            out["note"] = "no price target given; scored on direction only"
    return out


class PredictionService:
    def __init__(self, db: Database, market: MarketData):
        self.db = db
        self.market = market

    # -- recording -----------------------------------------------------------

    def record(self, *, source: str, ticker: str, direction: str, entry_price: float,
               horizon_hours: float, target_price: float | None = None, stop_price: float | None = None,
               created_at: datetime | None = None, horizon_text: str | None = None, rating: str | None = None,
               confidence: float | None = None, rationale: str | None = None, run_id: int | None = None,
               fund_id: int | None = None, cycle_id: int | None = None) -> int | None:
        if direction not in ("up", "down", "flat") or not entry_price or entry_price <= 0:
            return None
        # A target or stop on the wrong side of the entry contradicts the call; keep the direction only.
        if target_price is not None and (
                (direction == "up" and target_price <= entry_price) or (direction == "down" and target_price >= entry_price)):
            target_price = None
        if stop_price is not None and (
                (direction == "up" and stop_price >= entry_price) or (direction == "down" and stop_price <= entry_price)):
            stop_price = None
        created = created_at or datetime.now(UTC)
        horizon_hours = min(max(float(horizon_hours), 0.25), MAX_HORIZON_HOURS)
        due = created + timedelta(hours=horizon_hours)
        return self.db.execute(
            "INSERT INTO predictions(created_at, source, run_id, fund_id, cycle_id, ticker, direction, rating, "
            "entry_price, target_price, stop_price, horizon_text, horizon_hours, due_at, confidence, rationale) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (created.isoformat(timespec="seconds"), source, run_id, fund_id, cycle_id, ticker, direction, rating,
             entry_price, target_price, stop_price, horizon_text, horizon_hours,
             due.isoformat(timespec="seconds"), confidence, (rationale or "")[:2000] or None),
        )

    def record_from_run(self, run: dict[str, Any], proposal: dict[str, Any]) -> int | None:
        """Turn a finished analysis into a prediction: rating -> direction, PM target and horizon."""
        rating = run.get("rating")
        direction = DIRECTION_OF_RATING.get(rating or "")
        if not direction:
            return None
        decision = proposal.get("decision") or {}
        trader = proposal.get("trader") or {}
        horizon_text = decision.get("time_horizon")
        hours = parse_horizon_hours(horizon_text) or DEFAULT_HORIZON_HOURS
        trade_date = run["trade_date"]
        today = datetime.now().date().isoformat()
        try:
            if trade_date >= today:
                created, entry = None, self.market.quote(run["ticker"]).price
            else:
                # A past-dated analysis is judged from that day's close.
                start = (datetime.fromisoformat(trade_date) - timedelta(days=10)).date().isoformat()
                closes = self.market.daily_closes(run["ticker"], start, trade_date)
                if not closes:
                    return None
                entry = closes[-1][1]
                created = datetime.fromisoformat(trade_date).replace(hour=21, tzinfo=UTC)
        except MarketDataError as exc:
            logger.info("no entry price for prediction of run %s: %s", run["id"], exc)
            return None
        source = "replay" if run.get("source") == "replay" else run.get("source") or "analysis"
        return self.record(
            source=source, ticker=run["ticker"], direction=direction, entry_price=entry,
            target_price=decision.get("price_target"), stop_price=trader.get("stop_loss"),
            horizon_hours=hours, horizon_text=horizon_text or "5 trading days (default)", rating=rating,
            rationale=decision.get("executive_summary"), run_id=run["id"], created_at=created,
        )

    # -- scoring -------------------------------------------------------------

    def evaluate_due(self, now: datetime | None = None, limit: int = 40) -> int:
        """Score predictions whose deadline has passed. Returns how many were scored."""
        now = now or datetime.now(UTC)
        due = self.db.query("SELECT * FROM predictions WHERE status = 'open' AND due_at <= ? ORDER BY due_at LIMIT ?",
                            (now.isoformat(timespec="seconds"), limit))
        scored = 0
        for p in due:
            created, deadline = datetime.fromisoformat(p["created_at"]), datetime.fromisoformat(p["due_at"])
            # Give the data feed time to publish the deadline's bar.
            grace = timedelta(minutes=20) if bar_interval(created, deadline, now) != "1d" else timedelta(hours=6)
            if now < deadline + grace:
                continue
            try:
                bars = self.market.bars_between(p["ticker"], created, deadline)
            except MarketDataError as exc:
                logger.info("cannot score prediction %s yet: %s", p["id"], exc)
                if now - deadline > timedelta(days=7):
                    self._close(p["id"], "no_data", note=str(exc)[:300])
                continue
            result = score(p, bars)
            if result is None:
                if now - deadline > timedelta(days=4):
                    self._close(p["id"], "no_data", note="no trading in the forecast window")
                continue
            self._close(p["id"], "scored", **result)
            scored += 1
        return scored

    def _close(self, pred_id: int, status: str, **fields: Any) -> None:
        sets, params = ["status = ?", "scored_at = ?"], [status, utcnow()]
        for k, v in fields.items():
            sets.append(f"{k} = ?")
            params.append(v)
        self.db.execute(f"UPDATE predictions SET {', '.join(sets)} WHERE id = ?", (*params, pred_id))

    # -- reading -------------------------------------------------------------

    @staticmethod
    def _where(source: str | None, fund_id: int | None, ticker: str | None, status: str | None,
               run_id: int | None = None):
        where, params = [], []
        if run_id is not None:
            where.append("run_id = ?")
            params.append(run_id)
        if fund_id is not None:
            where.append("fund_id = ?")
            params.append(fund_id)
        if source == "analyses":
            where.append("source IN ('manual', 'autopilot', 'analysis')")
        elif source == "funds":
            where.append("fund_id IS NOT NULL")
        elif source:
            where.append("source = ?")
            params.append(source)
        if ticker:
            where.append("ticker = ?")
            params.append(ticker.upper())
        if status:
            where.append("status = ?")
            params.append(status)
        return (" WHERE " + " AND ".join(where)) if where else "", params

    def list(self, source: str | None = None, fund_id: int | None = None, ticker: str | None = None,
             status: str | None = None, limit: int = 100, live: bool = True,
             run_id: int | None = None) -> list[dict[str, Any]]:
        clause, params = self._where(source, fund_id, ticker, status, run_id)
        rows = self.db.query(f"SELECT * FROM predictions{clause} ORDER BY id DESC LIMIT ?", (*params, limit))
        now = datetime.now(UTC)
        for r in rows:
            r["time_left_hours"] = max(0.0, (datetime.fromisoformat(r["due_at"]) - now).total_seconds() / 3600)
            if live and r["status"] == "open":
                r.update(self._live(r))
        return rows

    def _live(self, p: dict[str, Any]) -> dict[str, Any]:
        """Where an open prediction stands right now."""
        try:
            price = self.market.quote(p["ticker"]).price
        except MarketDataError:
            return {}
        out = {"current_price": price, "current_return_pct": (price - p["entry_price"]) / p["entry_price"] * 100}
        if p["target_price"] and p["direction"] != "flat":
            out["current_progress_pct"] = (price - p["entry_price"]) / (p["target_price"] - p["entry_price"]) * 100
        return out

    def stats(self, source: str | None = None, fund_id: int | None = None, ticker: str | None = None) -> dict[str, Any]:
        clause, params = self._where(source, fund_id, ticker, None)
        rows = self.db.query(f"SELECT * FROM predictions{clause}", tuple(params))
        scored = [r for r in rows if r["status"] == "scored"]
        targeted = [r for r in scored if r["accuracy_pct"] is not None and r["direction"] != "flat"]

        def avg(values):
            values = [v for v in values if v is not None]
            return round(sum(values) / len(values), 2) if values else None

        def rate(values):
            values = [v for v in values if v is not None]
            return round(sum(1 for v in values if v) / len(values) * 100, 1) if values else None

        by_kind: dict[str, dict[str, Any]] = {}
        for key in ("up", "down", "flat"):
            group = [r for r in scored if r["direction"] == key]
            by_kind[key] = {"count": len(group), "avg_accuracy_pct": avg(r["accuracy_pct"] for r in group),
                            "direction_rate_pct": rate(r["direction_correct"] for r in group)}
        recent = sorted(scored, key=lambda r: r["scored_at"] or "")[-30:]
        return {
            "total": len(rows),
            "open": sum(1 for r in rows if r["status"] == "open"),
            "scored": len(scored),
            "avg_accuracy_pct": avg(r["accuracy_pct"] for r in scored),
            "avg_precision_pct": avg(r["score"] for r in targeted),
            "target_hit_rate_pct": rate(r["hit_target"] for r in targeted),
            "direction_rate_pct": rate(r["direction_correct"] for r in scored),
            "avg_peak_reach_pct": avg(_clamp(r["peak_progress_pct"], -100, 200) for r in targeted),
            "stop_hit_rate_pct": rate(r["hit_stop"] for r in scored if r["stop_price"]),
            "avg_return_pct": avg(
                (r["return_pct"] if r["direction"] != "down" else -r["return_pct"]) for r in scored
                if r["direction"] != "flat" and r["return_pct"] is not None),
            "by_direction": by_kind,
            "recent_accuracy": [{"id": r["id"], "ticker": r["ticker"], "accuracy_pct": r["accuracy_pct"],
                                 "scored_at": r["scored_at"]} for r in recent],
        }
