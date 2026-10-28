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

from . import charts, dashboard, fetch, macro, narrative, report, sources, transform

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
          today: pd.Timestamp | None = None) -> dict:
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

    # ------------------------------------------------ markets (Yahoo)
    markets: dict[str, pd.Series] = {}
    for m in cfg.get("markets", []):
        try:
            s = get_yahoo(m["yahoo"])
            markets[m["key"]] = s
            record("Yahoo Finance", m["yahoo"], True, s.index[-1].date().isoformat())
        except Exception as err:
            _warn(f"Yahoo {m['yahoo']}: {err}")
            record("Yahoo Finance", m["yahoo"], False)
            if m.get("fred"):  # same quote convention on FRED (daily, published with a lag)
                try:
                    s = get_fred(m["fred"])
                    markets[m["key"]] = s
                    record("FRED (fallback)", m["fred"], True, s.index[-1].date().isoformat())
                except Exception as err2:
                    _warn(f"FRED fallback {m['fred']}: {err2}")
                    record("FRED (fallback)", m["fred"], False)

    # ------------------------------------------------ macro (FRED)
    fred: dict[str, pd.Series] = {}
    for f in cfg.get("fred", []):
        try:
            s = get_fred(f["id"])
            fred[f["id"]] = s
            record("FRED", f["id"], True, s.index[-1].date().isoformat())
        except Exception as err:
            _warn(f"FRED {f['id']}: {err}")
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
    fx_rows = macro.fx_rows(markets, cfg.get("markets", []))
    gic = macro.gold_in_currencies(markets)
    cmdty = macro.commodity_rows(markets, cfg.get("markets", []))
    rat = macro.ratios(markets)
    rat_now = {}
    for name, s in rat.items():
        five = s[s.index >= s.index[-1] - pd.Timedelta(days=365 * 5)]
        rat_now[name] = {"last": float(s.iloc[-1]), "pctile": macro.percentile_rank(five),
                         "m3": macro.pct_change_ago(s, 91)}
    cot_rows = macro.cot_rows(cot, cfg.get("cot", []))
    fomc = macro.next_fomc(cfg.get("fomc_decisions", []), today)
    dxy = markets.get("dxy", pd.Series(dtype="float64"))

    text = {
        "gold": narrative.gold_summary(gold_perf, gold_tech, sc),
        "macro": narrative.macro_summary(mrow_by_id, fomc),
        "fx": narrative.fx_summary(macro.performance(dxy), macro.technicals(dxy), fx_rows, gic),
        "cmdty": narrative.commodity_summary(cmdty, rat_now),
        "cot": narrative.cot_summary(cot_rows),
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
        "chains": [{"chain": c, "share": round(float(v), 2)} for c, v in
                   zip(first_chain.get("chain", []), first_chain.get("share_pct", []))][:8],
    }

    k = report.kpis(snapshot, history, spread, (a, b))
    notes_path = root / "notes.md"
    updated = report.now_utc()
    ctx = {
        "updated": updated, "scorecard": sc, "gold_perf": gold_perf, "gold_tech": gold_tech, "fomc": fomc,
        "gold_ccy": gic, "macro_rows": mrows, "fx_rows": fx_rows, "dxy_perf": macro.performance(dxy),
        "dxy_tech": macro.technicals(dxy), "cmdty_rows": cmdty, "cot_rows": cot_rows, "text": text,
        "notes": notes_path.read_text(encoding="utf-8") if notes_path.exists() else None,
        "token": {"snapshot": snapshot.to_dict("records") if not snapshot.empty else [], "pair": (a, b), "kpis": k,
                  "oz_last": float(ounces.iloc[-1]) if len(ounces) else None,
                  "oz_m1": macro.pct_change_ago(ounces, 30) if len(ounces) else None},
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
