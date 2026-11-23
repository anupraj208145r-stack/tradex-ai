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

## Railway deployment (Free-plan test deployment)

This repository is prepared to run on Railway using its Dockerfile. The container listens on Railway's injected `PORT` (falling back to 8000 for local Docker). The API health endpoint is `/api/health`.

**Free-plan constraints are important:** Railway currently includes $1/month of resource usage, services can sleep after 5–10 minutes of outbound inactivity, and the free workspace has one persistent volume (0.5 GB). Free services are not guaranteed to stay online continuously. The one-time new-account trial is separate: $5 for 30 days. When that trial expires, free-plan usage limits apply. Review current [Railway Free plan documentation](https://docs.railway.com/pricing/free-plan) before deploying.

### Recommended free topology

Use one Railway project with exactly two services:

1. **PostgreSQL** — Railway's Postgres template. Keep its single persistent volume attached to this database service. This is where account, positions, closed trades, custom strategies, and candles are stored.
2. **TradeX AI app** — deploy this GitHub repository from branch `milestone/live-data-persistence`, using the repository Dockerfile. Do not attach a second volume to the app on the Free plan; it would exceed the one-volume project allowance. The app is stateless when `DATABASE_URL` points to PostgreSQL.

### Setup steps

1. Sign in at [Railway](https://railway.com/), create a project, and add a PostgreSQL database.
2. Add a service from GitHub and select `anupraj208145r-stack/tradex-ai`. Select branch `milestone/live-data-persistence`. Railway detects the root `Dockerfile`.
3. In the app service Variables, add:
   - `DATABASE_URL` = reference the Postgres service's `DATABASE_URL` variable using Railway's variable-reference picker (usually `${{Postgres.DATABASE_URL}}`; use the exact service name shown in your project).
   - `TWELVEDATA_API_KEY` = your private Twelve Data API key. This is optional for deployment, but required for live XAU/USD.
   - `CORS_ORIGINS` = your app's exact public origin if you use a separate frontend. For the bundled same-origin frontend, `http://localhost:8000` is not a production domain; set the Railway app origin or an appropriate exact origin.
   - `AUTO_RESUME_ON_RESTART` = `false`.
4. In app service Settings, generate a public domain. Set Healthcheck Path to `/api/health` and Healthcheck Timeout to 120 seconds.
5. Set the restart policy to `On Failure` (Free-plan maximum: 10 retries). Free plan does not support `Always`.
6. Deploy and inspect app logs. Check `https://YOUR-APP.up.railway.app/api/health` and confirm `mode=PAPER_ONLY`, `broker_connected=false`, and each feed's status.
7. Open the app domain. BTCUSD should connect to Coinbase. XAUUSD remains unavailable until the Twelve Data key and real-time entitlement are valid. Auto trading must remain off unless both feeds show fresh live readiness.

### Persistence and recovery verification

- Open a paper position, note the ID and account balance.
- Trigger an app redeploy/restart. Confirm the position and account balance remain in PostgreSQL.
- Confirm auto trading is disabled after restart (the safe default).
- Confirm the database service still has its persistent volume attached.
- Do not delete the Postgres volume or project when cleaning up deployments; that permanently destroys stored paper data.

### Cost and uptime expectations

The Free plan's $1 monthly usage credit is shared across the app, database, CPU, RAM, egress, and volume storage. A continuously active market-data WebSocket can keep a service awake and consume credits; when the monthly credit is exhausted, services stop until the next billing cycle or plan change. Free plan is therefore suitable for initial testing, not dependable 24/7 paper trading. For always-on operation, Railway currently points to Hobby at $5/month minimum usage (includes $5 usage credit); actual usage can exceed the minimum. Set a usage limit/alerts and inspect actual usage before leaving it unattended.

**Do not treat Railway's deployment healthcheck as continuous monitoring:** Railway uses it during deployment activation, not as an ongoing uptime monitor. Add an external uptime monitor and alerting before unattended operation.

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


## Supabase Auth setup (required before enabling sign-in)

This branch adds Supabase Auth in the browser and verifies every protected API bearer token against Supabase Auth's `/auth/v1/user` endpoint. The server never trusts a user ID supplied by the browser. Paper accounts, positions, closed trades, and custom strategy drafts are stored in separate user-keyed tables. The old single shared account tables are retained only for rollback and are not exposed through authenticated endpoints. Existing shared-account funds/positions are not copied to new users automatically.

1. Create a Supabase project.
2. In **Project Settings → API**, copy the Project URL and the publishable key (or legacy anon key). Put them in `frontend/supabase-config.js` as `TRADEX_SUPABASE_URL` and `TRADEX_SUPABASE_ANON_KEY`. These are public browser values. Never use the `service_role` key in frontend code.
3. In **Authentication → Providers**, enable **Phone** and configure a supported SMS provider in Supabase Auth. Set the SMS message template and rate limits. Confirm your SMS provider account has a valid sender/route and sufficient credits.
4. Enable **Google** provider and configure the OAuth Client ID and Client Secret from Google Cloud Console in Supabase. Add the Supabase callback URL shown in the provider setup to the Google OAuth authorized redirect URIs.
5. In **Authentication → URL Configuration**, add the exact production app URL and local development URL to Site URL / Redirect URLs. For Google OAuth, also add the exact app redirect URL.
6. Set Railway app variables `SUPABASE_URL` and `SUPABASE_ANON_KEY` to the same project URL and public anon/publishable key. Do not configure the service_role key.
7. Deploy the branch and test: email signup/confirmation, email+password login, Google OAuth, phone OTP, phone password set, email password recovery, and phone OTP password reset.
8. Verify that two separate Supabase users each receive their own initial virtual balance and cannot see or close each other's positions.

### Security notes

- All trading/account endpoints require a valid Supabase bearer token; market quotes, candles, and health remain public.
- WebSocket market sessions require a verified Supabase access token and receive only that user's paper-account snapshot.
- Server-side queries scope all paper records to the authenticated Supabase user ID. Do not expose the Railway database credentials or create direct browser access to these tables.
- Use HTTPS in production. Supabase public keys are expected in the browser; database credentials and provider secrets are not.
- Phone OTP password setup requires the user to enter a password in the Password field before completing OTP verification. Password reset for email uses Supabase's recovery email flow; phone password reset uses a fresh SMS OTP and then updates the password.
- Configure Supabase email confirmation and SMS rate limits to reduce account abuse. Enable CAPTCHA/Turnstile in Supabase Auth if your plan and provider support it.
- This app uses its own Railway/Postgres database for paper-trading records; Supabase Auth is the identity provider. Supabase database RLS policies do not apply to the separate Railway database. Isolation is enforced by verified server identity and user-scoped SQL queries.
