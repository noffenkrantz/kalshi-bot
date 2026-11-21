"""Minimal Kalshi Trade API v2 client.

Covers request signing, market data, portfolio reads and V2 orders
(POST /portfolio/events/orders). Prices are dollar strings ("0.4500") and
counts are fixed-point strings ("10.00"), per Kalshi's fixed-point format.
"""
from __future__ import annotations

import base64
import time
import uuid
from pathlib import Path
from urllib.parse import urlparse

import requests
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ed25519, padding, rsa

BASE_URLS = {
    "prod": "https://external-api.kalshi.com/trade-api/v2",
    "demo": "https://external-api.demo.kalshi.co/trade-api/v2",
}


class KalshiError(RuntimeError):
    def __init__(self, message: str, status: int | None = None, body: str | None = None):
        super().__init__(message)
        self.status = status
        self.body = body


def load_private_key(pem_text: str | None = None, path: str | None = None):
    """Load the private key Kalshi gave you, from text (GitHub secret) or a file."""
    if pem_text:
        data = pem_text.replace("\\n", "\n").strip().encode()
    elif path:
        data = Path(path).expanduser().read_bytes()
    else:
        raise KalshiError("No Kalshi private key provided")
    return serialization.load_pem_private_key(data, password=None)


def sign(private_key, timestamp_ms: str, method: str, path: str) -> str:
    """Sign timestamp + METHOD + path (no query string), base64-encoded."""
    message = (timestamp_ms + method.upper() + path).encode("utf-8")
    if isinstance(private_key, rsa.RSAPrivateKey):
        signature = private_key.sign(
            message,
            padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.DIGEST_LENGTH),
            hashes.SHA256(),
        )
    elif isinstance(private_key, ed25519.Ed25519PrivateKey):
        signature = private_key.sign(message)
    else:
        raise KalshiError("Unsupported Kalshi key type (expected RSA or Ed25519)")
    return base64.b64encode(signature).decode("utf-8")


class KalshiClient:
    def __init__(self, env: str, key_id: str | None = None, private_key=None,
                 session: requests.Session | None = None, min_interval: float = 0.12,
                 timeout: float = 20.0):
        if env not in BASE_URLS:
            raise ValueError(f"Unknown Kalshi environment: {env}")
        self.env = env
        self.base_url = BASE_URLS[env]
        self.key_id = key_id
        self.private_key = private_key
        self.session = session or requests.Session()
        self.min_interval = min_interval
        self.timeout = timeout
        self._last_call = 0.0

    # ---- plumbing -------------------------------------------------------
    @property
    def authenticated(self) -> bool:
        return bool(self.key_id and self.private_key)

    def require_auth(self) -> None:
        if not self.authenticated:
            raise KalshiError(f"Kalshi {self.env} API key is not configured")

    def _throttle(self) -> None:
        wait = self.min_interval - (time.monotonic() - self._last_call)
        if wait > 0:
            time.sleep(wait)
        self._last_call = time.monotonic()

    def _headers(self, method: str, url: str) -> dict:
        headers = {"Accept": "application/json"}
        if self.authenticated:
            ts = str(int(time.time() * 1000))
            headers.update({
                "KALSHI-ACCESS-KEY": self.key_id,
                "KALSHI-ACCESS-TIMESTAMP": ts,
                "KALSHI-ACCESS-SIGNATURE": sign(self.private_key, ts, method, urlparse(url).path),
            })
        return headers

    def request(self, method: str, endpoint: str, params: dict | None = None,
                json_body: dict | None = None, retry: bool = True) -> dict:
        url = self.base_url + endpoint
        # Only GETs are retried. Retrying an order could place it twice.
        attempts = 3 if (retry and method == "GET") else 1
        for attempt in range(attempts):
            self._throttle()
            headers = self._headers(method, url)
            if json_body is not None:
                headers["Content-Type"] = "application/json"
            try:
                r = self.session.request(method, url, params=params, json=json_body,
                                         headers=headers, timeout=self.timeout)
            except requests.RequestException as e:
                if attempt < attempts - 1:
                    time.sleep(2 ** attempt)
                    continue
                raise KalshiError(f"{method} {endpoint}: network error: {e}") from e
            if r.status_code in (429, 500, 502, 503, 504) and attempt < attempts - 1:
                time.sleep(2 ** attempt + 0.5)
                continue
            if r.status_code >= 400:
                raise KalshiError(f"{method} {endpoint} -> HTTP {r.status_code}: {r.text[:400]}",
                                  r.status_code, r.text)
            return r.json() if r.content else {}
        raise KalshiError(f"{method} {endpoint}: gave up after retries")

    # ---- market data (public) ---------------------------------------------
    def exchange_status(self) -> dict:
        return self.request("GET", "/exchange/status")

    def iter_markets(self, max_markets: int = 5000, **params):
        params = {"limit": 1000, **params}
        seen, cursor = 0, None
        while True:
            if cursor:
                params["cursor"] = cursor
            data = self.request("GET", "/markets", params=params)
            for market in data.get("markets", []):
                yield market
                seen += 1
                if seen >= max_markets:
                    return
            cursor = data.get("cursor")
            if not cursor:
                return

    def get_market(self, ticker: str) -> dict:
        return self.request("GET", f"/markets/{ticker}").get("market", {})

    def get_event(self, event_ticker: str) -> dict:
        return self.request("GET", f"/events/{event_ticker}").get("event", {})

    # ---- portfolio (needs a key) ----------------------------------------------
    def get_balance(self) -> dict:
        self.require_auth()
        return self.request("GET", "/portfolio/balance")

    def get_positions(self) -> list[dict]:
        self.require_auth()
        out, cursor = [], None
        while True:
            params = {"limit": 1000, "count_filter": "position"}
            if cursor:
                params["cursor"] = cursor
            data = self.request("GET", "/portfolio/positions", params=params)
            out.extend(data.get("market_positions", []))
            cursor = data.get("cursor")
            if not cursor:
                return out

    def create_order(self, ticker: str, book_side: str, count: int, price: str,
                     client_order_id: str | None = None,
                     time_in_force: str = "immediate_or_cancel") -> dict:
        """V2 order on the single YES book.

        book_side "bid" = buy YES at `price`.
        book_side "ask" = sell YES at `price`, which is how you buy NO
        (a NO at 0.60 is the same trade as selling YES at 0.40).
        """
        self.require_auth()
        if book_side not in ("bid", "ask"):
            raise ValueError("book_side must be 'bid' or 'ask'")
        body = {
            "ticker": ticker,
            "side": book_side,
            "count": str(int(count)),
            "price": price,
            "time_in_force": time_in_force,
            "self_trade_prevention_type": "taker_at_cross",
            "client_order_id": client_order_id or f"cb-{uuid.uuid4().hex[:24]}",
        }
        resp = self.request("POST", "/portfolio/events/orders", json_body=body, retry=False)
        resp.setdefault("client_order_id", body["client_order_id"])
        return resp

    def get_order(self, order_id: str) -> dict:
        self.require_auth()
        return self.request("GET", f"/portfolio/orders/{order_id}").get("order", {})

    def cancel_order(self, order_id: str, ticker: str) -> dict:
        self.require_auth()
        return self.request("DELETE", f"/portfolio/events/orders/{order_id}",
                            params={"market_ticker": ticker}, retry=False)
