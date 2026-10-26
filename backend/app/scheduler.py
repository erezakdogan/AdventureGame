"""Background loop: works waiting orders, records the equity curve, and runs autopilot.

Autopilot is the "trading bot" mode: once a day at your chosen time it has the
agent team analyse every ticker on its list and, if allowed, trades the result
on the paper account.
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .agents import RunError, RunManager
from .broker import PaperBroker
from .market import MarketDataError
from .settings_store import SettingsStore

logger = logging.getLogger(__name__)

TICK_SECONDS = 15


class Scheduler:
    def __init__(self, broker: PaperBroker, runs: RunManager, settings: SettingsStore):
        self.broker = broker
        self.runs = runs
        self.settings = settings
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_order_check = 0.0
        self.last_autopilot_message: str | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._loop, daemon=True, name="scheduler")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        while not self._stop.wait(TICK_SECONDS):
            try:
                self.tick()
            except Exception:
                logger.exception("scheduler tick failed")

    def tick(self, now: datetime | None = None) -> None:
        settings = self.settings.get()
        if time.monotonic() - self._last_order_check >= settings.order_check_seconds:
            self._last_order_check = time.monotonic()
            try:
                for order in self.broker.process_open_orders():
                    logger.info("filled waiting order %s %s %s", order["id"], order["side"], order["symbol"])
            except MarketDataError as exc:
                logger.info("order check skipped: %s", exc)
            if self.broker.positions():
                self.broker.snapshot()
        self.autopilot_due(now)

    def autopilot_due(self, now: datetime | None = None) -> list[int]:
        """Start today's autopilot runs if it is time. Returns the run IDs started."""
        ap = self.settings.get().autopilot
        if not ap.enabled or not ap.tickers:
            return []
        try:
            tz = ZoneInfo(ap.timezone)
        except (ZoneInfoNotFoundError, ValueError):
            tz = ZoneInfo("UTC")
        local = (now or datetime.now(tz)).astimezone(tz)
        today = local.date().isoformat()
        if ap.last_run_date == today:
            return []
        if ap.weekdays_only and local.weekday() >= 5:
            return []
        if local.strftime("%H:%M") < ap.run_time:
            return []

        # Mark the day first so a failure cannot retry every tick and burn the budget.
        self.settings.update({"autopilot": {"last_run_date": today}})
        started, problems = [], []
        for ticker in ap.tickers:
            try:
                run = self.runs.create_run(ticker, auto_execute=ap.auto_execute, source="autopilot")
                started.append(run["id"])
            except (RunError, MarketDataError, ValueError) as exc:
                problems.append(f"{ticker}: {exc}")
        self.last_autopilot_message = (
            f"{today}: started {len(started)} run(s)" + (f"; skipped {'; '.join(problems)}" if problems else ""))
        logger.info("autopilot %s", self.last_autopilot_message)
        return started
