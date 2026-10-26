"""Process-level configuration, read from the environment once at start-up."""

from __future__ import annotations

import contextlib
import os
import secrets
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]

DATA_DIR = Path(os.getenv("PAPERTRADER_DATA_DIR") or BACKEND_ROOT / "data").resolve()
DATA_DIR.mkdir(parents=True, exist_ok=True)

TOKEN_PATH = DATA_DIR / "access_token.txt"
# Everything TradingAgents writes (reports, caches, its memory log) goes under
# DATA_DIR/tradingagents instead of ~/.tradingagents, so one folder holds the app.

APP_VERSION = "1.0.0"


def load_access_token() -> str:
    """The bearer token every API call must carry.

    PAPERTRADER_TOKEN wins; otherwise a random token is generated on first start
    and kept in the data dir, so the phone only has to be paired once. The server
    holds a paid API key, so it never runs open.
    """
    token = os.getenv("PAPERTRADER_TOKEN", "").strip()
    if token:
        return token
    if TOKEN_PATH.exists():
        stored = TOKEN_PATH.read_text(encoding="utf-8").strip()
        if stored:
            return stored
    token = secrets.token_urlsafe(24)
    TOKEN_PATH.write_text(token + "\n", encoding="utf-8")
    with contextlib.suppress(OSError):
        TOKEN_PATH.chmod(0o600)
    return token
