import math
from backend.strategy_engine import SUPPORTED_STRATEGIES, atr_value, signal_for

def sample_candles(count=180):
    rows=[]
    previous=100.0
    for i in range(count):
        close=100 + i*0.08 + math.sin(i/4)*2 + math.sin(i/11)*1.2
        open_price=previous
        rows.append({
            "time": 1_700_000_000 + i*60,
            "open": open_price,
            "high": max(open_price, close) + 0.6 + abs(math.sin(i))*0.2,
            "low": min(open_price, close) - 0.6 - abs(math.cos(i))*0.2,
            "close": close,
            "volume": 1000 + (i % 13)*25,
        })
        previous=close
    return rows

def test_atr_is_positive_for_valid_market_candles():
    assert atr_value(sample_candles(), 14) > 0

def test_every_enabled_strategy_returns_only_a_valid_signal_or_none():
    candles=sample_candles()
    for strategy_id in SUPPORTED_STRATEGIES:
        signal=signal_for(strategy_id,candles)
        assert signal in (None,"BUY","SELL"), strategy_id

def test_strategy_catalog_matches_implemented_engine():
    import json
    from pathlib import Path
    catalog=json.loads((Path(__file__).parents[1]/"backend"/"strategies.json").read_text())
    enabled={item["id"] for item in catalog if item["executable"]}
    assert enabled == SUPPORTED_STRATEGIES
