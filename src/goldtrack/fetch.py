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


# ---------------------------------------------------------------- tokenized-gold extras
DEFILLAMA_YIELDS = "https://yields.llama.fi"


def coingecko_category(category: str = "tokenized-gold") -> list[dict]:
    """Every coin CoinGecko files under a category, largest first."""
    return _get(f"{COINGECKO}/coins/markets",
                {"vs_currency": "usd", "category": category, "order": "market_cap_desc", "per_page": 100,
                 "price_change_percentage": "7d,30d"}, _cg_headers())


def coingecko_tickers(coin_id: str) -> dict:
    """Top trading pairs by volume, with bid-ask spread and +/-2% order-book depth."""
    return _get(f"{COINGECKO}/coins/{coin_id}/tickers", {"depth": "true", "order": "volume_desc"}, _cg_headers(),
                retries=4, pause=15.0)


def defillama_pools() -> list[dict]:
    """All yield pools DefiLlama tracks (TVL, APY, chain, project)."""
    return _get(f"{DEFILLAMA_YIELDS}/pools").get("data", [])


def defillama_lend_borrow() -> list[dict]:
    """Lending-market parameters per pool: LTV, supplied and borrowed USD, borrow APY."""
    data = _get(f"{DEFILLAMA_YIELDS}/lendBorrow")
    return data.get("data", data) if isinstance(data, dict) else data


def token_extras(tokens: list[dict], category: str = "tokenized-gold") -> dict:
    """Fetch everything the extended tokenized-gold section needs; failures are reported, not raised."""
    out: dict = {"category": None, "tickers": {}, "pools": None, "lend": None, "errors": {}}
    try:
        out["category"] = coingecko_category(category)
    except Exception as err:
        out["errors"]["category"] = str(err)
    for t in tokens:
        try:
            time.sleep(8)  # keep under CoinGecko's free-tier rate limit
            out["tickers"][t["symbol"]] = coingecko_tickers(t["coingecko_id"])
        except Exception as err:
            out["errors"][f"tickers {t['symbol']}"] = str(err)
    for key, fn in (("pools", defillama_pools), ("lend", defillama_lend_borrow)):
        try:
            out[key] = fn()
        except Exception as err:
            out["errors"][key] = str(err)
    return out
