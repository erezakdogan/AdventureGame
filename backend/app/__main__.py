"""Start the API: ``python -m app`` (add ``--port 8000`` or ``--host`` to change where it listens)."""

from __future__ import annotations

import argparse
import logging
import socket
import warnings

import uvicorn

from . import config


def _lan_ip() -> str:
    """The address a phone on the same Wi-Fi reaches this machine at."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        try:
            s.connect(("10.255.255.255", 1))
            return s.getsockname()[0]
        except OSError:
            return "127.0.0.1"


def main() -> None:
    parser = argparse.ArgumentParser(description="TradingAgents paper-trading API")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    # langchain-anthropic warns on every structured agent because current Claude
    # models reject forced tool choice; it handles that, so the warning is noise.
    warnings.filterwarnings("ignore", message="You are attempting to use structured output")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    token = config.load_access_token()
    url = f"http://{_lan_ip()}:{args.port}"
    bar = "=" * 64
    print(f"\n{bar}\n  TradingAgents Paper Trader API\n\n"
          f"  Server URL   : {url}\n  Access token : {token}\n"
          f"  Data folder  : {config.DATA_DIR}\n\n"
          f"  Enter both in the app's connection screen.\n{bar}\n", flush=True)
    uvicorn.run("app.main:app", host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
