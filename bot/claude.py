"""Minimal Claude Messages API client (plain HTTP, so no SDK install needed)."""
from __future__ import annotations

import time

import requests

API_URL = "https://api.anthropic.com/v1/messages"


class ClaudeError(RuntimeError):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


class ClaudeClient:
    def __init__(self, api_key: str, prices: dict, session: requests.Session | None = None,
                 timeout: float = 240.0):
        self.api_key = api_key
        self.prices = prices
        self.session = session or requests.Session()
        self.timeout = timeout

    def create(self, body: dict) -> dict:
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        for attempt in range(4):
            try:
                r = self.session.post(API_URL, json=body, headers=headers, timeout=self.timeout)
            except requests.RequestException as e:
                if attempt < 3:
                    time.sleep(5 * 2 ** attempt)
                    continue
                raise ClaudeError(f"network error: {e}") from e
            if r.status_code in (429, 500, 502, 503, 504, 529) and attempt < 3:
                time.sleep(min(60, 5 * 2 ** attempt))
                continue
            if r.status_code >= 400:
                raise ClaudeError(f"HTTP {r.status_code}: {r.text[:400]}", r.status_code)
            return r.json()
        raise ClaudeError("gave up after retries")

    def cost_usd(self, usage: dict | None, model: str) -> float:
        """Approximate cost of one response from its usage block."""
        usage = usage or {}
        rates = self.prices.get(model) or self.prices.get("default") or {"input": 4.0, "output": 20.0}
        input_tokens = (usage.get("input_tokens", 0)
                        + 1.25 * usage.get("cache_creation_input_tokens", 0)
                        + 0.1 * usage.get("cache_read_input_tokens", 0))
        output_tokens = usage.get("output_tokens", 0)
        searches = (usage.get("server_tool_use") or {}).get("web_search_requests", 0)
        per_search = self.prices.get("web_search_per_1000", 10.0) / 1000
        return (input_tokens * rates["input"] / 1e6
                + output_tokens * rates["output"] / 1e6
                + searches * per_search)
