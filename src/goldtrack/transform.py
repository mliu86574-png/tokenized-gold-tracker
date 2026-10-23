"""Turn raw API responses into tidy tables."""
from __future__ import annotations

import pandas as pd

# DefiLlama chainTvls also contains derived keys such as "Ethereum-staking"
# or "borrowed"; keep only the plain chain totals.
_EXCLUDED_SUFFIXES = ("-staking", "-pool2", "-borrowed", "-vesting", "-treasury", "-offers")
_EXCLUDED_KEYS = {"staking", "pool2", "borrowed", "vesting", "treasury", "offers"}


def snapshot_table(markets: list[dict], tokens: list[dict]) -> pd.DataFrame:
    """One row per token with the latest market data and market share."""
    by_id = {m["id"]: m for m in markets}
    rows = []
    for t in tokens:
        m = by_id.get(t["coingecko_id"])
        if not m:
            continue
        rows.append({
            "symbol": t["symbol"],
            "name": t["name"],
            "price_usd": m.get("current_price"),
            "market_cap_usd": m.get("market_cap"),
            "circulating_supply": m.get("circulating_supply"),
            "volume_24h_usd": m.get("total_volume"),
            "change_7d_pct": m.get("price_change_percentage_7d_in_currency"),
            "change_30d_pct": m.get("price_change_percentage_30d_in_currency"),
            "last_updated": m.get("last_updated"),
        })
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    total = df["market_cap_usd"].fillna(0).sum()
    df["market_share_pct"] = df["market_cap_usd"].fillna(0) / total * 100 if total else 0.0
    df["volume_to_mcap_pct"] = df["volume_24h_usd"] / df["market_cap_usd"] * 100
    return df.sort_values("market_cap_usd", ascending=False).reset_index(drop=True)


def history_table(histories: dict[str, dict]) -> pd.DataFrame:
    """Long table: date, symbol, price_usd, market_cap_usd, volume_usd (one row per day)."""
    frames = []
    for symbol, h in histories.items():
        cols = {}
        for key, col in (("prices", "price_usd"), ("market_caps", "market_cap_usd"),
                         ("total_volumes", "volume_usd")):
            s = pd.DataFrame(h.get(key, []), columns=["ts", col])
            s["date"] = pd.to_datetime(s["ts"], unit="ms", utc=True).dt.date
            cols[col] = s.drop(columns="ts").groupby("date").last()
        if not cols:
            continue
        df = pd.concat(cols.values(), axis=1).reset_index()
        df["symbol"] = symbol
        frames.append(df)
    if not frames:
        return pd.DataFrame(columns=["date", "symbol", "price_usd", "market_cap_usd", "volume_usd"])
    out = pd.concat(frames, ignore_index=True)
    return out[["date", "symbol", "price_usd", "market_cap_usd", "volume_usd"]].sort_values(["symbol", "date"])


def price_spread_bps(history: pd.DataFrame, a: str, b: str) -> pd.DataFrame:
    """Daily price spread of token a over token b in basis points: (Pa / Pb - 1) * 10,000."""
    wide = history.pivot_table(index="date", columns="symbol", values="price_usd")
    if a not in wide or b not in wide:
        return pd.DataFrame(columns=["date", "spread_bps"])
    spread = (wide[a] / wide[b] - 1) * 10_000
    return spread.dropna().rename("spread_bps").reset_index()


def chain_distribution(protocol: dict | None) -> pd.DataFrame:
    """Per-chain value for a DefiLlama protocol entry, largest first."""
    if not protocol:
        return pd.DataFrame(columns=["chain", "value_usd", "share_pct"])
    rows = []
    for key, value in (protocol.get("chainTvls") or {}).items():
        if key in _EXCLUDED_KEYS or key.endswith(_EXCLUDED_SUFFIXES):
            continue
        if isinstance(value, (int, float)) and value > 0:
            rows.append({"chain": key, "value_usd": float(value)})
    df = pd.DataFrame(rows, columns=["chain", "value_usd"])
    if df.empty:
        return df.assign(share_pct=[])
    df["share_pct"] = df["value_usd"] / df["value_usd"].sum() * 100
    return df.sort_values("value_usd", ascending=False).reset_index(drop=True)
