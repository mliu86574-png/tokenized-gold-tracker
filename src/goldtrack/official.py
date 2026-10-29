"""Fallback sources for when Yahoo and FRED refuse requests from CI runners.

Every function returns a pandas Series indexed by date. Raw downloads are cached for the
run, so e.g. the Treasury curve is fetched once and serves DGS10, DGS2, T10Y2Y and T10YIE.

* official_series(fred_id) - the FRED series rebuilt from the agency that publishes it
* alt_market(spec)         - a market from the config rebuilt from another public feed
                             (ECB crosses for FX, CoinGecko for bitcoin, ETF proxies for futures)
Both return (series, source_label) and raise when no fallback exists or all fail.
"""
from __future__ import annotations

import csv
import io
import json
from datetime import date, timedelta

import numpy as np
import pandas as pd

from .sources import BROWSER_UA, _get_text

YEARS = 6


class NoFallback(LookupError):
    """No alternative public source exists for this series."""

_CACHE: dict = {}


def _cached(key, fn):
    if key not in _CACHE:
        try:
            _CACHE[key] = fn()
        except Exception as err:  # remember failures too, so one dead host costs one request
            _CACHE[key] = err
    hit = _CACHE[key]
    if isinstance(hit, Exception):
        raise RuntimeError(str(hit)) from hit
    return hit


def _start(years: int = YEARS) -> date:
    return date.today() - timedelta(days=365 * years)


def _num(x) -> float | None:
    if x is None:
        return None
    x = str(x).replace("$", "").replace(",", "").strip()
    try:
        return float(x)
    except ValueError:
        return None


def _series(pairs) -> pd.Series:
    pairs = [(d, v) for d, v in pairs if v is not None]
    if not pairs:
        raise ValueError("no observations")
    s = pd.Series([v for _, v in pairs], index=pd.to_datetime([d for d, _ in pairs]), dtype="float64")
    return s[~s.index.duplicated(keep="last")].sort_index()


# ---------------------------------------------------------------- US Treasury yield curves
TREASURY = "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/daily-treasury-rates.csv/{y}/all"


def parse_treasury_csv(text: str) -> pd.DataFrame:
    rows = list(csv.DictReader(io.StringIO(text)))
    if not rows:
        raise ValueError("empty Treasury csv")
    df = pd.DataFrame(rows)
    df.columns = [c.strip().upper() for c in df.columns]
    df["DATE"] = pd.to_datetime(df["DATE"], format="%m/%d/%Y")
    df = df.set_index("DATE").sort_index()
    return df.apply(pd.to_numeric, errors="coerce")


def treasury_curve(kind: str) -> pd.DataFrame:
    """kind: 'daily_treasury_yield_curve' (nominal) or 'daily_treasury_real_yield_curve' (TIPS)."""
    def load():
        frames, errors = [], []
        for y in range(_start().year, date.today().year + 1):
            try:
                text = _get_text(TREASURY.format(y=y), {"type": kind, "field_tdr_date_value": y, "page": "",
                                                        "_format": "csv"}, timeout=30)
                frames.append(parse_treasury_csv(text))
            except Exception as err:
                errors.append(f"{y}: {err}")
                if not frames and len(errors) >= 2:
                    break
        if not frames:
            raise RuntimeError("Treasury unavailable: " + "; ".join(errors))
        df = pd.concat(frames).sort_index()
        return df[~df.index.duplicated(keep="last")]
    return _cached(("treasury", kind), load)


# ---------------------------------------------------------------- New York Fed reference rates
NYFED = "https://markets.newyorkfed.org/api/rates/{path}/search.json"


def nyfed(path: str) -> list[dict]:
    def load():
        text = _get_text(NYFED.format(path=path), {"startDate": _start().isoformat(),
                                                  "endDate": date.today().isoformat()}, timeout=30)
        rows = json.loads(text).get("refRates") or []
        if not rows:
            raise ValueError(f"no NY Fed rows for {path}")
        return rows
    return _cached(("nyfed", path), load)


# ---------------------------------------------------------------- Cboe VIX
CBOE_VIX = "https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv"


def parse_cboe_csv(text: str) -> pd.Series:
    rows = list(csv.DictReader(io.StringIO(text)))
    return _series((pd.to_datetime(r["DATE"], format="%m/%d/%Y"), _num(r.get("CLOSE"))) for r in rows)


def cboe_vix() -> pd.Series:
    s = _cached("vix", lambda: parse_cboe_csv(_get_text(CBOE_VIX, timeout=30)))
    return s[s.index >= pd.Timestamp(_start())]


# ---------------------------------------------------------------- BLS
BLS = "https://api.bls.gov/publicAPI/v1/timeseries/data/"
BLS_IDS = {"CPIAUCSL": "CUSR0000SA0", "CPILFESL": "CUSR0000SA0L1E",
           "UNRATE": "LNS14000000", "PAYEMS": "CES0000000001"}


def parse_bls(payload: dict) -> dict[str, pd.Series]:
    if payload.get("status") != "REQUEST_SUCCEEDED":
        raise ValueError(f"BLS: {payload.get('status')} {payload.get('message')}")
    out = {}
    for ser in (payload.get("Results") or {}).get("series", []):
        pairs = [(f"{d['year']}-{d['period'][1:]}-01", _num(d.get("value")))
                 for d in ser.get("data", []) if d.get("period", "").startswith("M") and d["period"] != "M13"]
        if pairs:
            out[ser["seriesID"]] = _series(pairs)
    return out


def bls() -> dict[str, pd.Series]:
    def load():
        body = json.dumps({"seriesid": list(BLS_IDS.values()), "startyear": str(_start().year),
                           "endyear": str(date.today().year)}).encode()
        text = _get_text(BLS, headers={"User-Agent": BROWSER_UA, "Content-Type": "application/json"},
                         data=body, timeout=30)
        return parse_bls(json.loads(text))
    return _cached("bls", load)


# ---------------------------------------------------------------- dispatch for FRED ids
def official_series(fred_id: str) -> tuple[pd.Series, str]:
    if fred_id in ("DGS10", "DGS2", "T10Y2Y"):
        c = treasury_curve("daily_treasury_yield_curve")
        s = {"DGS10": c["10 YR"], "DGS2": c["2 YR"], "T10Y2Y": c["10 YR"] - c["2 YR"]}[fred_id]
        return s.dropna(), "US Treasury"
    if fred_id in ("DFII10", "T10YIE"):
        real = treasury_curve("daily_treasury_real_yield_curve")["10 YR"]
        if fred_id == "DFII10":
            return real.dropna(), "US Treasury"
        nom = treasury_curve("daily_treasury_yield_curve")["10 YR"]
        return (nom - real).dropna(), "US Treasury (nominal − TIPS)"
    if fred_id == "SOFR":
        return _series((r["effectiveDate"], _num(r.get("percentRate"))) for r in nyfed("secured/sofr")), "New York Fed"
    if fred_id == "DFEDTARU":
        return _series((r["effectiveDate"], _num(r.get("targetRateTo"))) for r in nyfed("unsecured/effr")), "New York Fed"
    if fred_id == "VIXCLS":
        return cboe_vix(), "Cboe"
    if fred_id in BLS_IDS:
        data = bls()
        if BLS_IDS[fred_id] not in data:
            raise ValueError(f"BLS returned no {BLS_IDS[fred_id]}")
        return data[BLS_IDS[fred_id]], "BLS"
    raise NoFallback(f"no official fallback for {fred_id}")


# ---------------------------------------------------------------- ECB reference rates -> USD pairs
ECB = "https://data-api.ecb.europa.eu/service/data/EXR/D.{ccys}.EUR.SP00.A"
ECB_CCYS = ("USD", "JPY", "GBP", "AUD", "CHF", "CNY", "HKD", "CAD", "SEK")


def parse_ecb_csv(text: str) -> pd.DataFrame:
    rows = list(csv.DictReader(io.StringIO(text)))
    recs = [(r["TIME_PERIOD"], r["CURRENCY"], _num(r.get("OBS_VALUE"))) for r in rows]
    df = pd.DataFrame(recs, columns=["date", "ccy", "v"]).dropna()
    if df.empty:
        raise ValueError("empty ECB csv")
    out = df.pivot_table(index="date", columns="ccy", values="v", aggfunc="last")
    out.index = pd.to_datetime(out.index)
    return out.sort_index()


def ecb_rates() -> pd.DataFrame:
    return _cached("ecb", lambda: parse_ecb_csv(_get_text(
        ECB.format(ccys="+".join(ECB_CCYS)), {"format": "csvdata", "startPeriod": _start().isoformat()},
        headers={"User-Agent": BROWSER_UA, "Accept": "text/csv"}, timeout=40)))


def ecb_pair(key: str, r: pd.DataFrame) -> pd.Series:
    """USD pairs from per-euro reference rates; 'dxy' uses the ICE index formula."""
    usd = r["USD"]  # USD per EUR = EUR/USD
    per_usd = lambda c: r[c] / usd  # noqa: E731  units of c per USD
    if key == "eur":
        return usd
    if key in ("gbp", "aud"):
        return usd / r[key.upper()]
    if key in ("jpy", "chf", "cny", "hkd"):
        return per_usd(key.upper())
    if key == "dxy":
        return (50.14348112 * usd ** -0.576 * per_usd("JPY") ** 0.136 * (usd / r["GBP"]) ** -0.119
                * per_usd("CAD") ** 0.091 * per_usd("SEK") ** 0.042 * per_usd("CHF") ** 0.036)
    raise KeyError(key)


# ---------------------------------------------------------------- Nasdaq.com history
NASDAQ = "https://api.nasdaq.com/api/quote/{sym}/historical"
NASDAQ_HEADERS = {"User-Agent": BROWSER_UA, "Accept": "application/json, text/plain, */*",
                  "Origin": "https://www.nasdaq.com", "Referer": "https://www.nasdaq.com/"}


def parse_nasdaq(payload: dict) -> pd.Series:
    rows = (((payload.get("data") or {}).get("tradesTable") or {}).get("rows")) or []
    return _series((pd.to_datetime(r.get("date"), format="%m/%d/%Y", errors="coerce"), _num(r.get("close")))
                   for r in rows if r.get("date"))


def nasdaq_history(symbol: str, assetclass: str) -> pd.Series:
    text = _get_text(NASDAQ.format(sym=symbol), {
        "assetclass": assetclass, "fromdate": _start(5).isoformat(), "todate": date.today().isoformat(),
        "limit": 9999}, headers=NASDAQ_HEADERS, timeout=30)
    return parse_nasdaq(json.loads(text))


# ---------------------------------------------------------------- CoinGecko bitcoin
def coingecko_btc() -> pd.Series:
    from . import fetch
    raw = fetch.coingecko_history("bitcoin", 365)
    return _series((pd.to_datetime(t, unit="ms").normalize(), float(p)) for t, p in raw.get("prices", []))


# ---------------------------------------------------------------- dispatch for markets
# Nasdaq.com serves stocks, ETFs and its own indices only (no futures, no spot FX), so
# futures fall back to the closest exchange-traded fund. Their LEVELS are ETF prices, not
# futures prices; the build labels them as proxies and keeps them out of price ratios.
ETF_PROXIES = {"gold": "GLD", "silver": "SLV", "platinum": "PPLT", "palladium": "PALL", "copper": "CPER",
               "wti": "USO", "brent": "BNO", "natgas": "UNG", "wheat": "WEAT", "corn": "CORN",
               "gsci": "GSG", "spx": "SPY"}
PROXY_PREFIX = "ETF proxy"


def alt_market(spec: dict) -> tuple[pd.Series, str]:
    key = spec["key"]
    tries = []
    if key in ("eur", "gbp", "aud", "jpy", "chf", "cny", "hkd", "dxy"):
        label = "ECB reference rates" + (" (ICE formula)" if key == "dxy" else "")
        tries.append((label, lambda: ecb_pair(key, ecb_rates()).replace([np.inf, -np.inf], np.nan).dropna()))
    if key == "btc":
        tries.append(("CoinGecko", coingecko_btc))
    if key in ETF_PROXIES:
        etf = ETF_PROXIES[key]
        tries.append((f"{PROXY_PREFIX} {etf} (Nasdaq)", lambda: nasdaq_history(etf, "etf")))
    if not tries:
        raise NoFallback(f"no fallback for {key}")
    errors = []
    for label, fn in tries:
        try:
            s = fn()
            if len(s) < 20:
                raise ValueError(f"only {len(s)} rows")
            return s, label
        except Exception as err:
            errors.append(f"{label}: {err}")
    raise RuntimeError("; ".join(errors))
