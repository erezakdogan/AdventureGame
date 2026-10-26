"""SQLite storage shared by the broker, the agent runs and the settings.

One connection guarded by a re-entrant lock: the app serves a single user, and
the agent threads write rarely, so serialising access keeps it simple and safe.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 2

SCHEMA = """
CREATE TABLE IF NOT EXISTS account (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL DEFAULT 'Main',
    kind TEXT NOT NULL DEFAULT 'main',
    starting_cash REAL NOT NULL,
    cash REAL NOT NULL,
    currency TEXT NOT NULL DEFAULT 'USD',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS positions (
    account_id INTEGER NOT NULL DEFAULT 1,
    symbol TEXT NOT NULL,
    quantity REAL NOT NULL,
    avg_price REAL NOT NULL,
    opened_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (account_id, symbol)
);

CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id INTEGER NOT NULL DEFAULT 1,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    quantity REAL NOT NULL,
    order_type TEXT NOT NULL,
    limit_price REAL,
    stop_price REAL,
    status TEXT NOT NULL,
    source TEXT NOT NULL,
    run_id INTEGER,
    note TEXT,
    reject_reason TEXT,
    fill_price REAL,
    commission REAL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    filled_at TEXT
);
CREATE INDEX IF NOT EXISTS orders_status ON orders(status);
CREATE INDEX IF NOT EXISTS orders_account ON orders(account_id, id);

CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id INTEGER NOT NULL DEFAULT 1,
    order_id INTEGER NOT NULL,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    quantity REAL NOT NULL,
    price REAL NOT NULL,
    commission REAL NOT NULL,
    realized_pnl REAL,
    source TEXT NOT NULL,
    run_id INTEGER,
    ts TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS trades_account ON trades(account_id, id);

CREATE TABLE IF NOT EXISTS equity_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id INTEGER NOT NULL DEFAULT 1,
    ts TEXT NOT NULL,
    equity REAL NOT NULL,
    cash REAL NOT NULL,
    benchmark REAL
);
CREATE INDEX IF NOT EXISTS equity_account ON equity_snapshots(account_id, id);

-- A forecast the bot made: "TICKER goes from entry to target by due_at".
-- Scored once due_at has passed (see predictions.py).
CREATE TABLE IF NOT EXISTS predictions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    source TEXT NOT NULL,
    run_id INTEGER,
    fund_id INTEGER,
    cycle_id INTEGER,
    ticker TEXT NOT NULL,
    direction TEXT NOT NULL,
    rating TEXT,
    entry_price REAL NOT NULL,
    target_price REAL,
    stop_price REAL,
    horizon_text TEXT,
    horizon_hours REAL NOT NULL,
    due_at TEXT NOT NULL,
    confidence REAL,
    rationale TEXT,
    status TEXT NOT NULL DEFAULT 'open',
    scored_at TEXT,
    price_at_due REAL,
    return_pct REAL,
    progress_pct REAL,
    accuracy_pct REAL,
    peak_progress_pct REAL,
    hit_target INTEGER,
    hit_target_at TEXT,
    hit_stop INTEGER,
    direction_correct INTEGER,
    target_error_pct REAL,
    score REAL,
    note TEXT
);
CREATE INDEX IF NOT EXISTS predictions_status ON predictions(status, due_at);
CREATE INDEX IF NOT EXISTS predictions_fund ON predictions(fund_id, id);

CREATE TABLE IF NOT EXISTS funds (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    account_id INTEGER NOT NULL,
    style TEXT NOT NULL,
    config TEXT NOT NULL,
    status TEXT NOT NULL,
    benchmark_symbol TEXT,
    benchmark_start REAL,
    created_at TEXT NOT NULL,
    last_cycle_at TEXT,
    next_cycle_at TEXT,
    last_error TEXT
);

CREATE TABLE IF NOT EXISTS fund_cycles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fund_id INTEGER NOT NULL,
    trigger TEXT NOT NULL,
    status TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    equity_before REAL,
    equity_after REAL,
    market_view TEXT,
    decisions TEXT NOT NULL DEFAULT '[]',
    orders TEXT NOT NULL DEFAULT '[]',
    run_ids TEXT NOT NULL DEFAULT '[]',
    usage TEXT NOT NULL DEFAULT '{}',
    error TEXT
);
CREATE INDEX IF NOT EXISTS fund_cycles_fund ON fund_cycles(fund_id, id);

CREATE TABLE IF NOT EXISTS watchlist (
    symbol TEXT PRIMARY KEY,
    added_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    trade_date TEXT NOT NULL,
    asset_type TEXT NOT NULL,
    status TEXT NOT NULL,
    source TEXT NOT NULL,
    replay_id INTEGER,
    auto_execute INTEGER NOT NULL DEFAULT 0,
    options TEXT NOT NULL,
    agents TEXT NOT NULL DEFAULT '{}',
    reports TEXT NOT NULL DEFAULT '{}',
    rating TEXT,
    decision TEXT,
    proposal TEXT,
    executed_order_ids TEXT,
    usage TEXT NOT NULL DEFAULT '{}',
    error TEXT,
    created_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT
);
CREATE INDEX IF NOT EXISTS runs_status ON runs(status);

CREATE TABLE IF NOT EXISTS run_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL,
    ts TEXT NOT NULL,
    agent TEXT,
    kind TEXT NOT NULL,
    text TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS run_events_run ON run_events(run_id, id);

CREATE TABLE IF NOT EXISTS chat_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    ts TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS replays (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    start_date TEXT NOT NULL,
    end_date TEXT NOT NULL,
    every_n_days INTEGER NOT NULL,
    starting_cash REAL NOT NULL,
    status TEXT NOT NULL,
    steps TEXT NOT NULL DEFAULT '[]',
    summary TEXT,
    error TEXT,
    created_at TEXT NOT NULL,
    finished_at TEXT
);

CREATE TABLE IF NOT EXISTS usage_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    kind TEXT NOT NULL,
    ref_id INTEGER,
    model TEXT NOT NULL,
    input_tokens INTEGER NOT NULL,
    output_tokens INTEGER NOT NULL,
    cache_read_tokens INTEGER NOT NULL DEFAULT 0,
    cache_write_tokens INTEGER NOT NULL DEFAULT 0,
    cost_usd REAL
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def utcnow() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class Database:
    def __init__(self, path: Path | str):
        self.path = str(path)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._migrate()
        self._conn.executescript(SCHEMA)
        self._conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

    def _columns(self, table: str) -> set[str]:
        return {r[1] for r in self._conn.execute(f"PRAGMA table_info({table})")}

    def _migrate(self) -> None:
        """Bring a version-1 database (one account) up to the multi-account schema."""
        if not self._columns("account") or "kind" in self._columns("account"):
            return  # fresh database, or already migrated
        c = self._conn
        c.executescript("""
            BEGIN;
            ALTER TABLE account RENAME TO account_v1;
            CREATE TABLE account (
                id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL DEFAULT 'Main',
                kind TEXT NOT NULL DEFAULT 'main', starting_cash REAL NOT NULL, cash REAL NOT NULL,
                currency TEXT NOT NULL DEFAULT 'USD', created_at TEXT NOT NULL);
            INSERT INTO account(id, starting_cash, cash, currency, created_at)
                SELECT id, starting_cash, cash, currency, created_at FROM account_v1;
            DROP TABLE account_v1;
            ALTER TABLE positions RENAME TO positions_v1;
            CREATE TABLE positions (
                account_id INTEGER NOT NULL DEFAULT 1, symbol TEXT NOT NULL, quantity REAL NOT NULL,
                avg_price REAL NOT NULL, opened_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                PRIMARY KEY (account_id, symbol));
            INSERT INTO positions(account_id, symbol, quantity, avg_price, opened_at, updated_at)
                SELECT 1, symbol, quantity, avg_price, opened_at, updated_at FROM positions_v1;
            DROP TABLE positions_v1;
            ALTER TABLE orders ADD COLUMN account_id INTEGER NOT NULL DEFAULT 1;
            ALTER TABLE trades ADD COLUMN account_id INTEGER NOT NULL DEFAULT 1;
            ALTER TABLE equity_snapshots ADD COLUMN account_id INTEGER NOT NULL DEFAULT 1;
            ALTER TABLE equity_snapshots ADD COLUMN benchmark REAL;
            COMMIT;
        """)

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """Hold the lock and commit the enclosed statements together."""
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                yield self._conn
            except BaseException:
                self._conn.execute("ROLLBACK")
                raise
            self._conn.execute("COMMIT")

    def execute(self, sql: str, params: tuple | dict = ()) -> int:
        """Run one statement; returns the last inserted row id."""
        with self._lock:
            cur = self._conn.execute(sql, params)
            return cur.lastrowid

    def query(self, sql: str, params: tuple | dict = ()) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(row) for row in self._conn.execute(sql, params).fetchall()]

    def query_one(self, sql: str, params: tuple | dict = ()) -> dict[str, Any] | None:
        rows = self.query(sql, params)
        return rows[0] if rows else None

    def close(self) -> None:
        with self._lock:
            self._conn.close()


def dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def loads(value: str | None, default: Any = None) -> Any:
    if value is None or value == "":
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default
