import unittest

from backend.strategy_engine import signal_for


def candles(count=30):
    rows=[]
    for i in range(count):
        base=100 + (i % 3) * 0.1
        rows.append({"time":i*60,"open":base,"high":base+1,"low":base-1,"close":base+0.2,"volume":10})
    return rows


class SMCStrategyTests(unittest.TestCase):
    def test_liquidity_sweep_requires_reclaim(self):
        rows=candles()
        rows[-1]={"time":rows[-1]["time"],"open":100.2,"high":101,"low":98,"close":100.5,"volume":10}
        self.assertEqual(signal_for("STR-058",rows),"BUY")

    def test_bos_requires_closed_candle_outside_range(self):
        rows=candles()
        rows[-1]={"time":rows[-1]["time"],"open":100.2,"high":113,"low":100,"close":112,"volume":10}
        self.assertEqual(signal_for("STR-059",rows),"BUY")

    def test_fvg_retest_requires_three_candle_gap_and_reclaim(self):
        rows=candles()
        rows[-3]={"time":rows[-3]["time"],"open":103,"high":105,"low":102,"close":104,"volume":10}
        rows[-2]={"time":rows[-2]["time"],"open":107,"high":108,"low":106,"close":107,"volume":10}
        rows[-1]={"time":rows[-1]["time"],"open":106,"high":107,"low":105.5,"close":106.5,"volume":10}
        self.assertEqual(signal_for("STR-061",rows),"BUY")


if __name__ == "__main__":
    unittest.main()
