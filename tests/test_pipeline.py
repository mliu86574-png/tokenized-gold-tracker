"""Offline tests. The responses below are SYNTHETIC: they mimic the shape of the
CoinGecko and DefiLlama APIs so the pipeline can be tested without network
access. They are not market data."""
import json
import shutil
from pathlib import Path

import pandas as pd
import pytest

from goldtrack import build, fetch, transform

ROOT = Path(__file__).resolve().parents[1]
DAY_MS = 86_400_000
T0 = 1_760_000_000_000  # arbitrary epoch milliseconds


def fake_markets(ids):
    caps = {"tether-gold": 3.0e9, "pax-gold": 1.0e9, "matrixdock-gold": 0.5e8}
    return [{"id": i, "current_price": 100.0, "market_cap": caps[i], "circulating_supply": caps[i] / 100,
             "total_volume": caps[i] * 0.02, "price_change_percentage_7d_in_currency": 1.0,
             "price_change_percentage_30d_in_currency": 3.0, "last_updated": "synthetic"}
            for i in ids if i in caps]


def fake_history(coin_id, days):
    base = {"tether-gold": 100.0, "pax-gold": 99.9, "matrixdock-gold": 100.1}.get(coin_id)
    if base is None:
        raise RuntimeError("unknown id")
    n = 40
    return {"prices": [[T0 + i * DAY_MS, base + i * 0.1] for i in range(n)],
            "market_caps": [[T0 + i * DAY_MS, 1e9 + i * 1e7] for i in range(n)],
            "total_volumes": [[T0 + i * DAY_MS, 1e7] for i in range(n)]}


def fake_protocols():
    return [{"name": "Tether Gold", "chainTvls": {"Ethereum": 2.7e9, "Ethereum-staking": 5e8,
                                                   "BSC": 2.0e8, "Tron": 1.0e8, "borrowed": 9e9}},
            {"name": "Other", "chainTvls": {"Ethereum": 1}}]


def _down(*_a, **_k):
    raise RuntimeError("offline")


@pytest.fixture
def repo(tmp_path):
    shutil.copy(ROOT / "config.json", tmp_path / "config.json")
    (tmp_path / "README.md").write_text("# Test\n<!-- SNAPSHOT:START -->\nSTALE-SENTINEL\n<!-- SNAPSHOT:END -->\n")
    return tmp_path


def test_snapshot_shares_sum_to_100():
    cfg = json.loads((ROOT / "config.json").read_text())
    snap = transform.snapshot_table(fake_markets([t["coingecko_id"] for t in cfg["tokens"]]), cfg["tokens"])
    assert snap["market_share_pct"].sum() == pytest.approx(100)
    assert snap.iloc[0]["symbol"] == "XAUT"


def test_spread_in_bps():
    hist = transform.history_table({"XAUT": fake_history("tether-gold", 40),
                                    "PAXG": fake_history("pax-gold", 40)})
    spread = transform.price_spread_bps(hist, "XAUT", "PAXG")
    assert spread["spread_bps"].iloc[0] == pytest.approx((100.0 / 99.9 - 1) * 10_000)


def test_chain_distribution_drops_derived_keys():
    df = transform.chain_distribution(fetch.find_protocol(fake_protocols(), "tether gold"))
    assert list(df["chain"]) == ["Ethereum", "BSC", "Tron"]
    assert df["share_pct"].sum() == pytest.approx(100)


def test_find_protocol_missing_returns_none():
    assert fetch.find_protocol(fake_protocols(), "Nope") is None
    assert transform.chain_distribution(None).empty


def test_full_build_writes_outputs(repo):
    res = build.build(repo, fake_markets, fake_history, fake_protocols, _down, _down, _down)
    assert (repo / "docs" / "index.html").exists()
    for name in ["snapshot.csv", "history.csv", "spread.csv", "chains_XAUT.csv"]:
        assert (repo / "data" / name).exists(), name
    readme = (repo / "README.md").read_text()
    assert "STALE-SENTINEL" not in readme and "| XAUT (Tether Gold)" in readme
    assert res["kpis"]["leader"] == "XAUT"
    assert res["kpis"]["mcap_30d_change"] is not None


def test_build_survives_defillama_outage(repo):
    def down():
        raise RuntimeError("outage")
    res = build.build(repo, fake_markets, fake_history, down, _down, _down, _down)
    assert res["chains"] == {}
    assert (repo / "docs" / "index.html").exists()
