import datetime
import unittest

from returns import daily_external_flows, irr, twr


class ReturnMathTests(unittest.TestCase):
    def test_twr_strips_out_deposit(self):
        values = [
            (datetime.date(2026, 1, 1), 100.0),
            (datetime.date(2026, 1, 2), 210.0),
        ]
        flows = {datetime.date(2026, 1, 2): 100.0}
        self.assertAlmostEqual(twr(values, flows), 0.10)

    def test_daily_external_flows_uses_portfolio_signs(self):
        txs = [
            {"side": "deposit", "amount": 500, "occurred_at": "2026-01-01T10:00:00Z"},
            {"side": "withdrawal", "amount": -125, "occurred_at": "2026-01-01T12:00:00Z"},
            {"side": "buy", "amount": -50, "occurred_at": "2026-01-01T13:00:00Z"},
        ]
        self.assertEqual(daily_external_flows(txs), {datetime.date(2026, 1, 1): 375.0})

    def test_irr_simple_gain(self):
        cashflows = [
            (datetime.date(2026, 1, 1), -100.0),
            (datetime.date(2027, 1, 1), 110.0),
        ]
        self.assertAlmostEqual(irr(cashflows), 0.10, places=3)


if __name__ == "__main__":
    unittest.main()
