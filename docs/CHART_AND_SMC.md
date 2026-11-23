# Chart and multi-market SMC additions

This branch adds chart controls and deterministic paper-only SMC signal implementations.

## Chart
- Symbol navigation between XAUUSD and BTCUSD.
- Chart timeframe aggregation: 1m, 5m, 15m, 30m, 1h, 4h, 1d.
- Optional FVG and order-block overlays. The API uses three-candle imbalance detection for FVGs and a confirmed swing-break / last-opposing-candle heuristic for order blocks.
- Overlays are drawn as upper/lower horizontal zone boundaries using Lightweight Charts price lines. They are not native shaded rectangles.

## Paper strategy rules
- Liquidity sweep: take the prior 10-bar high/low and close back inside.
- BOS: closed candle closes beyond the prior 10-bar range.
- CHoCH: early reversal proxy based on a close breaking the previous opposing swing level.
- FVG retest: a three-candle gap is revisited and price closes back in the gap direction.
- Order-block retest: last opposing candle zone after a structure break is revisited.

These are transparent mechanical approximations for research and paper testing. They are not a claim that they reproduce Gautam Jha's complete proprietary or discretionary methodology. The Gautam Jha catalogue entries remain research-only until each exact rule is supported by a specific public lesson and independently tested.

## Multi-symbol operation
The backend market workers subscribe independently to XAUUSD and BTCUSD. Automatic signal evaluation is triggered separately on each symbol's closed 1-minute candle; changing the chart symbol or chart timeframe does not change the scanner subscriptions. The currently selected executable strategy is applied to both symbols.

## Data limitations
- BTCUSD uses Coinbase spot market data; XAUUSD requires a valid Twelve Data API key (TWELVEDATA_API_KEY).
- If the XAUUSD feed is not configured or fresh, the bot cannot trade XAUUSD. Feed health is displayed separately.
- Chart timeframe changes are presentation/analysis aggregation. The automatic execution signal engine continues to evaluate 1-minute candles.
- SMC overlays are approximate price zones; the chart currently draws boundary lines, not filled rectangles.
- This remains paper trading only. No broker/live order route is added.
