from backend.risk_engine import evaluate_rules


def base_state(**overrides):
    state = {
        "day_key": "2026-11-25",
        "daily_locked": False,
        "overall_failed": False,
        "challenge_passed": False,
        "lock_reason": "",
    }
    state.update(overrides)
    return state


def test_daily_loss_locks_account():
    result = evaluate_rules(starting_balance=1000, day_start_equity=1000,
        equity=980, state=base_state(), today="2026-11-25")
    assert result["status"] == "DAILY_LOCKED"
    assert result["daily_locked"] is True
    assert result["daily_loss_limit"] == 20


def test_daily_lock_automatically_clears_next_utc_day():
    result = evaluate_rules(starting_balance=1000, day_start_equity=980,
        equity=980, state=base_state(daily_locked=True,
        lock_reason="DAILY_LOSS_LIMIT_REACHED"), today="2026-11-26")
    assert result["status"] == "ACTIVE"
    assert result["daily_locked"] is False
    assert result["day_start_equity"] == 980
    assert result["lock_reason"] == ""


def test_overall_failure_does_not_clear_next_day():
    result = evaluate_rules(starting_balance=1000, day_start_equity=960,
        equity=940, state=base_state(overall_failed=True,
        lock_reason="MAX_OVERALL_LOSS_BREACHED"), today="2026-11-26")
    assert result["status"] == "FAILED"
    assert result["overall_failed"] is True


def test_profit_target_marks_challenge_passed():
    result = evaluate_rules(starting_balance=1000, day_start_equity=1070,
        equity=1080, state=base_state(), today="2026-11-25")
    assert result["status"] == "PASSED"
    assert result["challenge_passed"] is True
