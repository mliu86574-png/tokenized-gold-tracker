"""Render the static dashboard (docs/index.html) and the README snapshot table."""
from __future__ import annotations

import html
import re
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

START, END = "<!-- SNAPSHOT:START -->", "<!-- SNAPSHOT:END -->"


def _usd(x: float | None, unit: str = "auto") -> str:
    if x is None or pd.isna(x):
        return "–"
    if unit == "auto":
        unit = "bn" if abs(x) >= 1e9 else "m"
    div = {"bn": 1e9, "m": 1e6}[unit]
    return f"${x / div:,.2f}{unit}"


def _pct(x: float | None, signed: bool = True) -> str:
    if x is None or pd.isna(x):
        return "–"
    return f"{x:+.2f}%" if signed else f"{x:.1f}%"


def kpis(snapshot: pd.DataFrame, history: pd.DataFrame, spread: pd.DataFrame,
         pair: tuple[str, str]) -> dict:
    out = {"total_mcap": snapshot["market_cap_usd"].sum() if not snapshot.empty else None,
           "leader": None, "leader_share": None, "mcap_30d_change": None, "spread_bps": None}
    if not snapshot.empty:
        out["leader"] = snapshot.iloc[0]["symbol"]
        out["leader_share"] = snapshot.iloc[0]["market_share_pct"]
    if not history.empty:
        daily = history.groupby("date")["market_cap_usd"].sum().sort_index()
        if len(daily) > 30 and daily.iloc[-31] > 0:
            out["mcap_30d_change"] = (daily.iloc[-1] / daily.iloc[-31] - 1) * 100
    if not spread.empty:
        out["spread_bps"] = float(spread["spread_bps"].iloc[-1])
    out["pair"] = pair
    return out


def markdown_table(snapshot: pd.DataFrame, updated: str) -> str:
    if snapshot.empty:
        return f"_No data yet. Run the workflow to populate. Last attempt: {updated}_"
    lines = ["| Token | Market cap | Share | Price (USD) | 24h volume | 30d price change |",
             "|---|---:|---:|---:|---:|---:|"]
    for _, r in snapshot.iterrows():
        lines.append(f"| {r['symbol']} ({r['name']}) | {_usd(r['market_cap_usd'])} | "
                     f"{_pct(r['market_share_pct'], False)} | {r['price_usd']:,.2f} | "
                     f"{_usd(r['volume_24h_usd'])} | {_pct(r['change_30d_pct'])} |")
    lines.append(f"\n_Last updated {updated} (UTC). Source: CoinGecko, DefiLlama._")
    return "\n".join(lines)


def markdown_summary(sc: dict, gold_perf: dict, snapshot: pd.DataFrame, updated: str) -> str:
    """README block: scorecard headline, factor signals and the token snapshot."""
    from .macro import STANCE_TEXT
    if not sc.get("factors"):
        return markdown_table(snapshot, updated)
    stance_en = STANCE_TEXT[sc["stance"]][0]
    sym = {1: "▲ supportive", -1: "▼ headwind", 0: "● neutral", None: "n/a"}
    lines = [f"**Gold scorecard: {stance_en} ({sc['score']:+d} from {sc['n']} factors).** "
             f"Gold last {gold_perf.get('last', 0):,.2f} USD/oz, "
             f"{_pct(gold_perf.get('m1'))} over one month.", "",
             "![Scorecard](docs/img/scorecard.png)", "",
             "| Factor | Signal |", "|---|---|"]
    for f in sc["factors"]:
        s = f.get("signal")
        lines.append(f"| {f['en']} | {sym[None if s is None else int(s)]} |")
    lines += ["", markdown_table(snapshot, updated)]
    return "\n".join(lines)


def update_readme(readme: Path, table_md: str) -> None:
    text = readme.read_text(encoding="utf-8")
    block = f"{START}\n{table_md}\n{END}"
    if START in text and END in text:
        text = re.sub(re.escape(START) + r".*?" + re.escape(END), lambda _: block, text, flags=re.S)
    else:
        text += "\n" + block + "\n"
    readme.write_text(text, encoding="utf-8")


def now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
