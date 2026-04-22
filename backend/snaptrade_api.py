"""Minimal SnapTrade client for read-only brokerage connections."""
import hashlib
import hmac
import json
import os
import time
from base64 import b64encode
from typing import Any, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from env_loader import load_local_env

load_local_env()


class SnapTradeAPIError(RuntimeError):
    """Raised when the SnapTrade API returns an error response."""


class SnapTradeClient:
    def __init__(self):
        self.base_url = os.getenv("SNAPTRADE_BASE_URL", "https://api.snaptrade.com/api/v1").rstrip("/")
        self.client_id = os.getenv("SNAPTRADE_CLIENT_ID", "").strip()
        self.consumer_key = os.getenv("SNAPTRADE_CONSUMER_KEY", "").strip()
        self.redirect_uri = os.getenv("SNAPTRADE_REDIRECT_URI", "").strip()

    def is_configured(self) -> bool:
        return bool(self.client_id and self.consumer_key)

    def _require_config(self):
        if not self.is_configured():
            raise SnapTradeAPIError(
                "SnapTrade is not configured. Set SNAPTRADE_CLIENT_ID and SNAPTRADE_CONSUMER_KEY."
            )

    def _compute_signature(self, resource_path: str, body: Optional[dict]) -> str:
        subpath, _, query = resource_path.partition("?")
        signature_payload = {
            "content": None if not body else body,
            "path": f"/api/v1{subpath}",
            "query": query,
        }
        signature_content = json.dumps(signature_payload, separators=(",", ":"), sort_keys=True)
        digest = hmac.new(
            self.consumer_key.encode("utf-8"),
            signature_content.encode("utf-8"),
            hashlib.sha256,
        ).digest()
        return b64encode(digest).decode("utf-8")

    def _request(self, method: str, path: str, *, query: Optional[dict] = None, body: Optional[dict] = None):
        self._require_config()

        clean_query = {k: v for k, v in (query or {}).items() if v is not None and v != ""}
        clean_query["clientId"] = self.client_id
        clean_query["timestamp"] = str(int(time.time()))

        query_string = urlencode(sorted(clean_query.items()), doseq=True)
        resource_path = f"{path}?{query_string}"
        url = f"{self.base_url}{resource_path}"

        encoded_body = None
        headers = {"Accept": "application/json"}
        if body is not None:
            encoded_body = json.dumps(body, separators=(",", ":"), sort_keys=True).encode("utf-8")
            headers["Content-Type"] = "application/json"

        headers["Signature"] = self._compute_signature(resource_path, body)
        request = Request(url, data=encoded_body, headers=headers, method=method.upper())

        try:
            with urlopen(request, timeout=30) as response:
                payload = response.read().decode("utf-8")
                return json.loads(payload) if payload else {}
        except HTTPError as exc:
            raw_error = exc.read().decode("utf-8", errors="ignore")
            try:
                parsed_error = json.loads(raw_error) if raw_error else {}
            except json.JSONDecodeError:
                parsed_error = {"detail": raw_error or str(exc)}
            message = parsed_error.get("detail") or parsed_error.get("message") or raw_error or str(exc)
            raise SnapTradeAPIError(f"SnapTrade {exc.code}: {message}") from exc
        except URLError as exc:
            raise SnapTradeAPIError(f"Could not reach SnapTrade: {exc.reason}") from exc

    def register_user(self, user_id: str):
        return self._request("POST", "/snapTrade/registerUser", body={"userId": user_id})

    def reset_user_secret(self, user_id: str, user_secret: str):
        return self._request(
            "POST",
            "/snapTrade/resetUserSecret",
            body={"userId": user_id, "userSecret": user_secret},
        )

    def create_connection_portal_link(
        self,
        *,
        user_id: str,
        user_secret: str,
        broker: Optional[str] = None,
        custom_redirect: Optional[str] = None,
        reconnect: Optional[str] = None,
        immediate_redirect: bool = True,
        dark_mode: bool = True,
    ):
        body = {
            "connectionType": "read",
            "connectionPortalVersion": "v4",
            "darkMode": dark_mode,
            "immediateRedirect": immediate_redirect,
            "showCloseButton": True,
        }
        if broker:
            body["broker"] = broker
        if custom_redirect or self.redirect_uri:
            body["customRedirect"] = custom_redirect or self.redirect_uri
        if reconnect:
            body["reconnect"] = reconnect

        return self._request(
            "POST",
            "/snapTrade/login",
            query={"userId": user_id, "userSecret": user_secret},
            body=body,
        )

    def list_brokerages(self):
        return self._request("GET", "/brokerages")

    def list_connections(self, *, user_id: str, user_secret: str):
        return self._request(
            "GET",
            "/authorizations",
            query={"userId": user_id, "userSecret": user_secret},
        )

    def refresh_connection(self, *, authorization_id: str, user_id: str, user_secret: str):
        return self._request(
            "POST",
            f"/authorizations/{quote(authorization_id, safe='')}/refresh",
            query={"userId": user_id, "userSecret": user_secret},
        )

    def remove_connection(self, *, authorization_id: str, user_id: str, user_secret: str):
        return self._request(
            "DELETE",
            f"/authorizations/{quote(authorization_id, safe='')}",
            query={"userId": user_id, "userSecret": user_secret},
        )

    def list_accounts(self, *, user_id: str, user_secret: str):
        return self._request(
            "GET",
            "/accounts",
            query={"userId": user_id, "userSecret": user_secret},
        )

    def get_account_holdings(self, *, account_id: str, user_id: str, user_secret: str):
        return self._request(
            "GET",
            f"/accounts/{quote(account_id, safe='')}/holdings",
            query={"userId": user_id, "userSecret": user_secret},
        )

    def get_account_activities(
        self,
        *,
        account_id: str,
        user_id: str,
        user_secret: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        offset: Optional[int] = None,
        limit: Optional[int] = None,
        types: Optional[str] = None,
    ):
        """List historical activities (buys/sells/divs/fees) for an account.
        Dates in YYYY-MM-DD. If omitted, SnapTrade returns a default window."""
        query = {"userId": user_id, "userSecret": user_secret}
        if start_date:
            query["startDate"] = start_date
        if end_date:
            query["endDate"] = end_date
        if offset is not None:
            query["offset"] = offset
        if limit is not None:
            query["limit"] = limit
        if types:
            query["type"] = types
        return self._request(
            "GET",
            f"/accounts/{quote(account_id, safe='')}/activities",
            query=query,
        )


snaptrade = SnapTradeClient()
