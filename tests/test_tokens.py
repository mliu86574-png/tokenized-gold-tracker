"""Offline tests for the tokenized-gold analytics. All payloads are SYNTHETIC and only
mimic the shape of CoinGecko and DefiLlama responses; they are not market data."""
import json
import shutil
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from goldtrack import build, official
from goldtrack import tokens as tk

ROOT = Path(__file__).resolve().parents[1]
OZ = 4000.0


def cat_rows():
    def row(i, sym, price, mcap, supply, vol=1e6):
        return {"id": i, "symbol": sym, "name": sym.upper(), "current_price": price, "market_cap": mcap,
                "circulating_supply": supply, "total_volume": vol,
                "price_change_percentage_7d_in_currency": 1.0, "price_change_percentage_30d_in_currency": 3.0}
    return [row("tok-a", "aaa", OZ, 3.2e9, 8e5, 2e8), row("tok-b", "bbb", OZ * 1.001, 1.8e9, 4.5e5, 9e7),
            row("tok-g", "ggg", OZ / tk.GRAMS_PER_OZ, 3.5e8, 2.7e6), row("tok-a-bridge", "aaa0", OZ, 1.1e8, 2.75e4),
            row("stock", "stk", 550.0, 5e7, 9e4), row("tiny", "tny", OZ, 5e5, 125), row("game", "gme", 4.05, 8e7, 2e7)]


def test_league_units_filter_and_bridged():
    df, s = tk.league_table(cat_rows(), {"tok-a-bridge": "wrapper of AAA"})
    assert set(df["symbol"]) == {"AAA", "BBB", "GGG", "AAA0"}  # stock, game and sub-$1m tokens dropped
    assert df.set_index("symbol").loc["GGG", "unit"] == "g"
    assert s["n"] == 3 and s["mcap"] == pytest.approx(3.2e9 + 1.8e9 + 3.5e8)
    assert np.isnan(df.set_index("symbol").loc["AAA0", "share"])  # listed, not double counted
    oz_g = 2.7e6 / tk.GRAMS_PER_OZ
    assert s["oz"] == pytest.approx(8e5 + 4.5e5 + oz_g)
    assert s["tonnes"] == pytest.approx(s["oz"] / tk.OZ_PER_TONNE)
    assert df.set_index("symbol").loc["BBB", "premium_bps"] > 0


def test_net_issuance_strips_price():
    idx = pd.date_range("2026-08-01", periods=60, freq="D")
    price = np.linspace(3500, 4000, 60)  # price rises, supply grows 100 oz a day
    oz = 1e5 + 100 * np.arange(60)
    h = pd.DataFrame({"date": idx.date, "symbol": "AAA", "price_usd": price, "market_cap_usd": price * oz})
    wide = tk.ounces_by_token(h, {"AAA": "oz"})
    rows, weekly = tk.net_issuance(wide, OZ)
    r = rows[0]
    assert r["d7_oz"] == pytest.approx(700) and r["d30_oz"] == pytest.approx(3000)
    assert r["d30_usd"] == pytest.approx(3000 * OZ)
    assert weekly["AAA"].dropna().iloc[-2] == pytest.approx(700 * OZ / 1e6)  # last bar is week to date
    assert not r["stale"] and not r["jump"]


def test_net_issuance_flags_stale_supply():
    idx = pd.date_range("2026-08-01", periods=40, freq="D")
    h = pd.DataFrame({"date": idx.date, "symbol": "AAA", "price_usd": np.linspace(3500, 4000, 40)})
    h["market_cap_usd"] = h["price_usd"] * 5e5  # supply frozen at the source
    rows, weekly = tk.net_issuance(tk.ounces_by_token(h, {"AAA": "oz"}), OZ)
    assert rows[0]["stale"] and rows[0]["d30_oz"] is None and "AAA" not in weekly


def test_venue_tables_dex_share_and_depth():
    def t(name, base, target, vol, up=1e5, down=1e5, stale=False):
        return {"market": {"name": name}, "base": base, "target": target, "converted_volume": {"usd": vol},
                "bid_ask_spread_percentage": 0.01, "cost_to_move_up_usd": up, "cost_to_move_down_usd": down,
                "is_stale": stale, "is_anomaly": False}
    payload = {"tickers": [t("CexA", "AAA", "USDT", 6e6), t("CexB", "AAA", "USDT", 2e6),
                           t("Uni", "0X68749665FF", "0XDAC17F958D", 2e6), t("Old", "AAA", "USD", 9e9, stale=True)]}
    summary, top = tk.venue_tables({"AAA": payload})
    s = summary[0]
    assert s["volume"] == pytest.approx(1e7) and s["dex_share"] == pytest.approx(20)
    assert s["top_venue"] == "CexA" and s["top_share"] == pytest.approx(60) and s["depth2"] == pytest.approx(6e5)
    assert top[2]["pair"] == "on-chain pool" and top[2]["dex"]


def test_defi_pools_match_symbols_and_lending():
    pools = [{"pool": "p1", "project": "lend-x", "chain": "Ethereum", "symbol": "XAUT", "tvlUsd": 5e7, "apy": 0.4,
              "apyBase": 0.4, "apyReward": None, "exposure": "single"},
             {"pool": "p2", "project": "dex-y", "chain": "Ethereum", "symbol": "XAUT-USDT", "tvlUsd": 2e6, "apy": 6.0,
              "apyBase": 2.0, "apyReward": 4.0, "exposure": "multi"},
             {"pool": "p3", "project": "dex-y", "chain": "Ethereum", "symbol": "XAUTX-USDC", "tvlUsd": 9e7, "apy": 1},
             {"pool": "p4", "project": "dex-z", "chain": "Base", "symbol": "PAXG-WETH", "tvlUsd": 5e4, "apy": 3}]
    lend = [{"pool": "p1", "ltv": 0.7, "totalSupplyUsd": 5e7, "totalBorrowUsd": 1e7, "apyBaseBorrow": 1.1}]
    top, proj, stats = tk.defi_pools(pools, lend, ["XAUT", "PAXG"])
    assert [p["pool"] if "pool" in p else p["project"] for p in top] == ["lend-x", "dex-y"]  # p3 not gold, p4 too small
    assert top[0]["ltv"] == 0.7 and top[0]["util"] == pytest.approx(20)
    assert stats["tvl"] == pytest.approx(5.2e7) and stats["collateral"] == 1
    assert proj[0]["k"] == "lend-x"


def test_risk_table_correlation_and_relative_price():
    idx = pd.date_range("2026-06-01", periods=120, freq="D")
    rng = np.random.default_rng(3)
    gold = pd.Series(OZ * np.exp(np.cumsum(rng.normal(0, 0.01, 120))), index=idx)
    stamp = (idx + pd.Timedelta(days=1)).date  # CoinGecko stamps the close at 00:00 UTC the next day
    h = pd.concat([pd.DataFrame({"date": stamp, "symbol": "AAA", "price_usd": gold.values * 1.0005,
                                 "market_cap_usd": 1e9}),
                   pd.DataFrame({"date": stamp, "symbol": "GGG", "price_usd": gold.values / tk.GRAMS_PER_OZ,
                                 "market_cap_usd": 1e8})])
    rows = {r["symbol"]: r for r in tk.risk_table(h, {"GGG": "g"}, gold, None)}
    assert rows["AAA"]["corr_gold"] == pytest.approx(1.0, abs=1e-6) and rows["AAA"]["te_gold"] < 0.01
    assert rows["AAA"]["rel_bps"] > 0 > rows["GGG"]["rel_bps"]
    assert tk.risk_table(h, {"GGG": "g"}, gold, None, gold_is_independent=False)[0]["corr_gold"] is None


def test_build_renders_extended_token_section(tmp_path):
    shutil.copy(ROOT / "config.json", tmp_path / "config.json")
    (tmp_path / "README.md").write_text("# T\n<!-- SNAPSHOT:START -->\n<!-- SNAPSHOT:END -->\n")
    day = 86_400_000
    t0 = int(pd.Timestamp("2026-06-01").timestamp() * 1000)

    def hist(coin_id, days):
        base = {"tether-gold": (OZ, 8e5), "pax-gold": (OZ * 1.001, 4.5e5)}.get(coin_id)
        if base is None:
            raise RuntimeError("n/a")
        p, oz = base
        return {"prices": [[t0 + i * day, p * (1 + 0.001 * np.sin(i))] for i in range(120)],
                "market_caps": [[t0 + i * day, p * (oz + 50 * i)] for i in range(120)],
                "total_volumes": [[t0 + i * day, 1e7] for i in range(120)]}

    extras = {"category": cat_rows(), "tickers": {"XAUT": {"tickers": [
        {"market": {"name": "CexA"}, "base": "XAUT", "target": "USDT", "converted_volume": {"usd": 5e7},
         "bid_ask_spread_percentage": 0.01, "cost_to_move_up_usd": 1e6, "cost_to_move_down_usd": 1e6}]}},
        "pools": [{"pool": "p1", "project": "lend-x", "chain": "Ethereum", "symbol": "XAUT", "tvlUsd": 5e7,
                   "apy": 0.4, "exposure": "single"}], "lend": [], "errors": {"tickers PAXG": "429"}}

    def down(*_a, **_k):
        raise RuntimeError("blocked")

    def nofb(*_a):
        raise official.NoFallback("x")

    build.build(tmp_path, lambda ids: [], hist, lambda: [], down, down, down, today=pd.Timestamp("2026-10-28"),
                get_alt=nofb, get_official=nofb, get_token_extras=lambda *a, **k: extras)
    page = (tmp_path / "docs" / "index.html").read_text()
    for needle in ("Market league table", "Net issuance (mint minus redeem)", "Liquidity and trading venues",
                   "DeFi usage", "Risk and tracking", "c_tokflow", "lend-x", "全市场排行"):
        assert needle in page, needle
    st = {s["item"]: s["ok"] for s in json.loads((tmp_path / "data" / "status.json").read_text())["sources"]}
    assert st["category tokenized-gold"] and st["tickers XAUT"] and not st["tickers PAXG"]
    assert (tmp_path / "data" / "token_league.csv").exists() and (tmp_path / "data" / "token_flows.csv").exists()
