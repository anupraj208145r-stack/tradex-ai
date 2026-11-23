# TradeX AI paper risk guard

## Status
This is a conservative internal paper-simulation overlay, not a certified SharkFunded rules profile and not a live broker risk engine.

The likely firm match is SharkFunded, but the exact programme and phase have not been confirmed. Programme rules differ.

## Default internal limits for a $10,000 paper account
- Risk per trade: 0.25% ($25)
- Daily loss stop: 2% of day-start reference ($200 on a $10,000 day start)
- Static maximum drawdown: 3% of initial balance (equity floor $9,700)
- Maximum aggregate floating loss: 1% of initial balance ($100); hard lock and flatten all paper positions
- Maximum aggregate open stop risk: 0.50% ($50)
- Maximum open positions: 3 total, 2 per symbol
- Stop adding to a symbol while an existing position on that symbol is losing
- Pause after 3 consecutive losing closed trades
- Minimum reward/risk: 1.5R
- Daily reset clock: UTC (not verified against the firm's broker-server reset)

## Enforcement
Both manual and automated paper entries are checked. Daily locks disable automation and block new orders until UTC day rollover or explicit paper-account reset. Hard locks persist across restarts and flatten open paper positions at the next market tick. An explicit paper-account reset starts a new simulation and clears the lock history.

## Important modelling limits
TradeX AI's current P&L model is price-difference multiplied by quantity. It does not yet model instrument-specific contract sizes, lot multipliers, tick values, commissions, spread, swaps, gaps, or realistic slippage. Therefore the dollar risk figures are simulator-unit estimates, not broker-accurate funded-account risk.

Before using any real prop evaluation, confirm the exact programme/phase, broker server daily reset, news rules, weekend holding, max floating loss applicability, and EA/bot permission in the firm's own account dashboard and written terms.
