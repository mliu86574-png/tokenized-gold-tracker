"""Public macro and market data sources (no API keys).

* Yahoo Finance chart API  - daily closes for futures, FX, indices
* FRED (St. Louis Fed)     - rates, inflation, labour, dollar index, credit spreads
* CFTC Public Reporting    - weekly Commitments of Traders (disaggregated, futures only)
"""
from __future__ import annotations

import csv
import io
import json
import time
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone

import pandas as pd

BROWSER_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
YAHOO_HOSTS = ("https://query1.finance.yahoo.com", "https://query2.finance.yahoo.com")
FRED_CSV = "https://fred.stlouisfed.org/graph/fredgraph.csv"
CFTC_DISAGG = "https://publicreporting.cftc.gov/resource/72hh-3qpy.json"


# Fail fast: after three consecutive failures a host is skipped for the rest of the run,
# so one blocked provider cannot stall the daily build.
_FAILS: dict[str, int] = {}
MAX_HOST_FAILS = 3


def _host(url: str) -> str:
    return urllib.parse.urlsplit(url).netloc


def host_blocked(url: str) -> bool:
    return _FAILS.get(_host(url), 0) >= MAX_HOST_FAILS


def _get_text(url: str, params: dict | None = None, retries: int = 2, pause: float = 2.0,
              timeout: int = 15) -> str:
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"
    host = _host(url)
    if host_blocked(url):
        raise RuntimeError(f"skipped: {host} failed {MAX_HOST_FAILS} times in a row")
    last: Exception | None = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": BROWSER_UA, "Accept": "*/*"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                text = resp.read().decode("utf-8")
            _FAILS[host] = 0
            return text
        except Exception as err:  # network errors, 429 rate limits
            last = err
            if attempt + 1 < retries:
                time.sleep(pause * (attempt + 1))
    _FAILS[host] = _FAILS.get(host, 0) + 1
    raise RuntimeError(f"GET failed after {retries} attempts: {url} ({last})") from last


# ---------------------------------------------------------------- Yahoo
def parse_yahoo_chart(payload: dict) -> pd.Series:
    """Daily close series indexed by exchange-local date from a v8 chart response."""
    result = (payload.get("chart") or {}).get("result") or []
    if not result:
        raise ValueError("empty chart result")
    r = result[0]
    ts = r.get("timestamp") or []
    closes = ((r.get("indicators") or {}).get("quote") or [{}])[0].get("close") or []
    offset = (r.get("meta") or {}).get("gmtoffset", 0) or 0
    idx = [datetime.fromtimestamp(t + offset, tz=timezone.utc).date() for t in ts]
    s = pd.Series(closes, index=pd.to_datetime(idx), dtype="float64").dropna()
    s = s[~s.index.duplicated(keep="last")].sort_index()
    if s.empty:
        raise ValueError("no closes")
    return s


def yahoo_history(symbol: str, rng: str = "5y") -> pd.Series:
    last: Exception | None = None
    for host in YAHOO_HOSTS:
        try:
            text = _get_text(f"{host}/v8/finance/chart/{urllib.parse.quote(symbol)}",
                             {"range": rng, "interval": "1d", "includePrePost": "false"})
            return parse_yahoo_chart(json.loads(text))
        except Exception as err:
            last = err
    raise RuntimeError(f"Yahoo history unavailable for {symbol}") from last


# ---------------------------------------------------------------- FRED
def parse_fred_csv(text: str) -> pd.Series:
    """FRED graph CSV: first column is the date (header DATE or observation_date), '.' marks gaps."""
    rows = list(csv.reader(io.StringIO(text)))
    if len(rows) < 2:
        raise ValueError("empty FRED csv")
    dates, vals = [], []
    for row in rows[1:]:
        if len(row) < 2 or not row[0]:
            continue
        try:
            v = float(row[1])
        except ValueError:
            continue
        dates.append(row[0])
        vals.append(v)
    s = pd.Series(vals, index=pd.to_datetime(dates), dtype="float64").sort_index()
    if s.empty:
        raise ValueError("no FRED observations")
    return s


def fred_series(series_id: str, years: int = 6) -> pd.Series:
    start = (date.today() - timedelta(days=365 * years)).isoformat()
    return parse_fred_csv(_get_text(FRED_CSV, {"id": series_id, "cosd": start}))


# ---------------------------------------------------------------- CFTC
def parse_cot(rows: list[dict]) -> pd.DataFrame:
    """Managed-money positioning from disaggregated COT rows."""
    out = []
    for r in rows:
        try:
            out.append({
                "date": pd.to_datetime(r["report_date_as_yyyy_mm_dd"][:10]),
                "mm_long": float(r["m_money_positions_long_all"]),
                "mm_short": float(r["m_money_positions_short_all"]),
                "open_interest": float(r["open_interest_all"]),
            })
        except (KeyError, TypeError, ValueError):
            continue
    df = pd.DataFrame(out)
    if df.empty:
        raise ValueError("no COT rows")
    df = df.drop_duplicates("date").sort_values("date").set_index("date")
    df["mm_net"] = df["mm_long"] - df["mm_short"]
    df["mm_net_pct_oi"] = df["mm_net"] / df["open_interest"] * 100
    return df


def cftc_cot(contract_code: str, weeks: int = 260) -> pd.DataFrame:
    text = _get_text(CFTC_DISAGG, {
        "$where": f"cftc_contract_market_code='{contract_code}'",
        "$order": "report_date_as_yyyy_mm_dd DESC",
        "$limit": str(weeks),
    })
    return parse_cot(json.loads(text))
