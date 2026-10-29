"""Analytics for the tokenized-gold section: market league table, net issuance,
trading venues, DeFi usage, and risk / tracking measures.

All inputs are public API payloads (CoinGecko, DefiLlama); every function tolerates
missing data and returns an empty result instead of raising.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

GRAMS_PER_OZ = 31.1034768
OZ_PER_TONNE = 32_150.7466


def _f(x) -> float | None:
    try:
        x = float(x)
    except (TypeError, ValueError):
        return None
    return None if np.isnan(x) else x


# ---------------------------------------------------------------- league table (whole category)
def league_table(rows: list[dict] | None, exclude: dict[str, str] | None = None,
                 min_mcap: float = 1e6, band: float = 0.03) -> tuple[pd.DataFrame, dict]:
    """Every gold token CoinGecko lists, with its unit inferred from price.

    A token counts as per-ounce when its price is within `band` of the reference ounce price
    (median price of the large tokens), per-gram when price x 31.10 is; anything else (stock
    tokens, game tokens, stale listings) is dropped. Bridged representations in `exclude`
    are listed but kept out of the totals so supply is not counted twice.
    """
    exclude = exclude or {}
    if not rows:
        return pd.DataFrame(), {}
    df = pd.DataFrame([{
        "id": r.get("id"), "symbol": str(r.get("symbol", "")).upper(), "name": r.get("name"),
        "price": _f(r.get("current_price")), "mcap": _f(r.get("market_cap")) or 0.0,
        "supply": _f(r.get("circulating_supply")), "volume": _f(r.get("total_volume")) or 0.0,
        "chg7d": _f(r.get("price_change_percentage_7d_in_currency")),
        "chg30d": _f(r.get("price_change_percentage_30d_in_currency")),
    } for r in rows])
    big = df[(df["mcap"] >= 50e6) & (df["price"] > 500)]
    if big.empty:
        return pd.DataFrame(), {}
    ref = float(big["price"].median())
    ratio = df["price"] / ref
    df["unit"] = np.where((ratio - 1).abs() <= band, "oz",
                          np.where((ratio * GRAMS_PER_OZ - 1).abs() <= band, "g", None))
    df = df[df["unit"].notna() & (df["mcap"] >= min_mcap)].copy()
    df["oz"] = np.where(df["unit"] == "oz", df["supply"], df["supply"] / GRAMS_PER_OZ)
    df["oz"] = df["oz"].where(df["oz"] > 0, df["mcap"] / ref)
    df["price_oz"] = np.where(df["unit"] == "oz", df["price"], df["price"] * GRAMS_PER_OZ)
    df["tonnes"] = df["oz"] / OZ_PER_TONNE
    df["bridged"] = df["id"].isin(exclude)
    counted = df[~df["bridged"]]
    total = counted["mcap"].sum()
    df["share"] = np.where(df["bridged"], np.nan, df["mcap"] / total * 100 if total else np.nan)
    med = float(counted["price_oz"].median()) if not counted.empty else ref
    df["premium_bps"] = (df["price_oz"] / med - 1) * 1e4
    df["turnover"] = df["volume"] / df["mcap"] * 100
    df = df.sort_values("mcap", ascending=False).reset_index(drop=True)
    shares = counted["mcap"].sort_values(ascending=False) / total * 100 if total else pd.Series(dtype=float)
    summary = {"n": int(len(counted)), "mcap": float(total), "oz": float(counted["oz"].sum()),
               "tonnes": float(counted["tonnes"].sum()), "volume": float(counted["volume"].sum()),
               "top2_share": float(shares.head(2).sum()) if len(shares) else None,
               "hhi": float((shares ** 2).sum()) if len(shares) else None,
               "ref_price": med, "bridged": {i: exclude[i] for i in df.loc[df["bridged"], "id"]}}
    return df, summary


# ---------------------------------------------------------------- net issuance from supply history
def ounces_by_token(history: pd.DataFrame, units: dict[str, str]) -> pd.DataFrame:
    """Wide frame (date x symbol) of ounces outstanding = market cap / price, grams converted."""
    if history is None or history.empty:
        return pd.DataFrame()
    h = history.dropna(subset=["market_cap_usd", "price_usd"]).copy()
    h = h[h["price_usd"] > 0]
    h["oz"] = h["market_cap_usd"] / h["price_usd"]
    h.loc[h["symbol"].map(units).eq("g"), "oz"] /= GRAMS_PER_OZ
    wide = h.pivot_table(index="date", columns="symbol", values="oz", aggfunc="last")
    wide.index = pd.to_datetime(wide.index)
    return wide.sort_index()


def net_issuance(oz: pd.DataFrame, price_oz: float | None) -> tuple[list[dict], pd.DataFrame]:
    """7- and 30-day change in ounces per token (mint minus redeem), valued at today's price,
    plus weekly net issuance in USD millions for the chart."""
    if oz.empty:
        return [], pd.DataFrame()
    rows = []
    for sym in oz.columns:
        s = oz[sym].dropna()
        if len(s) < 8:
            continue
        last = float(s.iloc[-1])

        def ago(days):
            past = s[s.index <= s.index[-1] - pd.Timedelta(days=days)]
            return float(past.iloc[-1]) if len(past) else None
        w, m = ago(7), ago(30)
        d7 = None if w is None else last - w
        d30 = None if m is None else last - m
        stale = d30 is not None and d7 is not None and abs(d30) < 1e-6 and abs(d7) < 1e-6
        if stale:  # the source has not updated circulating supply; a zero here is not "no flows"
            d7 = d30 = None
        jump = any(x is not None and b_ and abs(x / b_) > 0.15 for x, b_ in ((d7, w), (d30, m)))
        rows.append({"symbol": sym, "oz": last, "d7_oz": d7, "d30_oz": d30, "stale": stale, "jump": jump,
                     "d7_pct": None if not w or d7 is None else d7 / w * 100,
                     "d30_pct": None if not m or d30 is None else d30 / m * 100,
                     "d7_usd": None if d7 is None or not price_oz else d7 * price_oz,
                     "d30_usd": None if d30 is None or not price_oz else d30 * price_oz})
    weekly = oz.resample("W-SUN").last().diff().iloc[1:]
    for r_ in rows:
        if r_["stale"] and r_["symbol"] in weekly:
            weekly = weekly.drop(columns=r_["symbol"])
    if price_oz:
        weekly = weekly * price_oz / 1e6
    return rows, weekly.tail(26)


# ---------------------------------------------------------------- trading venues
def _is_dex(t: dict) -> bool:
    return str(t.get("base", "")).upper().startswith("0X") or str(t.get("target", "")).upper().startswith("0X")


def venue_tables(tickers: dict[str, dict]) -> tuple[list[dict], list[dict]]:
    """Per-token liquidity summary and the largest individual venues across tokens.

    Volume is as reported by each venue to CoinGecko and can be inflated on some exchanges;
    +/-2% depth (cost to move the price 2%) is the sturdier liquidity measure.
    """
    summary, top = [], []
    for sym, payload in (tickers or {}).items():
        ts = [t for t in (payload or {}).get("tickers", [])
              if not t.get("is_stale") and not t.get("is_anomaly") and (t.get("converted_volume") or {}).get("usd")]
        if not ts:
            continue
        vol = sum(t["converted_volume"]["usd"] for t in ts)
        by_venue: dict[str, float] = {}
        for t in ts:
            name = (t.get("market") or {}).get("name", "?")
            by_venue[name] = by_venue.get(name, 0.0) + t["converted_volume"]["usd"]
        ranked = sorted(by_venue.items(), key=lambda kv: kv[1], reverse=True)
        dex = sum(t["converted_volume"]["usd"] for t in ts if _is_dex(t))
        spreads = [t["bid_ask_spread_percentage"] for t in ts[:10] if _f(t.get("bid_ask_spread_percentage")) is not None]
        depth = sum((_f(t.get("cost_to_move_up_usd")) or 0) + (_f(t.get("cost_to_move_down_usd")) or 0) for t in ts)
        summary.append({"symbol": sym, "volume": vol, "venues": len(by_venue), "dex_share": dex / vol * 100,
                        "top_venue": ranked[0][0], "top_share": ranked[0][1] / vol * 100,
                        "top3_share": sum(v for _, v in ranked[:3]) / vol * 100,
                        "spread_med": float(np.median(spreads)) if spreads else None, "depth2": depth})
        for t in ts:
            top.append({"symbol": sym, "venue": (t.get("market") or {}).get("name", "?"),
                        "pair": f'{t.get("base", "")[:10]}/{t.get("target", "")[:10]}' if not _is_dex(t)
                        else "on-chain pool", "dex": _is_dex(t), "volume": t["converted_volume"]["usd"],
                        "spread": _f(t.get("bid_ask_spread_percentage")),
                        "depth2": (_f(t.get("cost_to_move_up_usd")) or 0) + (_f(t.get("cost_to_move_down_usd")) or 0)})
    summary.sort(key=lambda r: r["volume"], reverse=True)
    top.sort(key=lambda r: r["volume"], reverse=True)
    return summary, top[:12]


# ---------------------------------------------------------------- DeFi usage
def defi_pools(pools: list[dict] | None, lend: list[dict] | None, symbols: list[str],
               min_tvl: float = 100_000) -> tuple[list[dict], list[dict], dict]:
    """Pools on DefiLlama that hold a gold token: top pools, TVL by protocol, and totals."""
    if not pools:
        return [], [], {}
    want = {s.upper() for s in symbols}
    lb = {r.get("pool"): r for r in (lend or []) if isinstance(r, dict)}
    rows = []
    for p in pools:
        parts = {x.strip().upper() for x in str(p.get("symbol", "")).replace("/", "-").split("-")}
        hit = sorted(parts & want)
        tvl = _f(p.get("tvlUsd")) or 0.0
        if not hit or tvl < min_tvl:
            continue
        l = lb.get(p.get("pool")) or {}
        supplied, borrowed = _f(l.get("totalSupplyUsd")), _f(l.get("totalBorrowUsd"))
        rows.append({"project": p.get("project"), "chain": p.get("chain"), "symbol": p.get("symbol"),
                     "gold": "/".join(hit), "tvl": tvl, "apy": _f(p.get("apy")), "apy_base": _f(p.get("apyBase")),
                     "apy_reward": _f(p.get("apyReward")), "single": p.get("exposure") == "single",
                     "fee_tier": p.get("poolMeta") if str(p.get("poolMeta") or "").rstrip("%").replace(".", "").isdigit() else None,
                     "ltv": _f(l.get("ltv")),
                     "borrow_apy": _f(l.get("apyBaseBorrow")),
                     "util": borrowed / supplied * 100 if supplied and borrowed is not None else None})
    if not rows:
        return [], [], {}
    df = pd.DataFrame(rows)
    by_proj = (df.groupby("project")["tvl"].sum().sort_values(ascending=False) / 1e6).round(2)
    single = df[df["single"] & df["apy"].notna()]
    stats = {"tvl": float(df["tvl"].sum()), "pools": int(len(df)), "protocols": int(df["project"].nunique()),
             "chains": int(df["chain"].nunique()),
             "single_apy_w": float(np.average(single["apy"], weights=single["tvl"])) if len(single) else None,
             "collateral": int(df["ltv"].fillna(0).gt(0).sum())}
    top = df.sort_values("tvl", ascending=False).head(15).to_dict("records")
    return top, [{"k": k, "v": float(v)} for k, v in by_proj.head(10).items()], stats


# ---------------------------------------------------------------- risk and tracking
def risk_table(history: pd.DataFrame, units: dict[str, str], gold: pd.Series | None, btc: pd.Series | None,
               gold_is_independent: bool = True, btc_lag_days: int = 0) -> list[dict]:
    """Per token: 30-day realised volatility, 90-day correlation and tracking error against
    gold, correlation with bitcoin, and price relative to the median token (bp).

    CoinGecko stamps each daily price at 00:00 UTC, i.e. the close of the previous day, so
    token returns are moved back one day before they are lined up with gold's daily closes
    (and with bitcoin when its series comes from a source that stamps the close date)."""
    if history is None or history.empty:
        return []
    px = history.pivot_table(index="date", columns="symbol", values="price_usd", aggfunc="last")
    px.index = pd.to_datetime(px.index)
    for sym in px.columns:
        if units.get(sym) == "g":
            px[sym] = px[sym] * GRAMS_PER_OZ
    px = px.sort_index()
    rel = px.div(px.median(axis=1), axis=0).sub(1).mul(1e4)
    r = np.log(px).diff()
    r_close = r.copy()
    r_close.index = r_close.index - pd.Timedelta(days=1)  # 00:00 UTC stamp -> previous day's close
    g = np.log(gold).diff() if gold is not None and len(gold) and gold_is_independent else None
    b = np.log(btc).diff() if btc is not None and len(btc) else None
    out = []
    for sym in px.columns:
        s = r[sym].dropna()
        if len(s) < 30:
            continue
        row = {"symbol": sym, "vol30": float(s.tail(30).std() * np.sqrt(365) * 100),
               "rel_bps": _f(rel[sym].dropna().iloc[-1]) if rel[sym].notna().any() else None,
               "rel_bps_30d": _f(rel[sym].dropna().tail(30).mean()), "corr_gold": None, "te_gold": None,
               "corr_btc": None}
        if g is not None:
            x, y = r_close[sym].dropna().tail(90).align(g.dropna(), join="inner")
            if len(x) >= 30:
                row["corr_gold"] = float(x.corr(y))
                row["te_gold"] = float((x - y).std() * np.sqrt(252) * 100)
        if b is not None:
            sb = r_close[sym] if btc_lag_days else r[sym]
            x, y = sb.dropna().tail(90).align(b.dropna(), join="inner")
            if len(x) >= 30:
                row["corr_btc"] = float(x.corr(y))
        out.append(row)
    return out


def narrative(league: dict, flows: list[dict], venues: list[dict], defi: dict) -> tuple[str, str]:
    """Two-sentence bilingual summary for the top of the section."""
    en, zh = [], []
    if league and league.get("mcap"):
        top2 = league.get("top2_share") or 0
        en.append(f"{league['n']} gold-backed tokens worth ${league['mcap'] / 1e9:,.2f}bn represent about "
                  f"{league['tonnes']:,.1f} tonnes of gold; the two largest hold {top2:.0f}% of the market.")
        zh.append(f"共 {league['n']} 个黄金代币，总市值约 {league['mcap'] / 1e8:,.1f} 亿美元，对应约 "
                  f"{league['tonnes']:,.1f} 吨黄金；前两大代币占 {top2:.0f}% 的份额。")
    net30 = [f for f in flows if f.get("d30_usd") is not None]
    if net30:
        tot = sum(f["d30_usd"] for f in net30)
        lead = max(net30, key=lambda f: abs(f["d30_usd"]))
        word = "net minting" if tot >= 0 else "net redemptions"
        en.append(f"Tracked tokens saw {word} of ${abs(tot) / 1e6:,.0f}m over 30 days, led by {lead['symbol']} "
                  f"({lead['d30_oz']:+,.0f} oz).")
        zh.append(f"过去 30 天追踪代币{'净铸造' if tot >= 0 else '净赎回'}约 {abs(tot) / 1e6:,.0f} 百万美元，"
                  f"主要来自 {lead['symbol']}（{lead['d30_oz']:+,.0f} 盎司）。")
    if venues:
        v = venues[0]
        en.append(f"{v['symbol']} trades on {v['venues']} venues; {v['dex_share']:.0f}% of reported volume is on-chain.")
        zh.append(f"{v['symbol']} 在 {v['venues']} 个场所交易，链上 DEX 占报告成交量的 {v['dex_share']:.0f}%。")
    if defi:
        en.append(f"DeFi pools holding gold tokens total ${defi['tvl'] / 1e6:,.0f}m across {defi['protocols']} protocols.")
        zh.append(f"含黄金代币的 DeFi 池合计 {defi['tvl'] / 1e6:,.0f} 百万美元，分布在 {defi['protocols']} 个协议。")
    return " ".join(en), "".join(zh)
