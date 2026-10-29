"""Offline tests for the fallback sources. Every payload below is SYNTHETIC and only mimics
the shape of the Treasury, NY Fed, Cboe, BLS, ECB, Nasdaq, LBMA and FRED responses."""
import json
import shutil
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from goldtrack import build, official, sources

ROOT = Path(__file__).resolve().parents[1]


def test_treasury_csv():
    text = 'Date,"1 Mo","2 Yr","10 Yr"\n10/28/2026,4.10,3.60,4.05\n10/27/2026,4.11,3.62,4.08\n'
    df = official.parse_treasury_csv(text)
    assert list(df.index.strftime("%Y-%m-%d")) == ["2026-10-27", "2026-10-28"]
    assert df["10 YR"].iloc[-1] == 4.05 and df["2 YR"].iloc[0] == 3.62


def test_official_series_from_curves(monkeypatch):
    idx = pd.to_datetime(["2026-10-27", "2026-10-28"])
    nom = pd.DataFrame({"2 YR": [3.6, 3.5], "10 YR": [4.1, 4.0]}, index=idx)
    real = pd.DataFrame({"10 YR": [1.8, 1.7]}, index=idx)
    monkeypatch.setattr(official, "treasury_curve",
                        lambda kind: real if "real" in kind else nom)
    s, label = official.official_series("T10Y2Y")
    assert s.iloc[-1] == pytest.approx(0.5) and label == "US Treasury"
    s, _ = official.official_series("T10YIE")
    assert s.iloc[-1] == pytest.approx(2.3)
    with pytest.raises(official.NoFallback):
        official.official_series("BAMLH0A0HYM2")


def test_nyfed_target_and_sofr(monkeypatch):
    rows = {"secured/sofr": [{"effectiveDate": "2026-10-28", "percentRate": 3.92}],
            "unsecured/effr": [{"effectiveDate": "2026-10-28", "percentRate": 3.88, "targetRateFrom": 3.75,
                                "targetRateTo": 4.0}]}
    monkeypatch.setattr(official, "nyfed", lambda path: rows[path])
    assert official.official_series("SOFR")[0].iloc[-1] == 3.92
    assert official.official_series("DFEDTARU")[0].iloc[-1] == 4.0


def test_cboe_and_bls_parsers():
    vix = official.parse_cboe_csv("DATE,OPEN,HIGH,LOW,CLOSE\n10/27/2026,17,18,16,17.5\n10/28/2026,17.5,19,17,18.2\n")
    assert vix.iloc[-1] == 18.2
    payload = {"status": "REQUEST_SUCCEEDED", "Results": {"series": [
        {"seriesID": "LNS14000000", "data": [{"year": "2026", "period": "M09", "value": "4.3"},
                                             {"year": "2026", "period": "M08", "value": "4.2"}]}]}}
    s = official.parse_bls(payload)["LNS14000000"]
    assert s.index[-1] == pd.Timestamp("2026-09-01") and s.iloc[-1] == 4.3
    with pytest.raises(ValueError):
        official.parse_bls({"status": "REQUEST_NOT_PROCESSED", "message": ["daily threshold"]})


def test_ecb_crosses_and_dxy():
    text = ("KEY,FREQ,CURRENCY,CURRENCY_DENOM,EXR_TYPE,EXR_SUFFIX,TIME_PERIOD,OBS_VALUE\n"
            + "".join(f"x,D,{c},EUR,SP00,A,2026-10-28,{v}\n" for c, v in
                      [("USD", 1.08), ("JPY", 162.0), ("GBP", 0.85), ("AUD", 1.62), ("CHF", 0.95),
                       ("CNY", 7.7), ("HKD", 8.4), ("CAD", 1.47), ("SEK", 11.34)]))
    r = official.parse_ecb_csv(text)
    assert official.ecb_pair("eur", r).iloc[-1] == pytest.approx(1.08)
    assert official.ecb_pair("jpy", r).iloc[-1] == pytest.approx(150.0)
    assert official.ecb_pair("gbp", r).iloc[-1] == pytest.approx(1.08 / 0.85)
    dxy = official.ecb_pair("dxy", r).iloc[-1]
    direct = (50.14348112 * 1.08 ** -0.576 * 150 ** 0.136 * (1.08 / 0.85) ** -0.119 * (1.47 / 1.08) ** 0.091
              * (11.34 / 1.08) ** 0.042 * (0.95 / 1.08) ** 0.036)
    assert dxy == pytest.approx(direct) and 90 < dxy < 115


def test_nasdaq_lbma_fred_api_parsers():
    nd = official.parse_nasdaq({"data": {"tradesTable": {"rows": [
        {"date": "10/28/2026", "close": "4,012.30"}, {"date": "10/27/2026", "close": "$3,990.10"}]}}})
    assert list(nd.values) == [3990.10, 4012.30]
    lb = official.parse_lbma([{"d": "2026-10-27", "v": [3995.5, 3000.0, 3700.0]},
                              {"d": "2026-10-28", "v": [4005.0, 3010.0, 3710.0]}])
    assert lb.iloc[-1] == 4005.0
    fr = sources.parse_fred_api({"observations": [{"date": "2026-10-27", "value": "."},
                                                  {"date": "2026-10-28", "value": "4.05"}]})
    assert len(fr) == 1 and fr.iloc[0] == 4.05


def test_alt_market_tries_in_order(monkeypatch):
    s = pd.Series(np.linspace(1, 2, 30), index=pd.bdate_range(end="2026-10-28", periods=30))

    def nasdaq_down(*_a):
        raise RuntimeError("403")
    monkeypatch.setattr(official, "nasdaq_history", nasdaq_down)
    monkeypatch.setattr(official, "lbma", lambda name: s)
    got, label = official.alt_market({"key": "gold"})
    assert label == "LBMA gold_pm" and got.equals(s)
    with pytest.raises(official.NoFallback):
        official.alt_market({"key": "gsci"})


def test_build_records_fallback_sources(tmp_path):
    shutil.copy(ROOT / "config.json", tmp_path / "config.json")
    (tmp_path / "README.md").write_text("# T\n<!-- SNAPSHOT:START -->\n<!-- SNAPSHOT:END -->\n")
    idx = pd.bdate_range(end="2026-10-28", periods=600)
    walk = pd.Series(100 * np.exp(np.cumsum(np.random.default_rng(1).normal(0, 0.01, len(idx)))), index=idx)

    def down(*_a, **_k):
        raise RuntimeError("blocked")

    def alt(spec):
        if spec["key"] == "gsci":
            raise official.NoFallback("none")
        return walk, "ECB reference rates" if spec["group"] == "fx" else "Nasdaq"

    def off(fid):
        if fid in ("DGS10", "DGS2", "DFII10"):
            return walk / 25, "US Treasury"
        raise official.NoFallback(fid)

    res = build.build(tmp_path, lambda ids: [], lambda *a: {}, lambda: [], down, down, down,
                      today=pd.Timestamp("2026-10-28"), get_alt=alt, get_official=off)
    st = json.loads((tmp_path / "data" / "status.json").read_text())["sources"]
    by_item = {s["item"]: s for s in st}
    assert by_item["GC=F"]["source"] == "Nasdaq" and by_item["GC=F"]["ok"]
    assert by_item["EURUSD=X"]["source"] == "ECB reference rates"
    assert by_item["DGS10"]["source"] == "US Treasury"
    assert not by_item["^SPGSCI"]["ok"] and not by_item["WALCL"]["ok"]
    assert "DGS10" in res["fred"] and "gold" in res["markets"]
