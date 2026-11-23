# TradeX AI — Paper Trading Starter

Responsive, broker-free paper-trading prototype for XAUUSD and BTCUSD.

> **Safety boundary:** this application is paper-only by design. It contains no broker SDK, live-order endpoint, deposit flow, withdrawal flow, or real-money execution path.

## Current build

- Responsive dashboard layout for desktop and mobile browsers.
- XAUUSD and BTCUSD simulated candlestick charts using Lightweight Charts.
- A $10,000 default virtual starting balance.
- Manual simulated BUY/SELL orders and manual position close.
- Editable/resettable paper balance.
- Open positions, unrealized P&L, realized P&L, and trade history.
- 67 strategy catalogue records.
- Auto-paper-trading starter implementation for the EMA 9/21 crossover (STR-001).
- Custom EMA strategy draft form.
- FastAPI backend and Dockerfile.

## Important limitations — read before use

1. **Prices are synthetic.** The starter generates demo prices in-process. They are not live XAUUSD or BTCUSD quotes. Do not use this feed to assess profitability or strategy quality.
2. **Only one automated strategy is implemented.** STR-001 is the initial EMA crossover starter. Most of the other catalogue entries are descriptive templates and are not yet executable.
3. **Gautam Jha entries are research placeholders.** They do not claim to reproduce or represent Gautam Jha's complete strategies. The source material must be reviewed and converted into explicit, deterministic rules before implementation. No paid/private material is included.
4. **Custom strategies are drafts.** The current form saves an EMA configuration in server memory; it does not yet compile a general-purpose strategy or run a custom strategy.
5. **State is in memory.** Balance, positions, history, and custom drafts are reset when the API process restarts. There is no database persistence or multi-user isolation.
6. **Prototype security only.** There is no authentication, authorization, audit log, hardened CORS policy, production rate-limiting, or production monitoring. Do not expose this prototype publicly with user data.
7. **Trading costs are not modelled.** Spread, slippage, commissions, swap/financing, contract specifications, market sessions, and realistic order-fill rules are not implemented.

## Run locally

Requires Python 3.10+.

```bash
python -m venv .venv

# Windows PowerShell
.venv\Scripts\Activate.ps1

# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt
uvicorn backend.main:app --reload
```

Open http://127.0.0.1:8000

API health check: http://127.0.0.1:8000/api/health

## Run with Docker

```bash
docker build -t tradex-ai .
docker run --rm -p 8000:8000 tradex-ai
```

Then open http://127.0.0.1:8000.

## API endpoints

- `GET /api/health` — reports PAPER_ONLY mode and demo-feed status.
- `GET /api/account` — account balance, equity, open positions, and history.
- `POST /api/account/reset` — reset paper balance and clear positions/history.
- `GET /api/quotes` — current synthetic demo quotes.
- `GET /api/candles/{symbol}` — simulator candles for XAUUSD or BTCUSD.
- `GET /api/strategies` — strategy catalogue.
- `POST /api/orders` — open a simulated manual position.
- `POST /api/positions/{position_id}/close` — close a simulated position.
- `POST /api/auto` — start/stop the paper auto engine.
- `POST /api/strategies/custom` — save a custom EMA draft.
- `WS /ws/market` — market/account message stream.

## Next engineering milestones

1. Select a licensed, reliable XAUUSD quote source and a clearly specified BTC/USD feed; keep credentials server-side.
2. Build robust candle aggregation and model bid/ask, spread, slippage, commissions, swaps, and instrument contract details.
3. Add database persistence, user authentication, per-user paper accounts, and immutable trade/audit events.
4. Implement a validated strategy DSL and custom strategy compiler.
5. Implement the strategy library one-by-one with unit tests and deterministic entry/exit logic.
6. Add historical backtesting, walk-forward validation, out-of-sample tests, realistic costs, and downloadable reports.
7. Harden deployment, add rate limits, secrets management, monitoring, and CI checks.

No strategy should be described as profitable without reproducible, out-of-sample evidence. This project is educational software, not investment advice.
