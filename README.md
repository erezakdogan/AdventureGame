# Paper Trader: TradingAgents on Claude, in your pocket

A mobile paper-trading app built on [TradingAgents](https://github.com/TauricResearch/TradingAgents), the
open-source multi-agent LLM trading framework from Tauric Research. Every agent runs on **Claude through your
own Anthropic API key**. You can watch a simulated trading firm research a stock, debate it and reach a call,
then trade that call on a **paper account with simulated money**. You can also hand Claude a pot of paper money as
an **AI fund** that trades a whole market on its own, and check every price forecast the bots make against what
the market really did in the **track record**.

> Research and education only. Nothing here is financial advice, and no real money or broker is involved.

```
 ┌──────────── phone ─────────────┐        ┌──────────────── your computer / server ────────────────┐
 │ Expo (React Native) app        │  HTTP  │ FastAPI backend  (backend/)                           │
 │  Portfolio · Markets · Agents  │ ─────► │  ├─ TradingAgents v0.7.0 graph ──► Anthropic API (Claude) │
 │  AI Fund · Track record        │ token  │  ├─ AI fund allocator (one Claude call per check)       │
 │  Settings · Replay · Orders    │        │  ├─ paper broker (SQLite): one wallet per fund         │
 └────────────────────────────────┘        │  ├─ forecast tracker: scores each call at its deadline │
                                           │  ├─ scheduler: orders, fund checks, scoring, autopilot │
                                           │  └─ Yahoo Finance prices (yfinance)                    │
                                           └────────────────────────────────────────────────────────┘
```

TradingAgents is a Python framework (LangGraph, pandas, yfinance), so it cannot run on a phone. The backend
runs it on your computer, or on any small server, and the app talks to it. Your API key stays on that machine.

---

## What TradingAgents is (assessment)

TradingAgents (Apache-2.0, ~v0.7.0, Oct 2026) models a trading firm as a LangGraph pipeline of LLM agents:

| Stage | Agents | What they produce |
|---|---|---|
| Analyst team (parallel) | Market (technicals), Sentiment (StockTwits/Reddit/news), News (company + macro, FRED, Polymarket), Fundamentals (SEC EDGAR as filed, Yahoo) | Four research reports, each built from tool calls against live data |
| Research team | Bull researcher vs bear researcher, N debate rounds; Research Manager judges | A structured investment plan (5-tier recommendation) |
| Trader | Trader | A concrete proposal: Buy/Hold/Sell, entry, stop-loss, sizing |
| Risk management | Aggressive, conservative and neutral analysts, N rounds | Stress tests of the proposal |
| Portfolio manager | Portfolio Manager (deep model) | **Final rating: Buy / Overweight / Hold / Underweight / Sell**, with an executive summary, price target and time horizon |

Strengths this app builds on:

- **Point-in-time data.** A run dated in the past only sees data published by then (SEC filings as filed,
  date-filtered news), so you can check its calls against what happened next. That is what Strategy Replay uses.
- **Memory and reflection.** Each decision is logged. Once its holding period has passed it is scored against
  the market, and a written lesson feeds later runs.
- **Portfolio awareness.** It accepts your holdings, so "Buy" can mean "add to" rather than "open".
- **Two model tiers.** A quick tier runs the analysts and debaters, and a deep tier runs the managers. Both run on
  Claude here.
- Works for US stocks, ETFs, crypto (`BTC-USD`) and most world markets (`7203.T`, `AZN.L`, `0700.HK`, `RELIANCE.NS`).

What it does not do, and this app adds: it never places orders or keeps an account. Its CLI prints a decision and
stops. There is no mobile or web UI, no cost tracking, no scheduling and no order execution. Runs are also
non-deterministic: the same ticker and date can produce different calls.

---

## Quick start

### 1. Start the backend

Requirements: Python 3.11+ and git.

```bash
cd backend
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python -m app
```

It prints what the phone needs:

```
  Server URL   : http://192.168.1.23:8000
  Access token : 3kY9…
```

Or with Docker, from the repo root: `docker compose up --build`. The token is in the container log and in the
`/data/access_token.txt` volume. You can also set your own with `PAPERTRADER_TOKEN=...`.

### 2. Run the app on your phone

Requirements: Node 20+ and the **Expo Go** app (App Store / Google Play).

```bash
cd mobile
npm install
npx expo start
```

Scan the QR code with your camera (iOS) or Expo Go (Android). The phone must be on the same Wi-Fi as the
computer. `npx expo start --tunnel` works across networks, and `npx expo start --web` runs the app in a browser.

### 3. Connect and add your Anthropic key

1. In the app, enter the **Server URL** and **Access token**.
2. Go to **Settings → Anthropic API key**, paste your key (`sk-ant-…`, from console.anthropic.com), then tap
   **Save & test**. The test only looks up the model and spends no tokens.
3. Optional: add a free [FRED](https://fred.stlouisfed.org/docs/api/api_key.html) key for macro data.

You can also put `ANTHROPIC_API_KEY=...` in the backend's environment instead.

---

## Using the app

| Tab / screen | What you can do |
|---|---|
| **Portfolio** | Account value, all-time and daily P&L, equity curve, positions with live P&L. Buttons to **Orders & trades** and **Track record** |
| **Markets** | Watchlist with live quotes. Tap a ticker for a price chart (1D–5Y), your position, a manual order ticket (market/limit/stop, in shares or dollars) and **Run AI analysis** |
| **Agents** | Start an analysis: ticker, date (today, or a past date to test the agents), which analysts, debate depth, model preset, auto-trade on/off. Lists every run with live progress |
| **Analysis** (tap a run) | The firm at work: each team lights up as its agents finish; a live log of tool calls (`get_stock_data(...)`, `get_news(...)`); every report (technicals, sentiment, news, fundamentals, bull, bear, research manager, trader, the three risk analysts, final decision); the **paper order** sized for your account, with an **Execute** button and optional quantity override; **Ask Claude** follow-up chat about the reports |
| **Strategy replay** | Let the agents trade a stretch of the past (for example every 7 days for two months) on a separate simulated account. You get an equity curve vs buy-and-hold, drawdown and every decision |
| **AI Fund** | Create funds that Claude manages on its own: type the paper money, pick markets and a trading frequency. Each fund page shows equity vs a benchmark, holdings, win rate, drawdown, Claude cost, forecast accuracy, and every trading check with Claude's reasoning per ticker (see below) |
| **Track record** | Every forecast from analyses and funds: entry → target → deadline, live progress while open, and accuracy, precision, target hit and direction once scored (see below) |
| **Orders & trades** | Waiting limit/stop orders (cancel them), order history with who placed each one (you, agents, autopilot, agent stop), trades with realized P&L |
| **Settings** | API keys, Claude usage and a monthly budget, models and effort, agent-team defaults, trading rules, simulated costs, **Autopilot**, account reset |

### How a decision becomes a paper trade

The Portfolio Manager's rating is sized against your account with rules you control in Settings:

| Rating | Action (defaults) |
|---|---|
| **Buy** | Grow the position to *max position size* (20% of equity) |
| **Overweight** | Grow it to 50% of that maximum |
| **Hold** | No trade |
| **Underweight** | Sell 50% of the position |
| **Sell** | Close the position. The account never shorts |
| REVIEW (no readable rating) | No trade. Read the report |

After a buy, the Trader's **stop-loss** is placed as a stop order on the whole position. Optionally, a
**take-profit** limit order is placed at the price target. When a position closes, its other exit orders are
cancelled. Orders pay the configured slippage (default 5 bps) and commission (default 0). Buys are capped by your
cash. Executing re-sizes the decision against the account and price at that moment.

### Autopilot (the "trading bot" mode)

Settings → Autopilot. Once a day at your chosen time (and time zone, weekdays only by default), the agent team
analyses every ticker on the list and, if allowed, trades the result. The backend must be running at that time.
To keep it always on, use a spare computer, a small VPS with Docker, or a home server.

### AI funds (Claude trades a whole market)

**AI Fund → Create an AI fund.** You choose:

- **Paper money**: any amount, typed in. Each fund has its **own wallet**, separate from your main account and
  from other funds, so you can run several side by side (for example the same markets as hourly vs swing). You
  can add more money later; deposits don't count as profit.
- **Markets to choose from**: presets (US mega caps, US ETFs, crypto, global, AI & chips) plus any extra tickers,
  up to 40.
- **Trading frequency**:

| Style | Checks | Forecast horizon | Notes |
|---|---|---|---|
| Hourly trading | every hour while the US market is open | 1–6 hours | flat before the close |
| Day trading | every 2 hours in the session | within the day | closes everything at 15:45 New York |
| Swing trading | daily, 10:00 New York | 2 days – 2 weeks | |
| Long-term | weekly, Monday 10:00 | 1–6 months | cheapest |
| Custom | your interval (15 min – 1 week) | any | |

  Crypto-only funds trade around the clock.
- **Risk limits**: max positions, max % per position, cash to keep in reserve, protective stop-loss, take-profit
  at Claude's forecast price.
- **Brain**: Opus 5.5, Sonnet 5.5 or Haiku 5.5; whether to read headlines; optionally a **full TradingAgents
  team check** on the top 1–3 new buys, where picks the team doesn't rate Buy/Overweight are dropped; and your
  own instructions ("prefer quality large caps, avoid earnings week").

On each check the fund:

1. Computes technicals for every ticker at the style's timeframe: % change, RSI, distance from moving averages
   and from highs and lows, volatility, volume.
2. Sends one structured request to Claude, acting as the fund's portfolio manager. The request includes the
   holdings, the fund's open forecasts and its scored track record, so it can calibrate. Claude returns a target
   weight per ticker plus an expected price, a horizon, a stop-loss, a confidence and its reasoning.
3. Rebalances toward those weights: sells first, then buys, within your limits.
4. Places the protective stop and take-profit orders.
5. Records a forecast for every trade.

Tap any check to see Claude's market view and its decision and reasoning per ticker.

### Track record: how accurate the bots' forecasts are

Every finished analysis records a forecast. The portfolio manager's rating gives the direction, its price
target the target, and its time horizon (for example "3-6 months") the deadline; without a horizon the default
is 5 trading days. Every AI-fund trade records the expected price and horizon Claude gave for it. When the
deadline passes, the server fetches the real price path (5-minute bars for short horizons, hourly or daily for
longer ones) and scores it:

| Measure | Meaning | Example: bought at 1.00, target 1.20 in 5 hours |
|---|---|---|
| **Accuracy** | How far the price got toward the target by the deadline, 0–100% | 1.12 at the deadline → **60%** |
| **Precision** | How close the deadline price landed to the target; overshooting counts against it too | 1.12 → 60%, 1.28 → 60%, 1.20 → 100% |
| **Target hit in time** | Did the target trade at any point before the deadline (even if the price fell back) | touched 1.21 at hour 2 → hit |
| **Best reach** | The furthest the price got toward the target | |
| **Direction right** | Did the price at least move the predicted way | |
| **Stopped out** | Did it trade through the stated stop-loss | |

Wrong-way moves score 0% accuracy. Sell calls are mirrored, so a fall toward the target counts. A Hold is
right if the price stays within a small band (1% intraday up to 5% over months). Open forecasts show live
progress ("33% of the way, 5 days left"). Averages are shown overall, per source (analyses or funds) and per
fund.

---

## Claude models and cost

Every analysis makes roughly 15–40 Claude calls, depending on analysts and debate rounds. The app counts tokens on
every call and shows an estimated cost per run, per month and per model. **Settings → Monthly budget** (default
$50) stops new runs once this month's estimate reaches it.

| Preset | Quick tier (analysts, debaters, trader) | Deep tier (managers) |
|---|---|---|
| Maximum depth (default) | `claude-opus-5-5` | `claude-opus-5-5` |
| Balanced | `claude-sonnet-5-5` | `claude-opus-5-5` |
| Budget | `claude-haiku-5-5` | `claude-sonnet-5-5` |
| Frontier | `claude-opus-5-5` | `claude-fable-5-1` |

You can mix any models and set **thinking effort** (low → max; default medium). One analysis costs anywhere from
a few cents (Budget) to a dollar or more (Maximum depth, several debate rounds). After a few runs the app shows
your actual average. The Anthropic Console has the exact bill.

The "Ask Claude" chat uses the deep-tier model at low effort. The reports go in a cached system prompt, so
follow-up questions are cheap.

An **AI fund check** is a single Claude call: well under a cent with Haiku 5.5, roughly $0.10–0.40 with Opus 5.5
depending on how many tickers it watches. An hourly Opus fund makes about 7 checks a day (roughly $1–3 a day). A
swing fund makes one, and a long-term fund one a week. The optional agent-team check adds one full analysis per
pick. Fund costs count toward the same monthly budget, and each fund page shows its own Claude cost.

---

## Security notes

- The backend refuses every request without the **access token** (generated on first start, stored in
  `backend/data/access_token.txt`).
- API keys are stored in `backend/data/secrets.json` (file mode 600) and are never sent back to the app. The app
  only shows a masked preview.
- The phone keeps the server URL and token in the OS secure store (Keychain/Keystore).
- The server speaks plain HTTP for LAN use. To reach it from outside your network, put it behind HTTPS (a
  reverse proxy, or a private network such as Tailscale) instead of opening the port to the internet.

## Limitations

- Prices come from Yahoo Finance and can be delayed. Paper orders fill at the last price even when the market is
  closed.
- Long-only cash account: no margin, shorting, options or dividends.
- Limit and stop orders are checked about once a minute while the backend runs, not tick by tick.
- Fund schedules follow US market hours (holidays aren't skipped). The backend must be running for funds to
  trade and for forecasts to be scored; missed deadlines are scored the next time it runs.
- LLM decisions vary from run to run and depend on the model and the data available that day. A short replay is
  one sample, not proof of skill.

---

## Development

```
backend/            FastAPI service wrapping TradingAgents
  app/agents.py       runs the TradingAgents graph, streams progress, records usage
  app/fund.py         AI funds: universe technicals, Claude allocation (structured output), rebalancing, schedules
  app/predictions.py  forecast log, horizon parsing, accuracy/precision/target-hit scoring, statistics
  app/broker.py       paper broker with one wallet per account (cash, positions, orders, equity curve)
  app/db.py           SQLite schema and the migration from the single-account version
  app/policy.py       rating → order sizing rules; parses the trader/PM reports
  app/replay.py       strategy replay over past dates vs buy-and-hold
  app/chat.py         "Ask Claude" (Anthropic SDK) and API-key test
  app/scheduler.py    waiting-order checks, equity snapshots, fund checks, forecast scoring, autopilot
  app/usage.py        token → cost accounting, model catalog and presets
  tests/              end-to-end API tests with a fake market and a fake agent graph (no tokens spent)
mobile/             Expo SDK 58 app (Expo Router, TypeScript)
  src/app/            screens (tabs, run/[id], symbol/[symbol], funds/…, track-record, replays/…)
  src/components/     UI kit, SVG line chart, markdown renderer, agent pipeline view
  src/lib/            API client, types, formatting, theme, session
legacy/adventure-game/   the original Java text adventure that used to live in this repo
```

```bash
# backend
cd backend && pip install -r requirements-dev.txt
pytest            # 60 tests: broker, sizing, runs, autopilot, replay, budget, funds, forecast scoring, migration
ruff check .

# mobile
cd mobile && npm install
npx tsc --noEmit && npx expo lint
```

To build installable apps (not just Expo Go), use EAS: `npx eas-cli@latest build -p android --profile preview`.
For a release build that talks to a plain-HTTP LAN server on Android, allow cleartext traffic with the
`expo-build-properties` plugin, or serve the backend over HTTPS.

## Credits

- [TradingAgents](https://github.com/TauricResearch/TradingAgents) by Tauric Research (Apache-2.0), used
  unmodified as a dependency. Paper: *TradingAgents: Multi-Agents LLM Financial Trading Framework*,
  arXiv:2412.20138.
- Claude models by Anthropic.
