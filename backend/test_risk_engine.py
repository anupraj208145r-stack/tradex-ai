import unittest

from backend.risk_engine import POLICY, evaluate_limits, position_risk


class PaperRiskEngineTests(unittest.TestCase):
    def evaluate(self, **overrides):
        values = dict(
            starting_balance=10000,
            day_start_equity=10000,
            equity=10000,
            unrealized_pnl=0,
            open_risk=0,
            consecutive_losses=0,
        )
        values.update(overrides)
        return evaluate_limits(**values)

    def test_active_account_is_not_locked(self):
        result = self.evaluate()
        self.assertEqual(result["status"], "ACTIVE")

    def test_daily_loss_guard_locks_at_two_percent(self):
        result = self.evaluate(equity=9800)
        self.assertTrue(result["daily_locked"])
        self.assertEqual(result["reason"], "DAILY_LOSS_LIMIT_REACHED")

    def test_static_drawdown_guard_hard_locks(self):
        result = self.evaluate(equity=9700)
        self.assertTrue(result["hard_locked"])
        self.assertEqual(result["reason"], "MAX_DRAWDOWN_BREACHED")

    def test_floating_loss_guard_hard_locks(self):
        result = self.evaluate(unrealized_pnl=-100)
        self.assertTrue(result["hard_locked"])
        self.assertEqual(result["reason"], "MAX_FLOATING_LOSS_BREACHED")

    def test_consecutive_losses_pause_new_trading(self):
        result = self.evaluate(consecutive_losses=3)
        self.assertTrue(result["daily_locked"])
        self.assertEqual(result["reason"], "CONSECUTIVE_LOSS_LIMIT_REACHED")

    def test_position_risk_uses_price_distance_times_quantity(self):
        self.assertAlmostEqual(position_risk(100, 98, 5), 10)

    def test_policy_is_conservative_for_ten_thousand_account(self):
        self.assertEqual(10000 * POLICY["risk_per_trade_pct"] / 100, 25)
        self.assertEqual(10000 * POLICY["max_open_risk_pct"] / 100, 50)
        self.assertEqual(10000 * POLICY["max_floating_loss_pct"] / 100, 100)


if __name__ == "__main__":
    unittest.main()
