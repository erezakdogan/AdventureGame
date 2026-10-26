"""Token accounting for every Claude call, priced so you can see what a run costs.

Prices are Anthropic first-party list prices in USD per million tokens. Cache
reads bill at 0.1x input and cache writes at 1.25x. Treat the totals as
estimates; the Anthropic Console is the source of truth for the bill.
"""

from __future__ import annotations

import threading
from collections import defaultdict
from datetime import UTC, datetime
from typing import Any

from langchain_core.callbacks import BaseCallbackHandler

from .db import Database, utcnow

# model id -> (input $/MTok, output $/MTok, short description)
MODEL_CATALOG: dict[str, tuple[float, float, str]] = {
    "claude-opus-5-5": (4.00, 20.00, "Claude Opus 5.5 - frontier reasoning, the default"),
    "claude-fable-5-1": (10.00, 50.00, "Claude Fable 5.1 - most capable, slowest, priciest"),
    "claude-sonnet-5-5": (2.00, 10.00, "Claude Sonnet 5.5 - fast and strong, half the Opus price"),
    "claude-haiku-5-5": (0.10, 0.50, "Claude Haiku 5.5 - fastest and cheapest"),
    "claude-opus-5": (5.00, 25.00, "Claude Opus 5 - previous Opus"),
    "claude-sonnet-5": (2.00, 10.00, "Claude Sonnet 5 - previous Sonnet"),
    "claude-haiku-4-5": (1.00, 5.00, "Claude Haiku 4.5 - previous Haiku"),
}

PRESETS = [
    {"id": "max", "label": "Maximum depth", "quick_model": "claude-opus-5-5",
     "deep_model": "claude-opus-5-5", "description": "Opus 5.5 for every agent (default)."},
    {"id": "balanced", "label": "Balanced", "quick_model": "claude-sonnet-5-5",
     "deep_model": "claude-opus-5-5",
     "description": "Sonnet 5.5 analysts and debaters, Opus 5.5 managers. Roughly half the cost."},
    {"id": "budget", "label": "Budget", "quick_model": "claude-haiku-5-5",
     "deep_model": "claude-sonnet-5-5",
     "description": "Haiku 5.5 analysts, Sonnet 5.5 managers. Cheapest; shallower reports."},
    {"id": "frontier", "label": "Frontier", "quick_model": "claude-opus-5-5",
     "deep_model": "claude-fable-5-1",
     "description": "Fable 5.1 managers on top of Opus 5.5 analysts. Most capable and most expensive."},
]


def _price(model: str) -> tuple[float, float] | None:
    if model in MODEL_CATALOG:
        return MODEL_CATALOG[model][:2]
    # Dated or suffixed IDs resolve to their family entry.
    for known, (pin, pout, _) in MODEL_CATALOG.items():
        if model.startswith(known):
            return pin, pout
    return None


def cost_usd(model: str, input_tokens: int, output_tokens: int,
             cache_read: int = 0, cache_write: int = 0) -> float | None:
    """``input_tokens`` excludes cached tokens, which are passed separately."""
    price = _price(model)
    if price is None:
        return None
    pin, pout = price
    return (input_tokens * pin + cache_read * pin * 0.1 + cache_write * pin * 1.25
            + output_tokens * pout) / 1_000_000


class UsageTracker(BaseCallbackHandler):
    """LangChain callback summing tokens per model across a run's parallel agents."""

    def __init__(self):
        self._lock = threading.Lock()
        self.by_model: dict[str, dict[str, int]] = defaultdict(
            lambda: {"calls": 0, "input": 0, "output": 0, "cache_read": 0, "cache_write": 0})

    def on_llm_end(self, response, **kwargs: Any) -> None:
        for gens in response.generations:
            for gen in gens:
                msg = getattr(gen, "message", None)
                usage = getattr(msg, "usage_metadata", None) if msg is not None else None
                if not usage:
                    continue
                meta = getattr(msg, "response_metadata", {}) or {}
                model = meta.get("model_name") or meta.get("model") or "unknown"
                details = usage.get("input_token_details") or {}
                cache_read = int(details.get("cache_read") or 0)
                cache_write = int(details.get("cache_creation") or 0)
                with self._lock:
                    row = self.by_model[model]
                    row["calls"] += 1
                    # LangChain's input_tokens include cached tokens; split them out.
                    row["input"] += max(int(usage.get("input_tokens") or 0) - cache_read - cache_write, 0)
                    row["output"] += int(usage.get("output_tokens") or 0)
                    row["cache_read"] += cache_read
                    row["cache_write"] += cache_write

    def add(self, model: str, input_tokens: int, output_tokens: int,
            cache_read: int = 0, cache_write: int = 0) -> None:
        with self._lock:
            row = self.by_model[model]
            row["calls"] += 1
            row["input"] += input_tokens
            row["output"] += output_tokens
            row["cache_read"] += cache_read
            row["cache_write"] += cache_write

    def summary(self) -> dict[str, Any]:
        with self._lock:
            models = {m: dict(v) for m, v in self.by_model.items()}
        total_cost, unknown = 0.0, False
        for m, v in models.items():
            c = cost_usd(m, v["input"], v["output"], v["cache_read"], v["cache_write"])
            v["cost_usd"] = c
            if c is None:
                unknown = True
            else:
                total_cost += c
        return {
            "models": models,
            "input_tokens": sum(v["input"] + v["cache_read"] + v["cache_write"] for v in models.values()),
            "output_tokens": sum(v["output"] for v in models.values()),
            "calls": sum(v["calls"] for v in models.values()),
            "cost_usd": round(total_cost, 4),
            "cost_incomplete": unknown,
        }

    def persist(self, db: Database, kind: str, ref_id: int | None) -> None:
        for model, v in self.summary()["models"].items():
            db.execute(
                "INSERT INTO usage_log(ts, kind, ref_id, model, input_tokens, output_tokens, "
                "cache_read_tokens, cache_write_tokens, cost_usd) VALUES(?,?,?,?,?,?,?,?,?)",
                (utcnow(), kind, ref_id, model, v["input"], v["output"], v["cache_read"],
                 v["cache_write"], v["cost_usd"]),
            )


def month_spend(db: Database) -> float:
    start = datetime.now(UTC).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    row = db.query_one("SELECT COALESCE(SUM(cost_usd), 0) AS s FROM usage_log WHERE ts >= ?",
                       (start.isoformat(timespec="seconds"),))
    return float(row["s"])


def usage_report(db: Database) -> dict[str, Any]:
    start = datetime.now(UTC).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    since = start.isoformat(timespec="seconds")
    by_model = db.query(
        "SELECT model, SUM(input_tokens + cache_read_tokens + cache_write_tokens) AS input_tokens, "
        "SUM(output_tokens) AS output_tokens, COALESCE(SUM(cost_usd), 0) AS cost_usd "
        "FROM usage_log WHERE ts >= ? GROUP BY model ORDER BY cost_usd DESC", (since,))
    by_kind = db.query(
        "SELECT kind, COALESCE(SUM(cost_usd), 0) AS cost_usd, COUNT(DISTINCT ref_id) AS items "
        "FROM usage_log WHERE ts >= ? GROUP BY kind", (since,))
    avg = db.query_one(
        "SELECT AVG(c) AS avg_cost FROM (SELECT ref_id, SUM(cost_usd) AS c FROM usage_log "
        "WHERE kind = 'run' GROUP BY ref_id ORDER BY ref_id DESC LIMIT 20)")
    all_time = db.query_one("SELECT COALESCE(SUM(cost_usd), 0) AS s FROM usage_log")
    return {
        "month_start": since,
        "month_cost_usd": round(sum(r["cost_usd"] for r in by_model), 4),
        "all_time_cost_usd": round(all_time["s"], 4),
        "avg_run_cost_usd": round(avg["avg_cost"], 4) if avg and avg["avg_cost"] is not None else None,
        "by_model": by_model,
        "by_kind": by_kind,
    }
