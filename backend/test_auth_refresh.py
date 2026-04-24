import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient

import main


class AuthRefreshTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(main.app)

    def test_refresh_route_returns_new_session(self):
        response_payload = SimpleNamespace(
            user=SimpleNamespace(id="user-1", email="user@example.com"),
            session=SimpleNamespace(
                access_token="new-access-token",
                refresh_token="new-refresh-token",
            ),
        )

        with patch.object(main.db.supabase.auth, "refresh_session", return_value=response_payload) as refresh_session, \
             patch.object(main.db, "ensure_profile", return_value={"id": "user-1"}) as ensure_profile:
            response = self.client.post("/api/auth/refresh", json={"refresh_token": "old-refresh-token"})

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["user"]["email"], "user@example.com")
        self.assertEqual(body["session"]["access_token"], "new-access-token")
        self.assertEqual(body["session"]["refresh_token"], "new-refresh-token")
        refresh_session.assert_called_once_with("old-refresh-token")
        ensure_profile.assert_called_once_with("new-access-token", "user-1")

    def test_refresh_route_requires_refresh_token(self):
        response = self.client.post("/api/auth/refresh", json={"refresh_token": ""})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"], "refresh_token is required")


if __name__ == "__main__":
    unittest.main()
