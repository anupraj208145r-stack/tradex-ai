"""Configurable internal funded-style paper challenge rules.

These defaults are simulation guardrails, not the contractual rules of any prop firm.
Daily loss locks automatically clear on the next UTC day. Overall failure and pass
states remain terminal until the user explicitly resets the paper challenge.
"""
from __future__ import annotations

POLICY = {
    "profile": "INTERNAL_1000_FUNDED_STYLE",
    "daily_loss_pct": 2.0,
    "max_overall_loss_pct": 5.0,
    "profit_target_pct": 8.0,
    "risk_per_trade_pct": 0.5,
    "max_positions": 3,
    "daily_reset_timezone": "UTC",
}


def evaluate_rules(*, starting_balance: float, day_start_equity: float,
                   equity: float, state: dict, today: str) -> dict:
    """Pure rule evaluation; caller persists returned state fields."""
    start = max(float(starting_balance), 0.0)
    current = float(equity)
    day_start = max(float(day_start_equity), 0.0)
    daily_locked = bool(state.get("daily_locked", False))
    overall_failed = bool(state.get("overall_failed", False))
    challenge_passed = bool(state.get("challenge_passed", False))
    lock_reason = str(state.get("lock_reason", "") or "")

    if state.get("day_key") != today:
        day_start = current
        daily_locked = False
        if not overall_failed and not challenge_passed:
            lock_reason = ""

    daily_loss = max(0.0, day_start - current)
    daily_limit = day_start * POLICY["daily_loss_pct"] / 100
    max_loss_floor = start * (1 - POLICY["max_overall_loss_pct"] / 100)
    profit_target = start * (1 + POLICY["profit_target_pct"] / 100)

    if current <= max_loss_floor:
        overall_failed = True
        lock_reason = "MAX_OVERALL_LOSS_BREACHED"
    elif current >= profit_target:
        challenge_passed = True
        lock_reason = "PROFIT_TARGET_REACHED"
    elif daily_loss >= daily_limit and not (overall_failed or challenge_passed):
        daily_locked = True
        lock_reason = "DAILY_LOSS_LIMIT_REACHED"

    status = ("FAILED" if overall_failed else "PASSED" if challenge_passed
              else "DAILY_LOCKED" if daily_locked else "ACTIVE")
    return {
        "profile": POLICY["profile"],
        "status": status,
        "day_key": today,
        "day_start_equity": round(day_start, 2),
        "daily_loss": round(daily_loss, 2),
        "daily_loss_limit": round(daily_limit, 2),
        "max_loss_floor": round(max_loss_floor, 2),
        "overall_drawdown": round(max(0.0, start - current), 2),
        "max_overall_loss": round(start - max_loss_floor, 2),
        "profit_target": round(profit_target, 2),\n        "profit_target_amount": round(start * POLICY["profit_target_pct"] / 100, 2),
        "profit_progress": round(max(0.0, current - start), 2),
        "risk_per_trade_pct": POLICY["risk_per_trade_pct"],
        "max_positions": POLICY["max_positions"],
        "daily_reset_timezone": POLICY["daily_reset_timezone"],
        "daily_locked": daily_locked,
        "overall_failed": overall_failed,
        "challenge_passed": challenge_passed,
        "lock_reason": lock_reason,
    }
