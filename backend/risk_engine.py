"""Conservative paper-only risk controls. This is NOT a verified SharkFunded rule profile.

The SharkFunded programme/phase is not yet confirmed. These limits are an independent
simulation safety overlay and must not be represented as the firm's contractual rules.
"""
from __future__ import annotations

POLICY = {
    "profile": "SHARKFUNDED_UNCONFIRMED_PAPER",
    "risk_per_trade_pct": 0.25,
    "daily_loss_pct": 2.0,
    "max_drawdown_pct": 3.0,
    "max_floating_loss_pct": 1.0,
    "max_open_risk_pct": 0.50,
    "max_positions": 3,
    "max_positions_per_symbol": 2,
    "max_consecutive_losses": 3,
    "minimum_reward_risk": 1.5,
    "daily_reset_timezone": "UTC",
}

def position_risk(entry: float, stop_loss: float | None, quantity: float) -> float:
    if stop_loss is None:
        return float("inf")
    return abs(float(entry) - float(stop_loss)) * float(quantity)

def evaluate_limits(*, starting_balance: float, day_start_equity: float,
                    equity: float, unrealized_pnl: float, open_risk: float,
                    consecutive_losses: int, daily_locked: bool = False,
                    hard_locked: bool = False) -> dict:
    start = max(float(starting_balance), 0.0)
    day_start = max(float(day_start_equity), 0.0)
    daily_loss = max(0.0, day_start - float(equity))
    floating_loss = max(0.0, -float(unrealized_pnl))
    daily_limit = day_start * POLICY["daily_loss_pct"] / 100
    max_loss_floor = start * (1 - POLICY["max_drawdown_pct"] / 100)
    floating_limit = start * POLICY["max_floating_loss_pct"] / 100
    max_open_risk = start * POLICY["max_open_risk_pct"] / 100

    reason = "ACTIVE"
    hard = bool(hard_locked)
    daily = bool(daily_locked)
    if float(equity) <= max_loss_floor:
        hard, reason = True, "MAX_DRAWDOWN_BREACHED"
    elif floating_loss >= floating_limit:
        hard, reason = True, "MAX_FLOATING_LOSS_BREACHED"
    elif daily_loss >= daily_limit:
        daily, reason = True, "DAILY_LOSS_LIMIT_REACHED"
    elif int(consecutive_losses) >= POLICY["max_consecutive_losses"]:
        daily, reason = True, "CONSECUTIVE_LOSS_LIMIT_REACHED"
    elif hard:
        reason = "HARD_LOCKED"
    elif daily:
        reason = "DAILY_LOCKED"

    return {
        "profile": POLICY["profile"],
        "status": "LOCKED" if hard or daily else "ACTIVE",
        "reason": reason,
        "daily_loss": round(daily_loss, 2),
        "daily_loss_limit": round(daily_limit, 2),
        "max_loss_floor": round(max_loss_floor, 2),
        "floating_loss": round(floating_loss, 2),
        "floating_loss_limit": round(floating_limit, 2),
        "open_risk": round(open_risk, 2) if open_risk != float("inf") else None,
        "max_open_risk": round(max_open_risk, 2),
        "risk_per_trade_pct": POLICY["risk_per_trade_pct"],
        "max_drawdown_pct": POLICY["max_drawdown_pct"],
        "daily_loss_pct": POLICY["daily_loss_pct"],
        "max_positions": POLICY["max_positions"],
        "max_positions_per_symbol": POLICY["max_positions_per_symbol"],
        "consecutive_losses": int(consecutive_losses),
        "max_consecutive_losses": POLICY["max_consecutive_losses"],
        "minimum_reward_risk": POLICY["minimum_reward_risk"],
        "daily_reset_timezone": POLICY["daily_reset_timezone"],
        "hard_locked": hard,
        "daily_locked": daily,
    }
