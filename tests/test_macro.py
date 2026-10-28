"""Offline tests for the macro monitor. All inputs are SYNTHETIC series that
mimic the shape of the Yahoo, FRED and CFTC responses; they are not market data."""
import json
import shutil
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from goldtrack import build, macro, narrative, sources
from test_pipeline import fake_history, fake_markets, fake_protocols

ROOT = Path(__file__).resolve().parents[1]
END = pd.Timestamp("2026-10-27")


def _walk(start, drift, vol, n=1300, seed=0):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range(end=END, periods=n)
    return pd.Series(start * np.exp(np.cumsum(rng.normal(drift, vol, n))), index=idx)


def fake_yahoo(symbol):
    if symbol == "ZC=F":
        raise RuntimeError("simulated outage")
    seed = sum(map(ord, symbol))
    return _walk(100 + seed % 50, 0.0002, 0.01, seed=seed)


def fake_fred(series_id):
    seed = sum(map(ord, series_id))
    if series_id in ("CPIAUCSL", "CPILFESL", "PCEPILFE", "PAYEMS", "UNRATE"):
        idx = pd.date_range(end="2026-09-01", periods=80, freq="MS")
        return pd.Series(np.linspace(100, 125, 80), index=idx)
    s = _walk(2.0, 0.0, 0.01, seed=seed)
    return s.iloc[:-1]  # FRED lags markets by a day


def fake_cot(code):
    idx = pd.date_range(end="2026-10-20", periods=260, freq="W-TUE")
    rng = np.random.default_rng(int(code))
    long = 150_000 + rng.normal(0, 20_000, len(idx)).cumsum() / 5
    return sources.parse_cot([{"report_date_as_yyyy_mm_dd": d.strftime("%Y-%m-%dT00:00:00.000"),
                               "m_money_positions_long_all": str(l), "m_money_positions_short_all": "30000",
                               "open_interest_all": "500000"} for d, l in zip(idx, long)])


@pytest.fixture
def repo(tmp_path):
    shutil.copy(ROOT / "config.json", tmp_path / "config.json")
    (tmp_path / "README.md").write_text("# T\n<!-- SNAPSHOT:START -->\nSTALE\n<!-- SNAPSHOT:END -->\n")
    return tmp_path


def test_parse_yahoo_chart_shape():
    payload = {"chart": {"result": [{"meta": {"gmtoffset": -14400},
                                     "timestamp": [1792641600, 1792728000, 1792728000],
                                     "indicators": {"quote": [{"close": [10.0, None, 11.0]}]}}], "error": None}}
    s = sources.parse_yahoo_chart(payload)
    assert list(s.values) == [10.0, 11.0]
    assert s.index.is_monotonic_increasing


def test_parse_fred_csv_handles_gaps_and_header_names():
    for header in ("DATE", "observation_date"):
        s = sources.parse_fred_csv(f"{header},DGS10\n2026-10-01,4.1\n2026-10-02,.\n2026-10-03,4.2\n")
        assert list(s.values) == [4.1, 4.2]


def test_parse_cot_net_position():
    df = sources.parse_cot([{"report_date_as_yyyy_mm_dd": "2026-10-20T00:00:00.000",
                             "m_money_positions_long_all": "120970", "m_money_positions_short_all": "16764",
                             "open_interest_all": "402279"}])
    assert df["mm_net"].iloc[0] == 120970 - 16764
    assert df["mm_net_pct_oi"].iloc[0] == pytest.approx((120970 - 16764) / 402279 * 100)


def test_signals_follow_rules():
    idx = pd.bdate_range(end=END, periods=400)
    gold = pd.Series(np.linspace(100, 200, 400), index=idx)          # steady uptrend
    real = pd.Series(np.linspace(2.0, 1.0, 400), index=idx)          # real yields falling ~7.5bp/month
    real.iloc[-30:] = np.linspace(real.iloc[-31], real.iloc[-31] - 0.3, 30)  # -30bp in the last month
    usd = pd.Series(np.linspace(120, 130, 400), index=idx)           # dollar rising
    read, sig = macro.factor_frame(gold, {"DFII10": real, "DTWEXBGS": usd}, {}, None, None)
    sc = macro.scorecard(read, sig)
    by = {f["key"]: f["signal"] for f in sc["factors"]}
    assert by["real_yield"] == 1
    assert by["trend"] == 1
    assert by["stretch"] == -1        # monotonic rise -> RSI 100
    assert by["usd"] == 0             # ~+0.8% a month, inside the ±1% band
    assert by["positioning"] is None  # no data -> excluded
    assert sc["n"] == 4


def test_stance_thresholds():
    assert macro.stance(3, 9) == "constructive"
    assert macro.stance(-3, 9) == "cautious"
    assert macro.stance(2, 9) == "neutral"
    assert macro.stance(0, 0) == "na"


def test_fx_sign_convention():
    idx = pd.bdate_range(end=END, periods=100)
    up = pd.Series(np.linspace(100, 110, 100), index=idx)
    specs = [{"key": "jpy", "group": "fx", "en": "USD/JPY", "zh": "", "usd_base": True},
             {"key": "eur", "group": "fx", "en": "EUR/USD", "zh": "", "usd_base": False}]
    rows = {r["key"]: r for r in macro.fx_rows({"jpy": up, "eur": up}, specs)}
    assert rows["jpy"]["ccy_m1"] < 0 < rows["eur"]["ccy_m1"]


def test_token_ounces_strip_price():
    h = pd.DataFrame({"date": ["2026-10-01"] * 2 + ["2026-10-02"] * 2, "symbol": ["XAUT", "PAXG"] * 2,
                      "price_usd": [4000, 4000, 4400, 4400], "market_cap_usd": [4e9, 2e9, 4.4e9, 2.2e9]})
    oz = macro.token_ounces(h)
    assert list(oz.values) == pytest.approx([1.5e6, 1.5e6])


def test_full_build_with_outages(repo):
    res = build.build(repo, fake_markets, fake_history, fake_protocols, fake_yahoo, fake_fred, fake_cot,
                      today=pd.Timestamp("2026-10-28"))
    page = (repo / "docs" / "index.html").read_text()
    assert "Gold & Macro Monitor" in page and "黄金宏观看板" in page
    assert "window.DATA=" in page and "echarts@5.5.1" in page
    status = json.loads((repo / "data" / "status.json").read_text())
    failed = [s["item"] for s in status["sources"] if not s["ok"]]
    assert failed == ["ZC=F"]
    sc = json.loads((repo / "data" / "scorecard.json").read_text())
    assert sc["factors_used"] >= 8 and -9 <= sc["score"] <= 9
    assert (repo / "docs" / "img" / "scorecard.png").exists()
    readme = (repo / "README.md").read_text()
    assert "STALE" not in readme and "Gold scorecard" in readme
    assert "2026-12-09" in page  # next FOMC decision from config


def test_build_survives_all_macro_sources_down(repo):
    def down(*_a, **_k):
        raise RuntimeError("down")
    res = build.build(repo, fake_markets, fake_history, fake_protocols, down, down, down,
                      today=pd.Timestamp("2026-10-28"))
    assert (repo / "docs" / "index.html").exists()
    assert set(res["markets"]) == {"gold"} and res["fred"] == {}  # gold falls back to the XAUT price


def test_narrative_is_bilingual():
    f = {"key": "real_yield", "reading": -12.0, "extra": None}
    en, zh = narrative.factor_reading(f, {"DFII10": 2.5})
    assert "bp" in en and "天" in zh


def test_host_breaker_skips_after_repeated_failures(monkeypatch):
    calls = []

    def boom(*_a, **_k):
        calls.append(1)
        raise OSError("blocked")
    monkeypatch.setattr(sources.urllib.request, "urlopen", boom)
    monkeypatch.setattr(sources.time, "sleep", lambda *_: None)
    sources._FAILS.clear()
    for _ in range(3):
        with pytest.raises(RuntimeError):
            sources._get_text("https://blocked.example/a")
    n = len(calls)
    with pytest.raises(RuntimeError, match="skipped"):
        sources._get_text("https://blocked.example/b")
    assert len(calls) == n  # no further network attempts
    sources._FAILS.clear()
