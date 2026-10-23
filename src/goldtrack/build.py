"""End-to-end build: fetch -> tables -> charts -> dashboard and README.

Run from the repository root:  python -m goldtrack.build
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Callable

import pandas as pd

from . import charts, fetch, report, transform

ROOT = Path(__file__).resolve().parents[2]


def build(root: Path = ROOT,
          get_markets: Callable = fetch.coingecko_markets,
          get_history: Callable = fetch.coingecko_history,
          get_protocols: Callable = fetch.defillama_protocols) -> dict:
    cfg = json.loads((root / "config.json").read_text())
    tokens = cfg["tokens"]
    order = [t["symbol"] for t in tokens]
    data, img = root / "data", root / "docs" / "img"
    data.mkdir(exist_ok=True)
    img.mkdir(parents=True, exist_ok=True)

    markets = get_markets([t["coingecko_id"] for t in tokens])
    snapshot = transform.snapshot_table(markets, tokens)

    histories = {}
    for t in tokens:
        try:
            histories[t["symbol"]] = get_history(t["coingecko_id"], cfg.get("history_days", 365))
        except Exception as err:  # one failing token should not stop the build
            print(f"warning: history unavailable for {t['symbol']}: {err}", file=sys.stderr)
    history = transform.history_table(histories)

    a, b = cfg.get("spread_pair", order[:2])
    spread = transform.price_spread_bps(history, a, b)

    chains = {}
    try:
        protocols = get_protocols()
        for t in tokens:
            df = transform.chain_distribution(fetch.find_protocol(protocols, t.get("defillama_name", "")))
            if not df.empty:
                chains[t["symbol"]] = df
    except Exception as err:
        print(f"warning: DefiLlama unavailable: {err}", file=sys.stderr)

    snapshot.to_csv(data / "snapshot.csv", index=False)
    history.to_csv(data / "history.csv", index=False)
    spread.to_csv(data / "spread.csv", index=False)
    for sym, df in chains.items():
        df.to_csv(data / f"chains_{sym}.csv", index=False)

    images = {}
    for alt, path in [
        ("Market capitalisation over time", charts.market_cap_history(history, img / "market_cap.png", order)),
        ("Market share among tracked tokens", charts.market_share(snapshot, img / "market_share.png", order)),
        (f"{a} vs {b} price spread", charts.spread_chart(spread, img / "spread.png", a, b)),
    ]:
        if path:
            images[alt] = f"img/{path.name}"
    for sym, df in chains.items():
        p = charts.chain_chart(df, img / f"chains_{sym}.png", sym)
        if p:
            images[f"{sym} distribution by chain"] = f"img/{p.name}"

    updated = report.now_utc()
    k = report.kpis(snapshot, history, spread, (a, b))
    (root / "docs" / "index.html").write_text(report.render_html(snapshot, k, images, updated), encoding="utf-8")
    report.update_readme(root / "README.md", report.markdown_table(snapshot, updated))
    return {"snapshot": snapshot, "history": history, "spread": spread, "chains": chains, "kpis": k}


if __name__ == "__main__":
    result = build()
    print(result["snapshot"].to_string(index=False) if not result["snapshot"].empty else "no market data")
