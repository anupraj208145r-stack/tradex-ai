from backend.main import (
    legacy_account_is_untouched,
    market_candle_is_valid,
    sanitize_market_candles,
)


def test_legacy_migration_recognizes_both_default_account_sizes():
    assert legacy_account_is_untouched(1000, 1000, 0, False, False)
    assert legacy_account_is_untouched(10000, 10000, 0, False, False)


def test_legacy_migration_never_overwrites_an_account_with_activity():
    assert not legacy_account_is_untouched(950, 1000, -50, False, False)
    assert not legacy_account_is_untouched(1000, 1000, 0, True, False)
    assert not legacy_account_is_untouched(1000, 1000, 0, False, True)


def test_gold_chart_rejects_abnormal_one_minute_spike():
    valid = {"time": 100, "open": 3556, "high": 3560, "low": 3552, "close": 3557}
    spike = {"time": 160, "open": 3556, "high": 3625, "low": 3554, "close": 3556}
    assert market_candle_is_valid("XAUUSD", valid)
    assert not market_candle_is_valid("XAUUSD", spike)


def test_candle_sanitizer_deduplicates_and_sorts_valid_rows():
    rows = [
        {"time": 120, "open": 3556, "high": 3560, "low": 3552, "close": 3557},
        {"time": 60, "open": 3554, "high": 3558, "low": 3550, "close": 3556},
        {"time": 180, "open": 3557, "high": 3625, "low": 3556, "close": 3558},
        {"time": 120, "open": 3556, "high": 3561, "low": 3552, "close": 3559},
    ]
    clean = sanitize_market_candles("XAUUSD", rows)
    assert [row["time"] for row in clean] == [60, 120]
    assert clean[-1]["close"] == 3559
