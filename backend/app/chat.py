"""Ask Claude follow-up questions about a finished analysis.

The run's reports go in a cached system prompt, so each follow-up question in
the same conversation only pays full price for the new turn.
"""

from __future__ import annotations

from typing import Any

import anthropic

from .agents import REPORT_ORDER, RunError, RunManager
from .db import Database, utcnow
from .settings_store import SettingsStore
from .usage import UsageTracker

REPORT_TITLES = {
    "market_report": "Market (technical) analysis",
    "sentiment_report": "Sentiment analysis",
    "news_report": "News analysis",
    "fundamentals_report": "Fundamentals analysis",
    "bull_history": "Bull researcher",
    "bear_history": "Bear researcher",
    "investment_plan": "Research manager's investment plan",
    "trader_investment_plan": "Trader's proposal",
    "aggressive_history": "Aggressive risk analyst",
    "conservative_history": "Conservative risk analyst",
    "neutral_history": "Neutral risk analyst",
    "final_trade_decision": "Portfolio manager's final decision",
}

SYSTEM_PROMPT = """You are the desk assistant of a paper-trading app built on TradingAgents, a \
multi-agent LLM trading research framework. The user is learning how trading bots reason and is \
trading simulated money only.

Below are the reports the agent team produced for {ticker} as of {date}. Answer the user's \
questions about them: explain the reasoning, point out where the agents disagreed, define \
jargon plainly, and say what would change the conclusion. Ground every claim in the reports and \
say so when they do not cover something. This is educational research, not financial advice; \
mention that once if the user asks what they should do with real money."""


class ChatService:
    def __init__(self, db: Database, runs: RunManager, settings: SettingsStore):
        self.db = db
        self.runs = runs
        self.settings = settings

    def history(self, run_id: int) -> list[dict[str, Any]]:
        return self.db.query("SELECT id, role, content, ts FROM chat_messages WHERE run_id = ? ORDER BY id",
                             (run_id,))

    def ask(self, run_id: int, question: str) -> dict[str, Any]:
        question = (question or "").strip()
        if not question:
            raise RunError("ask a question")
        if len(question) > 4000:
            raise RunError("question is too long")
        run = self.runs.get_run(run_id)
        if not run:
            raise RunError("no such run")
        if run["status"] != "completed":
            raise RunError("the analysis has not finished yet")
        settings = self.settings.get()
        self.runs.preflight(settings)

        reports = run["reports"]
        body = "\n\n".join(f"## {REPORT_TITLES[k]}\n\n{reports[k]}" for k in REPORT_ORDER if reports.get(k))
        system = [
            {"type": "text", "text": SYSTEM_PROMPT.format(ticker=run["ticker"], date=run["trade_date"])},
            {"type": "text", "text": f"# Reports\n\n{body}", "cache_control": {"type": "ephemeral"}},
        ]
        messages = [{"role": m["role"], "content": m["content"]} for m in self.history(run_id)[-20:]]
        messages.append({"role": "user", "content": question})

        model = settings.deep_model
        client = anthropic.Anthropic(api_key=self.settings.get_key("anthropic"), max_retries=3)
        kwargs: dict[str, Any] = {}
        # Server-side fallback re-runs a declined request on another model.
        if model.startswith(("claude-opus-5", "claude-fable-5-1", "claude-sonnet-5-5")):
            kwargs = {"betas": ["server-side-fallback-2026-07-01"], "fallbacks": "default"}
        try:
            response = client.beta.messages.create(
                model=model,
                max_tokens=16000,
                system=system,
                messages=messages,
                output_config={"effort": "low"},
                **kwargs,
            )
        except anthropic.AuthenticationError as exc:
            raise RunError("Anthropic rejected the API key; check it in Settings.") from exc
        except anthropic.RateLimitError as exc:
            raise RunError("Anthropic rate limit reached; try again in a minute.") from exc
        except anthropic.APIStatusError as exc:
            raise RunError(f"Anthropic API error {exc.status_code}: {exc.message}") from exc
        except anthropic.APIConnectionError as exc:
            raise RunError("Could not reach the Anthropic API.") from exc

        if response.stop_reason == "refusal":
            answer = "Claude declined to answer this question. Try rephrasing it."
        else:
            answer = "".join(b.text for b in response.content if b.type == "text").strip() or "(no answer)"

        usage = response.usage
        tracker = UsageTracker()
        tracker.add(response.model, usage.input_tokens or 0, usage.output_tokens or 0,
                    getattr(usage, "cache_read_input_tokens", 0) or 0,
                    getattr(usage, "cache_creation_input_tokens", 0) or 0)
        tracker.persist(self.db, "chat", run_id)

        now = utcnow()
        self.db.execute("INSERT INTO chat_messages(run_id, role, content, ts) VALUES(?,?,?,?)",
                        (run_id, "user", question, now))
        msg_id = self.db.execute("INSERT INTO chat_messages(run_id, role, content, ts) VALUES(?,?,?,?)",
                                 (run_id, "assistant", answer, utcnow()))
        return {"id": msg_id, "role": "assistant", "content": answer,
                "cost_usd": tracker.summary()["cost_usd"], "model": response.model}


def test_key(api_key: str, model: str) -> dict[str, Any]:
    """Prove the key works without spending tokens: look up the configured model."""
    client = anthropic.Anthropic(api_key=api_key, max_retries=1, timeout=20)
    try:
        info = client.models.retrieve(model)
    except anthropic.AuthenticationError:
        return {"ok": False, "message": "Anthropic rejected this API key."}
    except anthropic.NotFoundError:
        return {"ok": False, "message": f"The key works, but model {model} is not available to it."}
    except anthropic.APIStatusError as exc:
        return {"ok": False, "message": f"Anthropic API error {exc.status_code}: {exc.message}"}
    except anthropic.APIConnectionError:
        return {"ok": False, "message": "Could not reach the Anthropic API from the server."}
    return {"ok": True, "message": f"Key works. {getattr(info, 'display_name', model)} is available."}
