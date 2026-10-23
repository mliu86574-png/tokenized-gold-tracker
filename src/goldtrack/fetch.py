"""Fetch public market data for tokenized gold.

Sources (no API key required; optional keys raise rate limits):
* CoinGecko  - current market data and daily market-cap / price history
* DefiLlama  - per-chain distribution where the asset is tracked as a protocol
"""
from __future__ import annotations

import json
import os
import time
import urllib.parse
import urllib.request
from typing import Any

COINGECKO = "https://api.coingecko.com/api/v3"
DEFILLAMA = "https://api.llama.fi"
UA = "tokenized-gold-tracker/0.1 (+https://github.com)"


def _get(url: str, params: dict | None = None, headers: dict | None = None,
         retries: int = 3, pause: float = 6.0) -> Any:
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"
    hdrs = {"User-Agent": UA, "Accept": "application/json", **(headers or {})}
    last_err: Exception | None = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=hdrs)
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode())
        except Exception as err:  # network errors and HTTP 429 rate limits
            last_err = err
            time.sleep(pause * (attempt + 1))
    raise RuntimeError(f"GET failed after {retries} attempts: {url}") from last_err


def _cg_headers() -> dict:
    key = os.environ.get("COINGECKO_API_KEY")
    return {"x-cg-demo-api-key": key} if key else {}


def coingecko_markets(ids: list[str]) -> list[dict]:
    """Current price, market cap, supply and 24h volume for each CoinGecko id."""
    return _get(f"{COINGECKO}/coins/markets",
                {"vs_currency": "usd", "ids": ",".join(ids), "price_change_percentage": "7d,30d"},
                _cg_headers())


def coingecko_history(coin_id: str, days: int = 365) -> dict:
    """Daily price, market cap and volume history: {'prices': [[ms, v], ...], ...}."""
    return _get(f"{COINGECKO}/coins/{coin_id}/market_chart",
                {"vs_currency": "usd", "days": days, "interval": "daily"}, _cg_headers())


def defillama_protocols() -> list[dict]:
    """All protocols tracked by DefiLlama, including chainTvls."""
    return _get(f"{DEFILLAMA}/protocols")


def find_protocol(protocols: list[dict], name: str) -> dict | None:
    """Exact (case-insensitive) name match against DefiLlama's protocol list."""
    target = name.strip().lower()
    for p in protocols:
        if str(p.get("name", "")).strip().lower() == target:
            return p
    return None
