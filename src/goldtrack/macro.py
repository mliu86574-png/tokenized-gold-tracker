"""Analytics for the gold & macro monitor: performance, technicals, macro tables,
positioning, ratios and the rules-based gold scorecard.

Every number here is derived mechanically from public data. The scorecard is a
transparent checklist of conditions that have historically mattered for gold;
it is not a forecast and not investment advice.
"""
from __future__ import annotations

from math import sqrt

import numpy as np
import pandas as pd

GRAMS_PER_OZ = 31.1034768


# ---------------------------------------------------------------- helpers
def _f(x) -> float | None:
    if x is None:
        return None
    try:
        x = float(x)
    except (TypeError, ValueError):
        return None
    return None if np.isnan(x) else x


def calendar_ffill(s: pd.Series) -> pd.Series:
    """Reindex to calendar days with forward fill so look-backs use calendar time."""
    if s.empty:
        return s
    idx = pd.date_range(s.index.min(), s.index.max(), freq="D")
    return s.reindex(idx).ffill()


def value_ago(s: pd.Series, days: int) -> float | None:
    if s.empty:
        return None
    target = s.index[-1] - pd.Timedelta(days=days)
    if target < s.index[0]:
        return None
    return _f(s.asof(target))


def pct_change_ago(s: pd.Series, days: int) -> float | None:
    past = value_ago(s, days)
    last = _f(s.iloc[-1]) if not s.empty else None
    if past in (None, 0) or last is None:
        return None
    return (last / past - 1) * 100


def ytd_change(s: pd.Series) -> float | None:
    if s.empty:
        return None
    start = pd.Timestamp(year=s.index[-1].year, month=1, day=1)
    prior = s[s.index < start]
    if prior.empty:
        return None
    return (s.iloc[-1] / prior.iloc[-1] - 1) * 100


def performance(s: pd.Series) -> dict:
    s = s.dropna()
    if s.empty:
        return {}
    d1 = (s.iloc[-1] / s.iloc[-2] - 1) * 100 if len(s) > 1 else None
    return {"last": _f(s.iloc[-1]), "date": s.index[-1].date().isoformat(), "d1": _f(d1),
            "w1": pct_change_ago(s, 7), "m1": pct_change_ago(s, 30), "m3": pct_change_ago(s, 91),
            "ytd": ytd_change(s), "y1": pct_change_ago(s, 365)}


def rsi(s: pd.Series, n: int = 14) -> pd.Series:
    d = s.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    rs = up / dn.replace(0, np.nan)
    return (100 - 100 / (1 + rs)).fillna(100)


def technicals(s: pd.Series) -> dict:
    s = s.dropna()
    if len(s) < 30:
        return {}
    last = s.iloc[-1]
    ma50 = s.rolling(50).mean().iloc[-1] if len(s) >= 50 else np.nan
    ma200 = s.rolling(200).mean().iloc[-1] if len(s) >= 200 else np.nan
    year = s[s.index > s.index[-1] - pd.Timedelta(days=365)]
    rets = np.log(s).diff().dropna().iloc[-21:]
    hi, lo = year.max(), year.min()
    if np.isnan(ma50) or np.isnan(ma200):
        trend = "mixed"
    elif last > ma50 > ma200:
        trend = "up"
    elif last < ma50 < ma200:
        trend = "down"
    else:
        trend = "mixed"
    return {"ma50": _f(ma50), "ma200": _f(ma200), "rsi14": _f(rsi(s).iloc[-1]),
            "vol30": _f(rets.std() * sqrt(252) * 100), "hi52": _f(hi), "lo52": _f(lo),
            "from_hi": _f((last / hi - 1) * 100), "from_lo": _f((last / lo - 1) * 100),
            "vs_ma200": _f((last / ma200 - 1) * 100) if not np.isnan(ma200) else None,
            "vs_ma50": _f((last / ma50 - 1) * 100) if not np.isnan(ma50) else None,
            "trend": trend}


def percentile_rank(s: pd.Series, value: float | None = None) -> float | None:
    s = s.dropna()
    if s.empty:
        return None
    v = s.iloc[-1] if value is None else value
    return float((s <= v).mean() * 100)


# ---------------------------------------------------------------- macro (FRED)
def transform_fred(s: pd.Series, kind: str, scale: float = 1.0) -> pd.Series:
    s = s.dropna() * scale
    if kind == "yoy":
        return ((s / s.shift(12) - 1) * 100).dropna()
    if kind == "diff":
        return s.diff().dropna()
    return s


def macro_rows(fred: dict[str, pd.Series], specs: list[dict]) -> list[dict]:
    rows = []
    for spec in specs:
        raw = fred.get(spec["id"])
        if raw is None or raw.empty:
            continue
        s = transform_fred(raw, spec.get("kind", "level"), spec.get("scale", 1.0))
        if s.empty:
            continue
        monthly = (s.index.to_series().diff().dt.days.median() or 1) > 20
        prev = _f(s.iloc[-2]) if monthly and len(s) > 1 else value_ago(s, 30)
        last = _f(s.iloc[-1])
        rows.append({"id": spec["id"], "en": spec["en"], "zh": spec["zh"], "unit": spec.get("unit", ""),
                     "last": last, "date": s.index[-1].date().isoformat(), "prev": prev,
                     "change": None if prev is None or last is None else last - prev,
                     "y1": value_ago(s, 365), "monthly": bool(monthly)})
    return rows


# ---------------------------------------------------------------- FX and gold in currencies
def fx_rows(markets: dict[str, pd.Series], specs: list[dict]) -> list[dict]:
    """Changes expressed as the currency's move against USD (positive = currency stronger)."""
    rows = []
    for spec in specs:
        if spec["group"] != "fx" or spec["key"] == "dxy" or spec["key"] not in markets:
            continue
        p = performance(markets[spec["key"]])
        sign = -1 if spec.get("usd_base") else 1
        conv = {k: (None if p.get(k) is None else sign * p[k]) for k in ("d1", "w1", "m1", "ytd", "y1")}
        rows.append({"key": spec["key"], "en": spec["en"], "zh": spec["zh"], "last": p.get("last"),
                     "date": p.get("date"), **{f"ccy_{k}": v for k, v in conv.items()},
                     "trend": technicals(markets[spec["key"]]).get("trend")})
    return rows


def gold_in_currencies(markets: dict[str, pd.Series]) -> list[dict]:
    """Gold priced in other currencies, with the conventional local unit."""
    gold = markets.get("gold")
    if gold is None:
        return []
    out = [{"ccy": "USD", "unit_en": "USD/oz", "unit_zh": "美元/盎司", "series": gold}]
    defs = [("eur", "EUR", False, 1.0, "EUR/oz", "欧元/盎司"),
            ("gbp", "GBP", False, 1.0, "GBP/oz", "英镑/盎司"),
            ("jpy", "JPY", True, 1 / GRAMS_PER_OZ, "JPY/g", "日元/克"),
            ("cny", "CNY", True, 1 / GRAMS_PER_OZ, "CNY/g", "人民币/克"),
            ("hkd", "HKD", True, 1.0, "HKD/oz", "港币/盎司")]
    for key, ccy, usd_base, scale, u_en, u_zh in defs:
        fx = markets.get(key)
        if fx is None:
            continue
        g, f = gold.align(fx, join="inner")
        local = (g * f if usd_base else g / f) * scale
        out.append({"ccy": ccy, "unit_en": u_en, "unit_zh": u_zh, "series": local.dropna()})
    rows = []
    for o in out:
        p = performance(o["series"])
        t = technicals(o["series"])
        rows.append({"ccy": o["ccy"], "unit_en": o["unit_en"], "unit_zh": o["unit_zh"], "last": p.get("last"),
                     "m1": p.get("m1"), "ytd": p.get("ytd"), "y1": p.get("y1"), "from_hi": t.get("from_hi")})
    return rows


# ---------------------------------------------------------------- commodities and ratios
def commodity_rows(markets: dict[str, pd.Series], specs: list[dict]) -> list[dict]:
    rows = []
    for spec in specs:
        if spec["group"] not in ("metals", "energy", "agri", "index") or spec["key"] not in markets:
            continue
        s = markets[spec["key"]]
        rows.append({"key": spec["key"], "en": spec["en"], "zh": spec["zh"], "group": spec["group"],
                     "unit": spec.get("unit", ""), **performance(s), **technicals(s)})
    return rows


def ratios(markets: dict[str, pd.Series]) -> dict[str, pd.Series]:
    out = {}

    def _ratio(a, b, mult=1.0):
        if a in markets and b in markets:
            x, y = markets[a].align(markets[b], join="inner")
            r = (x / y * mult).replace([np.inf, -np.inf], np.nan).dropna()
            if not r.empty:
                return r
        return None

    for name, a, b, mult in [("gold_silver", "gold", "silver", 1.0),
                             ("copper_gold", "copper", "gold", 1000.0),
                             ("gold_oil", "gold", "brent", 1.0),
                             ("gold_spx", "gold", "spx", 1.0)]:
        r = _ratio(a, b, mult)
        if r is not None:
            out[name] = r
    return out


# ---------------------------------------------------------------- positioning
def cot_rows(cot: dict[str, pd.DataFrame], specs: list[dict]) -> list[dict]:
    rows = []
    for spec in specs:
        df = cot.get(spec["key"])
        if df is None or df.empty:
            continue
        last = df.iloc[-1]
        window = df["mm_net_pct_oi"].iloc[-156:]
        rows.append({"key": spec["key"], "en": spec["en"], "zh": spec["zh"], "date": df.index[-1].date().isoformat(),
                     "net": _f(last["mm_net"]), "net_pct_oi": _f(last["mm_net_pct_oi"]),
                     "wk_change": _f(df["mm_net"].diff().iloc[-1]) if len(df) > 1 else None,
                     "pctile_3y": percentile_rank(window), "oi": _f(last["open_interest"])})
    return rows


# ---------------------------------------------------------------- tokenized gold supply
def token_ounces(history: pd.DataFrame, symbols: tuple[str, ...] = ("XAUT", "PAXG")) -> pd.Series:
    """Implied ounces outstanding = market cap / price, summed over per-ounce tokens."""
    if history.empty:
        return pd.Series(dtype="float64")
    h = history[history["symbol"].isin(symbols)].copy()
    h["oz"] = h["market_cap_usd"] / h["price_usd"]
    s = h.groupby("date")["oz"].sum(min_count=1).dropna()
    s.index = pd.to_datetime(s.index)
    # drop days where only one token reported
    counts = h.dropna(subset=["oz"]).groupby("date")["symbol"].nunique()
    counts.index = pd.to_datetime(counts.index)
    return s[counts.reindex(s.index).fillna(0) == len(symbols)].sort_index()


# ---------------------------------------------------------------- scorecard
FACTORS = [
    {"key": "real_yield", "en": "US real yields", "zh": "美国实际利率",
     "rule_en": "10Y TIPS yield, 30-day change: ≤ −10 bp supportive, ≥ +10 bp headwind",
     "rule_zh": "10年期 TIPS 收益率 30 天变动：下降 ≥10bp 利好，上升 ≥10bp 利空"},
    {"key": "usd", "en": "US dollar", "zh": "美元",
     "rule_en": "Broad dollar index, 30-day change: ≤ −1% supportive, ≥ +1% headwind",
     "rule_zh": "广义美元指数 30 天变动：下跌 ≥1% 利好，上涨 ≥1% 利空"},
    {"key": "policy", "en": "Fed policy expectations", "zh": "美联储政策预期",
     "rule_en": "2Y Treasury yield, 30-day change: ≤ −15 bp supportive, ≥ +15 bp headwind",
     "rule_zh": "2年期美债收益率 30 天变动：下降 ≥15bp 利好，上升 ≥15bp 利空"},
    {"key": "inflation", "en": "Inflation expectations", "zh": "通胀预期",
     "rule_en": "10Y breakeven, 30-day change: ≥ +10 bp supportive, ≤ −10 bp headwind",
     "rule_zh": "10年期盈亏平衡通胀 30 天变动：上升 ≥10bp 利好，下降 ≥10bp 利空"},
    {"key": "risk", "en": "Risk appetite", "zh": "风险偏好",
     "rule_en": "Supportive if HY spread widens ≥ 40 bp in 30 days or VIX ≥ 25; headwind if spread tightens ≥ 40 bp and VIX ≤ 15",
     "rule_zh": "高收益债利差 30 天走阔 ≥40bp 或 VIX ≥25 为利好（避险）；利差收窄 ≥40bp 且 VIX ≤15 为利空"},
    {"key": "trend", "en": "Price trend", "zh": "价格趋势",
     "rule_en": "Price above both 50- and 200-day averages supportive; below both headwind",
     "rule_zh": "价格同时高于 50 日和 200 日均线为利好，同时低于为利空"},
    {"key": "stretch", "en": "Short-term stretch", "zh": "短期超买超卖",
     "rule_en": "14-day RSI ≤ 30 (oversold) supportive; ≥ 70 (overbought) headwind",
     "rule_zh": "14 日 RSI ≤30（超卖）利好，≥70（超买）利空"},
    {"key": "positioning", "en": "Futures positioning", "zh": "期货持仓",
     "rule_en": "Managed-money net long (% of open interest) vs its 3-year range: ≤ 20th percentile supportive, ≥ 80th crowded",
     "rule_zh": "管理基金净多头占持仓比例在 3 年区间的分位：≤20% 利好（仓位轻），≥80% 利空（拥挤）"},
    {"key": "onchain", "en": "Tokenized gold demand", "zh": "链上黄金需求",
     "rule_en": "XAU₮ + PAXG ounces outstanding, 30-day change: ≥ +2% supportive, ≤ −2% headwind",
     "rule_zh": "XAU₮ + PAXG 流通盎司数 30 天变动：增加 ≥2% 利好，减少 ≥2% 利空"},
]


def _chg(s: pd.Series, days: int = 30, pct: bool = False) -> pd.Series:
    c = calendar_ffill(s.dropna())
    if c.empty:
        return c
    return (c / c.shift(days) - 1) * 100 if pct else c - c.shift(days)


def _sig(x: pd.Series, pos: pd.Series, neg: pd.Series) -> pd.Series:
    out = pd.Series(0.0, index=x.index)
    out[pos.reindex(x.index).fillna(False)] = 1.0
    out[neg.reindex(x.index).fillna(False)] = -1.0
    out[x.isna()] = np.nan
    return out


def factor_frame(gold: pd.Series, fred: dict[str, pd.Series], markets: dict[str, pd.Series],
                 cot_gold: pd.DataFrame | None, ounces: pd.Series | None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Daily (calendar) readings and signals for each factor."""
    gold = gold.dropna()
    idx = pd.date_range(gold.index.min(), gold.index.max(), freq="D")
    read, sig = pd.DataFrame(index=idx), pd.DataFrame(index=idx)

    def put(key, reading: pd.Series, pos, neg):
        # carry the latest observation forward up to 10 days (weekly COT, FRED publication lag)
        r = reading.reindex(reading.index.union(idx)).ffill(limit=10).reindex(idx)
        read[key] = r
        sig[key] = _sig(r, pos(r), neg(r))

    if "DFII10" in fred:
        put("real_yield", _chg(fred["DFII10"]) * 100, lambda r: r <= -10, lambda r: r >= 10)
    usd = fred.get("DTWEXBGS")
    if usd is None or usd.empty:
        usd = markets.get("dxy")
    if usd is not None and not usd.empty:
        put("usd", _chg(usd, pct=True), lambda r: r <= -1, lambda r: r >= 1)
    if "DGS2" in fred:
        put("policy", _chg(fred["DGS2"]) * 100, lambda r: r <= -15, lambda r: r >= 15)
    if "T10YIE" in fred:
        put("inflation", _chg(fred["T10YIE"]) * 100, lambda r: r >= 10, lambda r: r <= -10)
    if "BAMLH0A0HYM2" in fred:
        def _carry(s):
            return s.reindex(s.index.union(idx)).ffill(limit=10).reindex(idx)
        hy = _carry(_chg(fred["BAMLH0A0HYM2"]) * 100)
        vix = _carry(calendar_ffill(fred["VIXCLS"])) if "VIXCLS" in fred else pd.Series(np.nan, index=idx)
        read["risk"] = hy
        read["risk_vix"] = vix
        sig["risk"] = _sig(hy, (hy >= 40) | (vix >= 25), (hy <= -40) & (vix <= 15))
    g = calendar_ffill(gold)
    ma50 = calendar_ffill(gold.rolling(50).mean())
    ma200 = calendar_ffill(gold.rolling(200).mean())
    trend_read = ((g / ma200 - 1) * 100).reindex(idx)
    read["trend"] = trend_read
    read["trend_ma50"] = ((g / ma50 - 1) * 100).reindex(idx)
    sig["trend"] = _sig(trend_read, (g > ma50) & (g > ma200), (g < ma50) & (g < ma200))
    put("stretch", calendar_ffill(rsi(gold)), lambda r: r <= 30, lambda r: r >= 70)
    if cot_gold is not None and not cot_gold.empty:
        pr = cot_gold["mm_net_pct_oi"].rolling(156, min_periods=52).apply(
            lambda x: (x <= x[-1]).mean() * 100, raw=True)
        pr = pr.dropna()
        if not pr.empty:
            put("positioning", calendar_ffill(pr), lambda r: r <= 20, lambda r: r >= 80)
    if ounces is not None and len(ounces) > 31:
        put("onchain", _chg(ounces, pct=True), lambda r: r >= 2, lambda r: r <= -2)
    return read, sig


def stance(score: float, n: int) -> str:
    if n == 0:
        return "na"
    if score >= 3:
        return "constructive"
    if score <= -3:
        return "cautious"
    return "neutral"


STANCE_TEXT = {"constructive": ("Constructive", "偏多"), "neutral": ("Neutral", "中性"),
               "cautious": ("Cautious", "偏谨慎"), "na": ("Insufficient data", "数据不足")}


def scorecard(read: pd.DataFrame, sig: pd.DataFrame) -> dict:
    if sig.empty:
        return {"score": 0, "n": 0, "stance": "na", "factors": [], "history": pd.DataFrame()}
    factors = []
    for f in FACTORS:
        k = f["key"]
        if k not in sig or sig[k].dropna().empty:
            factors.append({**f, "signal": None, "reading": None, "asof": None})
            continue
        last_i = sig[k].last_valid_index()
        factors.append({**f, "signal": _f(sig[k].loc[last_i]), "reading": _f(read[k].loc[last_i]),
                        "extra": _f(read["risk_vix"].loc[last_i]) if k == "risk" and "risk_vix" in read else
                        (_f(read["trend_ma50"].loc[last_i]) if k == "trend" else None),
                        "asof": last_i.date().isoformat()})
    valid = [f for f in factors if f["signal"] is not None]
    score = sum(f["signal"] for f in valid)
    hist = pd.DataFrame({"score": sig.sum(axis=1, min_count=1), "n": sig.notna().sum(axis=1)})
    return {"score": int(score), "n": len(valid), "stance": stance(score, len(valid)),
            "factors": factors, "history": hist}


def next_fomc(decisions: list[dict], today: pd.Timestamp) -> dict | None:
    for d in decisions:
        ts = pd.Timestamp(d["date"])
        if ts.normalize() >= today.normalize():
            return {"date": d["date"], "sep": d.get("sep", False), "days": int((ts - today.normalize()).days)}
    return None
