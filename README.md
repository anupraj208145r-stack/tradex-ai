# TradeX AI — Live-feed Paper Trading milestone

A broker-free paper-trading terminal for XAUUSD and BTCUSD. This branch adds market-data adapters, persistent account/trade storage, and a restartable backend service.

> **Paper-only by design:** there is no broker SDK, broker credential, real order endpoint, deposit flow, withdrawal flow, or real-money execution.

## What's added in this milestone

- Coinbase BTC-USD market data via public WebSocket ticker feed and REST candle history.
- XAU/USD market data via Twelve Data REST history and price WebSocket.
- Explicit per-symbol feed health and last-error reporting. No synthetic-price fallback.
- Persistent PostgreSQL storage for account, positions, closed trades, candles, and custom strategy drafts.
- SQLite fallback for local development.
- Docker Compose with PostgreSQL, app restart policy, health checks, and a named persistent database volume.
- Reconnecting WebSocket clients with exponential backoff.
- One-minute candle aggregation and database persistence.
- Auto-paper trading gated on both market feeds being connected.
- Risk-based EMA 9/21 crossover demo with a 1% stop distance and 2R target.
- Automatic position exits when stop-loss or take-profit levels are touched.
- Auto trading is paused after restart by default; explicit opt-in is available after recovery testing.
- Dashboard feed status indicators for XAUUSD and BTCUSD.

## Market data providers

### BTCUSD

Uses Coinbase's public BTC-USD market data. The WebSocket ticker channel streams price updates; REST candles are used to initialize chart history. This is a BTC-USD spot reference price, not a CFD broker's BTCUSD contract quote.

References:
- [Coinbase Advanced Trade WebSocket feeds](https://help.coinbase.com/en/developer-platform/websocket-feeds/advanced-trade)
- [Coinbase Exchange WebSocket feeds](https://help.coinbase.com/en/developer-platform/websocket-feeds/exchange)

### XAUUSD

Uses Twelve Data's XAU/USD symbol. You must supply your own API key and have a plan that permits real-time WebSocket access and this instrument. Twelve Data currently documents WebSocket access starting with its Pro plan; verify the current plan, symbol entitlement, and data licence before subscribing. WebSocket usage consumes credits.

References:
- [Twelve Data WebSocket documentation](https://twelvedata.com/docs/websocket/websocket-getting-started)
- [Twelve Data WebSocket access and plans](https://support.twelvedata.com/en/articles/5609168-introduction-to-twelve-data)
- [Twelve Data pricing](https://twelvedata.com/pricing)

**Important:** XAU/USD spot data is a market-data reference, not necessarily the same as any broker's XAUUSD CFD bid/ask. The current paper simulator does not yet model bid/ask spread, CFD contract size, swaps, commissions, or slippage. Do not interpret its P&L as broker-equivalent.

## Local setup (Windows PowerShell)

1. Install Python 3.12+ and Docker Desktop.
2. Clone this repository and create a local environment file:

```powershell
git clone https://github.com/anupraj208145r-stack/tradex-ai.git
cd tradex-ai
Copy-Item .env.example .env
```

3. Edit `.env` and set:
   - `POSTGRES_PASSWORD`: a long random password.
   - `TWELVEDATA_API_KEY`: your Twelve Data API key.
   - `CORS_ORIGINS`: your exact app origin(s).

4. Start the stack:

```powershell
docker compose up --build -d
docker compose logs -f app
```

5. Open http://localhost:8000

Health status: http://localhost:8000/api/health

To stop without deleting the database volume:

```powershell
docker compose down
```

To permanently delete the local paper database volume (destructive):

```powershell
docker compose down -v
```

## Without Docker (SQLite development mode)

```powershell
python -m venv .venv
.venv\\Scripts\\Activate.ps1
pip install -r requirements-dev.txt
$env:DATABASE_URL="sqlite:///./data/tradex.db"
uvicorn backend.main:app --reload
```

SQLite is suitable for local single-process development only. Use PostgreSQL for hosted deployments.

## Important environment variables

- `DATABASE_URL`: PostgreSQL URL for persistent deployments, SQLite URL for local tests.
- `TWELVEDATA_API_KEY`: required for XAU/USD feed.
- `CORS_ORIGINS`: comma-separated exact origins allowed by the API.
- `AUTO_RESUME_ON_RESTART`: defaults to false. Set true only after you have tested recovery, alerting, and market-feed readiness on your own host.

Never commit `.env` or API keys.

## API

- `GET /api/health` — engine, feed status, live readiness, and last provider errors.
- `GET /api/account` — persistent paper account, positions, and trade history.
- `POST /api/account/reset` — reset virtual balance and clear positions/history.
- `GET /api/quotes` — latest provider quotes.
- `GET /api/candles/{symbol}` — stored and current one-minute candles.
- `GET /api/strategies` — strategy catalogue and saved custom drafts.
- `POST /api/orders` — open a simulated paper position; rejected if no quote is available.
- `POST /api/positions/{position_id}/close` — close a paper position.
- `POST /api/auto` — start/stop the EMA 9/21 paper strategy. Both feeds must be connected.
- `POST /api/strategies/custom` — save a custom EMA draft (not executable yet).
- `WS /ws/market` — market/account push stream.

## Current limitations and safety

1. The catalogue still contains 67 records, but only EMA 9/21 is implemented as an auto strategy. Other entries are not executable.
2. Gautam Jha entries remain research placeholders. No claim is made that these are his complete strategies. Rules must be verified from public source material and translated into deterministic specifications before coding.
3. Custom strategies are persisted as drafts; there is not yet a general strategy compiler.
4. This is a single shared paper account, not a multi-user product. Authentication, user isolation, roles, and session management are not yet implemented.
5. The database uses SQLAlchemy `create_all` for this milestone. Add Alembic migrations before production schema changes.
6. Provider feed status means a WebSocket connection was established; it is not an SLA or guarantee of complete market coverage. Monitor timestamps and stale-feed conditions.
7. The current simulator uses last-traded/reference prices for fills. Spread, slippage, tick-size, contract size, financing, and trading-session behavior need instrument-specific modelling.
8. A continuously running process requires an always-on host, durable PostgreSQL, restart policy, secrets management, monitoring, and provider entitlement. A local laptop or serverless static deployment alone does not provide this.
9. No strategy should be described as profitable without reproducible backtests, realistic transaction costs, walk-forward analysis, and out-of-sample validation.

## Next milestones

- Bid/ask-aware execution simulator and symbol-specific contract metadata.
- Historical data backfill, timeframe aggregation, and stale-feed circuit breakers.
- General custom-strategy DSL/compiler and executable strategy test harness.
- Backtesting and walk-forward validation.
- Authentication, per-user accounts, audit trail, and admin controls.
- Production monitoring, alerting, backup/restore drills, Alembic migrations, and deployment hardening.

Educational software only. Not investment advice.
