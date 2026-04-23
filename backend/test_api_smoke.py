import pathlib
import unittest

from fastapi.testclient import TestClient

import main


ROOT = pathlib.Path(__file__).resolve().parents[1]


class ApiSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(main.app)

    def test_openapi_exposes_snapshot_and_brokerage_routes(self):
        response = self.client.get("/openapi.json")
        self.assertEqual(response.status_code, 200)
        paths = response.json()["paths"]
        self.assertIn("/api/internal/snapshot", paths)
        self.assertIn("/api/brokerage/sync", paths)
        self.assertIn("/api/portfolio/equity-curve", paths)
        self.assertIn("/api/portfolio/snapshots", paths)

    def test_protected_auth_route_requires_bearer_token(self):
        response = self.client.get("/api/auth/me")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["detail"], "Missing or invalid authorization header")

    def test_frontend_is_served_from_root(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Northstar", response.text)

    def test_no_offline_demo_market_data_tokens_remain(self):
        source = "\n".join(
            [
                (ROOT / "backend" / "main.py").read_text(),
                (ROOT / "frontend" / "index.html").read_text(),
                (ROOT / "supabase" / "schema.sql").read_text(),
            ]
        )
        for token in (
            "offline-demo",
            "get_demo_history",
            "allow_demo",
            "Estimated trend",
            "synthetic",
            "dummy",
        ):
            self.assertNotIn(token, source)

    def test_crypto_symbols_use_yahoo_usd_pair_for_market_data(self):
        self.assertEqual(main._yahoo_symbol("AVAX"), "AVAX-USD")
        self.assertEqual(main._yahoo_symbol("xlm"), "XLM-USD")
        self.assertEqual(main._yahoo_symbol("AAPL"), "AAPL")


if __name__ == "__main__":
    unittest.main()
