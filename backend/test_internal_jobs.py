import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

import main


class InternalJobTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(main.app)

    def test_run_internal_alert_job_marks_triggered_alerts(self):
        alerts = [
            {
                "id": "alert-1",
                "user_id": "user-1",
                "symbol": "AAPL",
                "condition": "above",
                "target_price": 150.0,
                "triggered": False,
            },
            {
                "id": "alert-2",
                "user_id": "user-2",
                "symbol": "MSFT",
                "condition": "below",
                "target_price": 200.0,
                "triggered": False,
            },
        ]

        def quote(symbol: str):
            return {"price": 175.0 if symbol == "AAPL" else 250.0}

        with patch.object(main.db, "service_get_active_alerts", return_value=alerts), \
             patch.object(main, "get_ticker_info", side_effect=quote), \
             patch.object(main.db, "service_update_alert_triggered") as update_alert:
            result = main._run_internal_alert_job()

        self.assertEqual(result["checked"], 2)
        self.assertEqual(result["symbols_checked"], 2)
        self.assertEqual(result["triggered_count"], 1)
        self.assertEqual(result["users_seen"], 2)
        self.assertEqual(result["symbol_failures"], [])
        self.assertEqual(result["alerts_failed"], [])
        self.assertEqual(result["triggered"][0]["id"], "alert-1")
        update_alert.assert_called_once()

    def test_internal_snapshot_endpoint_returns_500_on_partial_failure(self):
        result = {
            "snapshot_date": "2026-04-24",
            "users_seen": 2,
            "snapshots_written": 1,
            "symbols_seen": 2,
            "price_rows_written": 10,
            "users_failed": [{"user_id": "user-2", "detail": "boom"}],
            "price_refresh_failed": None,
        }

        with patch.object(main, "require_internal_auth", return_value=None), \
             patch.object(main, "_run_internal_snapshot_job", return_value=result):
            response = self.client.post("/api/internal/snapshot")

        self.assertEqual(response.status_code, 500)
        body = response.json()
        self.assertFalse(body["ok"])
        self.assertEqual(body["job"], "snapshot")
        self.assertEqual(body["failure_count"], 1)

    def test_internal_alert_endpoint_returns_500_on_symbol_failure(self):
        result = {
            "checked": 1,
            "symbols_checked": 1,
            "triggered": [],
            "triggered_count": 0,
            "symbol_failures": [{"symbol": "AAPL", "detail": "No data"}],
            "alerts_failed": [],
            "users_seen": 1,
        }

        with patch.object(main, "require_internal_auth", return_value=None), \
             patch.object(main, "_run_internal_alert_job", return_value=result):
            response = self.client.post("/api/internal/alerts/check")

        self.assertEqual(response.status_code, 500)
        body = response.json()
        self.assertFalse(body["ok"])
        self.assertEqual(body["job"], "alerts-check")
        self.assertEqual(body["failure_count"], 1)


if __name__ == "__main__":
    unittest.main()
