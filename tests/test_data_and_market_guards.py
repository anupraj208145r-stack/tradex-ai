from sqlalchemy import create_engine, inspect, text

from backend.db import apply_compatibility_migrations
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


def test_existing_risk_state_table_gets_all_missing_risk_columns_without_losing_rows():
    engine = create_engine("sqlite:///:memory:")
    try:
        with engine.begin() as conn:
            conn.exec_driver_sql("""
                CREATE TABLE user_risk_states (
                    user_id VARCHAR(64) PRIMARY KEY,
                    day_key VARCHAR(10) NOT NULL,
                    day_start_equity FLOAT NOT NULL
                )
            """)
            conn.execute(text("""
                INSERT INTO user_risk_states (user_id, day_key, day_start_equity)
                VALUES ('user-1', '2026-11-25', 1000.0)
            """))

        apply_compatibility_migrations(engine)

        columns = {column["name"] for column in inspect(engine).get_columns("user_risk_states")}
        assert {
            "day_key", "day_start_equity", "peak_equity", "daily_locked",
            "overall_failed", "challenge_passed", "lock_reason", "updated_at",
        }.issubset(columns)
        with engine.connect() as conn:
            row = conn.execute(text("""
                SELECT user_id, day_key, day_start_equity, peak_equity, daily_locked, overall_failed, challenge_passed, lock_reason, updated_at
                FROM user_risk_states WHERE user_id='user-1'
            """)).one()
        assert row.user_id == "user-1"
        assert row.day_key == "2026-11-25"
        assert row.day_start_equity == 1000.0
        assert row.peak_equity == 1000.0
        assert row.daily_locked is False
        assert row.overall_failed is False
        assert row.challenge_passed is False
        assert row.lock_reason == ""
        assert row.updated_at == 0

        # Re-running startup migrations must be safe and idempotent.
        apply_compatibility_migrations(engine)
    finally:
        engine.dispose()
