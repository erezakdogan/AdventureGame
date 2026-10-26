"""User settings (models, agent depth, trading rules, autopilot) and API keys.

Settings live in the database as one JSON document. API keys are kept apart in
a 0600 file in the data dir and are never returned by the API, only a masked
preview, so a lost phone does not leak the key.
"""

from __future__ import annotations

import copy
import json
import os
import threading
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, field_validator

from .db import Database, dumps, loads

ANALYST_KEYS = ("market", "social", "news", "fundamentals")
EFFORT_LEVELS = ("low", "medium", "high", "xhigh", "max")

# API keys the app can hold, and the environment variable TradingAgents reads
# each one from.
KEY_ENV = {
    "anthropic": "ANTHROPIC_API_KEY",
    "fred": "FRED_API_KEY",
    "alpha_vantage": "ALPHA_VANTAGE_API_KEY",
}


class AutopilotSettings(BaseModel):
    enabled: bool = False
    tickers: list[str] = Field(default_factory=list)
    run_time: str = "15:30"  # HH:MM in `timezone`
    timezone: str = "America/New_York"
    weekdays_only: bool = True
    auto_execute: bool = True
    last_run_date: str | None = None

    @field_validator("run_time")
    @classmethod
    def _hhmm(cls, v: str) -> str:
        hh, _, mm = v.partition(":")
        if not (hh.isdigit() and mm.isdigit() and 0 <= int(hh) < 24 and 0 <= int(mm) < 60):
            raise ValueError("run_time must be HH:MM")
        return f"{int(hh):02d}:{int(mm):02d}"

    @field_validator("tickers")
    @classmethod
    def _upper(cls, v: list[str]) -> list[str]:
        return list(dict.fromkeys(t.strip().upper() for t in v if t.strip()))[:20]


class Settings(BaseModel):
    # Models. Both tiers default to Claude Opus 5.5; presets in /api/models trade
    # cost for depth on the quick tier, which makes most of a run's calls.
    deep_model: str = "claude-opus-5-5"
    quick_model: str = "claude-opus-5-5"
    effort: str | None = "medium"
    output_language: str = "English"

    # Agent team
    analysts: list[str] = Field(default_factory=lambda: list(ANALYST_KEYS))
    max_debate_rounds: int = Field(default=1, ge=1, le=5)
    max_risk_rounds: int = Field(default=1, ge=1, le=5)
    share_portfolio: bool = True

    # Turning a decision into an order
    auto_execute: bool = False
    max_position_pct: float = Field(default=20.0, gt=0, le=100)
    overweight_fraction: float = Field(default=0.5, gt=0, le=1)
    underweight_trim: float = Field(default=0.5, gt=0, le=1)
    use_stop_loss: bool = True
    use_take_profit: bool = False
    allow_fractional: bool = True

    # Simulated execution costs
    commission_per_trade: float = Field(default=0.0, ge=0)
    commission_bps: float = Field(default=0.0, ge=0, le=500)
    slippage_bps: float = Field(default=5.0, ge=0, le=500)

    # Spend guard and housekeeping
    monthly_budget_usd: float | None = Field(default=50.0, ge=0)
    max_concurrent_runs: int = Field(default=1, ge=1, le=4)
    order_check_seconds: int = Field(default=60, ge=15, le=3600)

    autopilot: AutopilotSettings = Field(default_factory=AutopilotSettings)

    @field_validator("analysts")
    @classmethod
    def _analysts(cls, v: list[str]) -> list[str]:
        picked = [a for a in ANALYST_KEYS if a in v]
        if not picked:
            raise ValueError(f"pick at least one analyst from {', '.join(ANALYST_KEYS)}")
        return picked

    @field_validator("effort")
    @classmethod
    def _effort(cls, v: str | None) -> str | None:
        if v in (None, "", "default"):
            return None
        if v not in EFFORT_LEVELS:
            raise ValueError(f"effort must be one of {', '.join(EFFORT_LEVELS)}")
        return v

    @field_validator("deep_model", "quick_model")
    @classmethod
    def _model(cls, v: str) -> str:
        v = v.strip()
        if not v.startswith("claude-"):
            raise ValueError("model must be a Claude model ID, e.g. claude-opus-5-5")
        return v


def _mask(key: str) -> str:
    return f"{key[:7]}…{key[-4:]}" if len(key) > 14 else "set"


class SettingsStore:
    def __init__(self, db: Database, secrets_path: Path):
        self.db = db
        self.secrets_path = secrets_path
        self._lock = threading.Lock()
        self._apply_keys_to_env()

    # -- settings -------------------------------------------------------------

    def get(self) -> Settings:
        row = self.db.query_one("SELECT value FROM settings WHERE key = 'settings'")
        data = loads(row["value"], {}) if row else {}
        try:
            return Settings.model_validate(data)
        except ValueError:
            # A stored document from an older version that no longer validates
            # falls back to defaults field by field rather than locking the app.
            base = Settings().model_dump()
            for k, v in data.items():
                trial = {**base, k: v}
                try:
                    Settings.model_validate(trial)
                    base = trial
                except ValueError:
                    continue
            return Settings.model_validate(base)

    def save(self, settings: Settings) -> Settings:
        self.db.execute(
            "INSERT INTO settings(key, value) VALUES('settings', ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (dumps(settings.model_dump()),),
        )
        return settings

    def update(self, patch: dict[str, Any]) -> Settings:
        """Merge a partial update (nested for autopilot) and validate the result."""
        with self._lock:
            current = self.get().model_dump()
            merged = copy.deepcopy(current)
            for k, v in patch.items():
                if k == "autopilot" and isinstance(v, dict):
                    merged["autopilot"] = {**merged["autopilot"], **v}
                else:
                    merged[k] = v
            return self.save(Settings.model_validate(merged))

    # -- API keys ---------------------------------------------------------------

    def _read_secrets(self) -> dict[str, str]:
        if not self.secrets_path.exists():
            return {}
        try:
            data = json.loads(self.secrets_path.read_text(encoding="utf-8"))
            return {k: v for k, v in data.items() if isinstance(v, str) and v}
        except (OSError, json.JSONDecodeError):
            return {}

    def _write_secrets(self, data: dict[str, str]) -> None:
        tmp = self.secrets_path.with_suffix(".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh)
        os.replace(tmp, self.secrets_path)

    def _apply_keys_to_env(self) -> None:
        """Expose stored keys to TradingAgents, which reads them from the environment.

        A key exported before start-up wins over a stored one only until the user
        saves a key in the app.
        """
        for name, value in self._read_secrets().items():
            env = KEY_ENV.get(name)
            if env:
                os.environ[env] = value

    def set_key(self, name: str, value: str | None) -> None:
        if name not in KEY_ENV:
            raise ValueError(f"unknown key {name!r}")
        with self._lock:
            data = self._read_secrets()
            if value:
                data[name] = value.strip()
                os.environ[KEY_ENV[name]] = value.strip()
            else:
                data.pop(name, None)
                os.environ.pop(KEY_ENV[name], None)
            self._write_secrets(data)

    def get_key(self, name: str) -> str | None:
        return os.environ.get(KEY_ENV[name]) or None

    def key_status(self) -> dict[str, dict[str, Any]]:
        out = {}
        for name in KEY_ENV:
            value = self.get_key(name)
            out[name] = {"set": bool(value), "preview": _mask(value) if value else None}
        return out
