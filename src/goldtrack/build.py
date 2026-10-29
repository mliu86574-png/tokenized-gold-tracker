"""End-to-end build: fetch -> tables -> analytics -> dashboard and README.

Run from the repository root:  python -m goldtrack.build
Every source is optional: a failing feed is recorded in data/status.json and
the rest of the page is still built.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Callable

import pandas as pd

from . import charts, dashboard, fetch, macro, narrative, official, report, sources, tokens as tk, transform

ROOT = Path(__file__).resolve().parents[2]


def _warn(msg: str) -> None:
    print(f"warning: {msg}", file=sys.stderr)


def build(root: Path = ROOT,
          get_markets: Callable = fetch.coingecko_markets,
          get_history: Callable = fetch.coingecko_history,
          get_protocols: Callable = fetch.defillama_protocols,
          get_yahoo: Callable = sources.yahoo_history,
          get_fred: Callable = sources.fred_series,
          get_cot: Callable = sources.cftc_cot,
          today: pd.Timestamp | None = None,
          get_alt: Callable = official.alt_market,
          get_official: Callable = official.official_series,
          get_token_extras: Callable = fetch.token_extras) -> dict:
    cfg = json.loads((root / "config.json").read_text())
    today = today or pd.Timestamp.now(tz="UTC").tz_localize(None)
    status: list[dict] = []
    data, img = root / "data", root / "docs" / "img"
    data.mkdir(exist_ok=True)
    img.mkdir(parents=True, exist_ok=True)

    def record(source, item, ok, last=None):
        status.append({"source": source, "item": item, "ok": ok, "last": last})

    # ------------------------------------------------ tokenized gold (CoinGecko / DefiLlama)
    tokens = cfg["tokens"]
    order = [t["symbol"] for t in tokens]
    try:
        snapshot = transform.snapshot_table(get_markets([t["coingecko_id"] for t in tokens]), tokens)
        record("CoinGecko", "markets", not snapshot.empty)
    except Exception as err:
        _warn(f"CoinGecko markets: {err}")
        snapshot = pd.DataFrame()
        record("CoinGecko", "markets", False)
    histories = {}
    for t in tokens:
        try:
            histories[t["symbol"]] = get_history(t["coingecko_id"], cfg.get("history_days", 365))
        except Exception as err:
            _warn(f"history unavailable for {t['symbol']}: {err}")
    history = transform.history_table(histories)
    record("CoinGecko", "history", bool(histories),
           str(history["date"].max()) if not history.empty else None)
    a, b = cfg.get("spread_pair", order[:2])
    spread = transform.price_spread_bps(history, a, b)
    chains = {}
    try:
        protocols = get_protocols()
        for t in tokens:
            df = transform.chain_distribution(fetch.find_protocol(protocols, t.get("defillama_name", "")))
            if not df.empty:
                chains[t["symbol"]] = df
        record("DefiLlama", "protocols", True)
    except Exception as err:
        _warn(f"DefiLlama unavailable: {err}")
        record("DefiLlama", "protocols", False)

    # ------------------------------------------------ tokenized gold: whole category, venues, DeFi
    try:
        extras = get_token_extras(tokens, cfg.get("category", "tokenized-gold")) or {}
    except Exception as err:
        _warn(f"token extras: {err}")
        extras = {}
    errs = extras.get("errors", {})
    # last-good cache: a rate-limited call shows the previous reading (labelled) instead of a gap
    cache_path = data / "token_cache.json"
    cache = json.loads(cache_path.read_text()) if cache_path.exists() else {}
    cached_from: dict[str, str] = {}
    if extras:
        day = today.date().isoformat()
        for key in ("category", "pools", "lend"):
            if extras.get(key) is not None:
                if key == "category":
                    cache[key] = {"date": day, "value": extras[key]}
            elif cache.get(key):
                extras[key] = cache[key]["value"]
                cached_from[key] = cache[key]["date"]
        cache = {k: v for k, v in cache.items() if v}
        tick_cache = cache.setdefault("tickers", {})
        for t in tokens:
            sym = t["symbol"]
            if sym in (extras.get("tickers") or {}):
                keep = ("base", "target", "bid_ask_spread_percentage", "cost_to_move_up_usd", "cost_to_move_down_usd",
                        "is_stale", "is_anomaly")
                slim = [{**{k: t_.get(k) for k in keep}, "market": {"name": (t_.get("market") or {}).get("name")},
                         "converted_volume": {"usd": (t_.get("converted_volume") or {}).get("usd")}}
                        for t_ in (extras["tickers"][sym] or {}).get("tickers", [])]
                tick_cache[sym] = {"date": day, "value": {"tickers": slim}}
            elif sym in tick_cache:
                extras.setdefault("tickers", {})[sym] = tick_cache[sym]["value"]
                cached_from[f"tickers {sym}"] = tick_cache[sym]["date"]
        cache_path.write_text(json.dumps(cache, separators=(",", ":")), encoding="utf-8")
    for key, src, item in [] if not extras else (("category", "CoinGecko", "category tokenized-gold"), ("pools", "DefiLlama", "yield pools"),
                           ("lend", "DefiLlama", "lend/borrow")):
        if errs.get(key):
            _warn(f"{src} {item}: {errs[key]}")
        label = f"{src} (cached {cached_from[key]})" if key in cached_from else src
        record(label, item, extras.get(key) is not None)
    for t in tokens if extras else []:
        sym = t["symbol"]
        if errs.get(f"tickers {sym}"):
            _warn(f"CoinGecko tickers {sym}: " + errs[f"tickers {sym}"])
        key = f"tickers {sym}"
        label = f"CoinGecko (cached {cached_from[key]})" if key in cached_from else "CoinGecko"
        record(label, key, sym in (extras.get("tickers") or {}))

    # ------------------------------------------------ markets: Yahoo -> other public feed -> FRED
    markets: dict[str, pd.Series] = {}
    proxies: dict[str, str] = {}  # market key -> ETF used as a stand-in for the futures price
    for m in cfg.get("markets", []):
        errors = []
        try:
            s = get_yahoo(m["yahoo"])
            markets[m["key"]] = s
            record("Yahoo Finance", m["yahoo"], True, s.index[-1].date().isoformat())
            continue
        except Exception as err:
            errors.append(f"Yahoo: {err}")
        try:
            s, label = get_alt(m)
            markets[m["key"]] = s
            if label.startswith(official.PROXY_PREFIX):
                proxies[m["key"]] = label.split()[2]
            record(label, m["yahoo"], True, s.index[-1].date().isoformat())
            continue
        except Exception as err:
            errors.append(f"fallback: {err}")
        if m.get("fred"):  # same quote convention on FRED (daily, published with a lag)
            try:
                s = get_fred(m["fred"])
                markets[m["key"]] = s
                record("FRED", m["yahoo"], True, s.index[-1].date().isoformat())
                continue
            except Exception as err:
                errors.append(f"FRED {m['fred']}: {err}")
        _warn(f"{m['yahoo']}: " + " | ".join(errors))
        record("Yahoo Finance", m["yahoo"], False)

    # gold is central to the page: put a GLD proxy back on a per-ounce footing using XAU₮
    if "gold" in proxies and not history.empty and a in set(history["symbol"]):
        h = history[history["symbol"] == a].set_index("date")["price_usd"].dropna()
        tok = pd.Series(h.values, index=pd.to_datetime(h.index))
        x, y = tok.align(markets["gold"], join="inner")
        if len(x) >= 20:
            k = float((x / y).median())
            markets["gold"] = markets["gold"] * k
            etf = proxies.pop("gold")
            for st in status:
                if st["item"] == "GC=F":
                    st["source"] = f"{etf} (Nasdaq) rescaled to {a} per-ounce price (x{k:.3f})"

    # ------------------------------------------------ macro: publishing agency first, then FRED
    fred: dict[str, pd.Series] = {}
    for f in cfg.get("fred", []):
        errors = []
        try:
            s, label = get_official(f["id"])
            fred[f["id"]] = s
            record(label, f["id"], True, s.index[-1].date().isoformat())
            continue
        except official.NoFallback:
            pass  # FRED is the only public source for this series
        except Exception as err:
            errors.append(f"official: {err}")
        try:
            s = get_fred(f["id"])
            fred[f["id"]] = s
            record("FRED", f["id"], True, s.index[-1].date().isoformat())
        except Exception as err:
            errors.append(f"FRED: {err}")
            _warn(f"{f['id']}: " + " | ".join(errors))
            record("FRED", f["id"], False)

    # ------------------------------------------------ positioning (CFTC)
    cot: dict[str, pd.DataFrame] = {}
    for c in cfg.get("cot", []):
        try:
            df = get_cot(c["code"])
            cot[c["key"]] = df
            record("CFTC", f"COT {c['en']}", True, df.index[-1].date().isoformat())
        except Exception as err:
            _warn(f"CFTC {c['code']}: {err}")
            record("CFTC", f"COT {c['en']}", False)

    # ------------------------------------------------ analytics
    gold = markets.get("gold")
    if gold is None:  # fall back to the largest per-ounce token so the page still renders
        if not history.empty and a in set(history["symbol"]):
            h = history[history["symbol"] == a].set_index("date")["price_usd"].dropna()
            gold = pd.Series(h.values, index=pd.to_datetime(h.index))
            markets["gold"] = gold
            record("CoinGecko (fallback)", f"gold price via {a}", True, gold.index[-1].date().isoformat())
        else:
            gold = pd.Series(dtype="float64")
    ounces = macro.token_ounces(history)
    units = {t["symbol"]: t.get("unit", "oz") for t in tokens}
    league, league_sum = tk.league_table(extras.get("category"), cfg.get("exclude_from_totals", {}),
                                         cfg.get("min_mcap_usd", 1e6))
    ref_oz = league_sum.get("ref_price") or (float(gold.iloc[-1]) if len(gold) else None)
    flows, weekly = tk.net_issuance(tk.ounces_by_token(history, units), ref_oz)
    venue_sum, venue_top = tk.venue_tables(extras.get("tickers") or {})
    defi_top, defi_proj, defi_stats = tk.defi_pools(extras.get("pools"), extras.get("lend"),
                                                    cfg.get("defi_symbols", [t["symbol"] for t in tokens]))
    gold_indep = not any(s_["source"] == "CoinGecko (fallback)" for s_ in status)
    gsrc = next((s_["source"] for s_ in status if s_["item"] == "GC=F" and s_["ok"]), "")
    gold_basis = "futures" if gsrc == "Yahoo Finance" else ("etf" if gsrc else "token")
    btc_src = next((s_["source"] for s_ in status if s_["item"] == "BTC-USD" and s_["ok"]), "")
    risk = tk.risk_table(history, units, gold, markets.get("btc"), gold_indep,
                         btc_lag_days=0 if btc_src.startswith("CoinGecko") else 1)
    if not gold.empty:
        read, sig = macro.factor_frame(gold, fred, markets, cot.get("gold"), ounces)
    else:
        read, sig = pd.DataFrame(), pd.DataFrame()
    sc = macro.scorecard(read, sig)
    levels = {k: float(v.iloc[-1]) for k, v in fred.items() if len(v)}
    for f in sc["factors"]:
        f["text"] = narrative.factor_reading(f, levels)

    gold_perf, gold_tech = macro.performance(gold), macro.technicals(gold)
    mrows = macro.macro_rows(fred, cfg.get("fred", []))
    mrow_by_id = {r["id"]: r for r in mrows}
    specs = [dict(m, en=f"{m['en']} ({proxies[m['key']]} ETF proxy)", zh=f"{m['zh']}（以 {proxies[m['key']]} ETF 代替）",
                  unit="ETF price") if m["key"] in proxies else m for m in cfg.get("markets", [])]
    fx_rows = macro.fx_rows(markets, specs)
    gic = macro.gold_in_currencies(markets)
    cmdty = macro.commodity_rows(markets, specs)
    rat = macro.ratios({k: v for k, v in markets.items() if k not in proxies})  # ETF levels would distort ratios
    rat_now = {}
    for name, s in rat.items():
        five = s[s.index >= s.index[-1] - pd.Timedelta(days=365 * 5)]
        rat_now[name] = {"last": float(s.iloc[-1]), "pctile": macro.percentile_rank(five),
                         "m3": macro.pct_change_ago(s, 91)}
    cot_rows = macro.cot_rows(cot, cfg.get("cot", []))
    fomc = macro.next_fomc(cfg.get("fomc_decisions", []), today)
    dxy = markets.get("dxy", pd.Series(dtype="float64"))

    text = {
        "gold": narrative.gold_summary(gold_perf, gold_tech, sc, gold_basis),
        "macro": narrative.macro_summary(mrow_by_id, fomc),
        "fx": narrative.fx_summary(macro.performance(dxy), macro.technicals(dxy), fx_rows, gic),
        "cmdty": narrative.commodity_summary(cmdty, rat_now),
        "cot": narrative.cot_summary(cot_rows),
        "token": tk.narrative(league_sum, flows, venue_sum, defi_stats),
    }

    # ------------------------------------------------ payload for charts
    P = dashboard.series_points
    series = {"gold": P(gold, 365 * 5, 2), "gold_2y": P(gold, 730, 2),
              "ma50": P(gold.rolling(50).mean(), 365 * 5, 2), "ma200": P(gold.rolling(200).mean(), 365 * 5, 2),
              "dxy": P(markets.get("dxy"), 365 * 5, 3)}
    if not sc["history"].empty:
        hist = sc["history"]
        hist = hist[hist["n"] >= 5]["score"]
        series["score"] = P(hist, 730, 0)
    for f in cfg.get("fred", []):
        if f["id"] in fred:
            s = macro.transform_fred(fred[f["id"]], f.get("kind", "level"), f.get("scale", 1.0))
            series[f["id"]] = P(s, 365 * 5, 3)
    for name, s in rat.items():
        series[name] = P(s, 365 * 5, 3)
    if "gold" in cot:
        series["cot_gold"] = P(cot["gold"]["mm_net"], 365 * 5, 0)
    series["token_oz"] = P(ounces, 400, 0)
    if not spread.empty:
        sp = spread.set_index(pd.to_datetime(spread["date"]))["spread_bps"]
        series["spread"] = P(sp, 400, 1)
    tok_series = []
    for sym in order:
        h = history[history["symbol"] == sym] if not history.empty else pd.DataFrame()
        if not h.empty:
            s = pd.Series(h["market_cap_usd"].values / 1e6, index=pd.to_datetime(h["date"]))
            tok_series.append({"symbol": sym, "mcap": P(s, 400, 1)})
    first_chain = next(iter(chains.values()), pd.DataFrame())
    payload = {
        "series": series,
        "bars": {
            "fx": [{"name": {"en": r["en"], "zh": r["zh"]}, "m1": _r(r["ccy_m1"]), "ytd": _r(r["ccy_ytd"])} for r in fx_rows],
            "cmdty": [{"name": {"en": r["en"], "zh": r["zh"]}, "m1": _r(r.get("m1")), "ytd": _r(r.get("ytd"))}
                      for r in cmdty if r["group"] != "index"],
        },
        "tokens": tok_series,
        "chains": ([{"chain": c, "share": round(float(v), 2)} for c, v in
                    zip(first_chain.get("chain", []), first_chain.get("share_pct", []))][:8]
                   or defi_stats.get("by_chain", [])),
        "tok_weekly": {"dates": [d.strftime("%Y-%m-%d") for d in weekly.index],
                       "series": [{"symbol": c, "data": [None if pd.isna(v) else round(float(v), 2) for v in weekly[c]]}
                                  for c in weekly.columns]} if not weekly.empty else {},
        "defi_proj": defi_proj,
        "venues": [{"k": f'{v["venue"]} · {v["symbol"]}', "v": round(v["volume"] / 1e6, 2), "dex": v["dex"]}
                   for v in venue_top],
        "league": [{"k": r["symbol"], "v": round(r["mcap"] / 1e6, 1)} for r in league.to_dict("records")
                   if not r["bridged"]][:12] if not league.empty else [],
    }

    k = report.kpis(snapshot, history, spread, (a, b))
    notes_path = root / "notes.md"
    updated = report.now_utc()
    ctx = {
        "updated": updated, "gold_basis": gold_basis, "scorecard": sc, "gold_perf": gold_perf, "gold_tech": gold_tech, "fomc": fomc,
        "gold_ccy": gic, "macro_rows": mrows, "fx_rows": fx_rows, "dxy_perf": macro.performance(dxy),
        "dxy_tech": macro.technicals(dxy), "cmdty_rows": cmdty, "cot_rows": cot_rows, "text": text,
        "notes": notes_path.read_text(encoding="utf-8") if notes_path.exists() else None,
        "token": {"snapshot": snapshot.to_dict("records") if not snapshot.empty else [], "pair": (a, b), "kpis": k,
                  "oz_last": float(ounces.iloc[-1]) if len(ounces) else None,
                  "oz_m1": macro.pct_change_ago(ounces, 30) if len(ounces) else None,
                  "league": league.to_dict("records") if not league.empty else [], "league_sum": league_sum,
                  "flows": flows, "venues": venue_sum, "venue_top": venue_top, "defi": defi_top,
                  "defi_stats": defi_stats, "risk": risk, "gold_indep": gold_indep,
                  "chain_basis": "supply" if not first_chain.empty else ("defi" if defi_stats.get("by_chain") else None)},
        "status": status, "payload": payload,
    }

    # ------------------------------------------------ write outputs
    snapshot.to_csv(data / "snapshot.csv", index=False)
    history.to_csv(data / "history.csv", index=False)
    spread.to_csv(data / "spread.csv", index=False)
    for sym, df in chains.items():
        df.to_csv(data / f"chains_{sym}.csv", index=False)
    if markets:
        pd.DataFrame(markets).sort_index().to_csv(data / "markets.csv", index_label="date")
    if fred:
        pd.DataFrame(fred).sort_index().to_csv(data / "macro.csv", index_label="date")
    for key, df in cot.items():
        df.to_csv(data / f"cot_{key}.csv", index_label="date")
    if not league.empty:
        league.drop(columns=["bridged"]).to_csv(data / "token_league.csv", index=False)
    for name, rows in (("token_flows", flows), ("token_venues", venue_sum), ("token_defi_pools", defi_top),
                       ("token_risk", risk)):
        if rows:
            pd.DataFrame(rows).to_csv(data / f"{name}.csv", index=False)
    sc_out = {"date": updated, "score": sc["score"], "factors_used": sc["n"], "stance": sc["stance"],
              "factors": [{"key": f["key"], "signal": f["signal"], "reading": f["reading"], "asof": f["asof"]}
                          for f in sc["factors"]]}
    (data / "scorecard.json").write_text(json.dumps(sc_out, indent=2), encoding="utf-8")
    (data / "status.json").write_text(json.dumps({"updated": updated, "sources": status}, indent=2), encoding="utf-8")

    (root / "docs" / "index.html").write_text(dashboard.render(ctx), encoding="utf-8")
    charts.scorecard_chart(gold, sc["history"], img / "scorecard.png")
    report.update_readme(root / "README.md", report.markdown_summary(sc, gold_perf, snapshot, updated))
    return {"snapshot": snapshot, "history": history, "spread": spread, "chains": chains, "kpis": k,
            "scorecard": sc, "markets": markets, "fred": fred, "cot": cot, "status": status}


def _r(x, dp=2):
    return None if x is None else round(float(x), dp)


if __name__ == "__main__":
    result = build()
    sc = result["scorecard"]
    print(f"score {sc['score']:+d} from {sc['n']} factors -> {sc['stance']}")
    failed = [f"{s['source']}:{s['item']}" for s in result["status"] if not s["ok"]]
    print("failed sources:", ", ".join(failed) if failed else "none")
