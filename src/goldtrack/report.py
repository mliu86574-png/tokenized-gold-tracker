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


def update_readme(readme: Path, table_md: str) -> None:
    text = readme.read_text(encoding="utf-8")
    block = f"{START}\n{table_md}\n{END}"
    if START in text and END in text:
        text = re.sub(re.escape(START) + r".*?" + re.escape(END), lambda _: block, text, flags=re.S)
    else:
        text += "\n" + block + "\n"
    readme.write_text(text, encoding="utf-8")


def render_html(snapshot: pd.DataFrame, k: dict, images: dict[str, str], updated: str) -> str:
    a, b = k["pair"]
    cards = [
        ("Tracked market cap", _usd(k["total_mcap"], "bn")),
        (f"Largest token", f"{k['leader'] or '–'} · {_pct(k['leader_share'], False)}"),
        ("30-day change in market cap", _pct(k["mcap_30d_change"])),
        (f"{a} vs {b} price spread", "–" if k["spread_bps"] is None else f"{k['spread_bps']:+.0f} bps"),
    ]
    card_html = "".join(f'<div class="card"><div class="lbl">{html.escape(l)}</div><div class="val">{html.escape(v)}</div></div>'
                        for l, v in cards)
    rows = ""
    for _, r in snapshot.iterrows():
        rows += (f"<tr><td>{html.escape(r['symbol'])}</td><td>{html.escape(r['name'])}</td>"
                 f"<td>{_usd(r['market_cap_usd'])}</td><td>{_pct(r['market_share_pct'], False)}</td>"
                 f"<td>{r['price_usd']:,.2f}</td><td>{_usd(r['volume_24h_usd'])}</td>"
                 f"<td>{_pct(r['change_30d_pct'])}</td></tr>")
    figs = "".join(f'<figure><img src="{src}" alt="{html.escape(alt)}"><figcaption>{html.escape(alt)}</figcaption></figure>'
                   for alt, src in images.items())
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Tokenized Gold Tracker</title>
<style>
:root{{--bg:#fbfaf7;--fg:#1d2433;--muted:#667085;--card:#fff;--line:#e6e2d8;--accent:#b8860b}}
@media (prefers-color-scheme:dark){{:root{{--bg:#14171c;--fg:#e8e6e1;--muted:#9aa1ad;--card:#1c2027;--line:#2c313a;--accent:#d4a63a}}}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--fg);font:15px/1.55 -apple-system,Segoe UI,Roboto,sans-serif}}
main{{max-width:960px;margin:0 auto;padding:32px 16px 64px}}h1{{margin:0 0 4px;font-size:28px}}
.sub{{color:var(--muted);margin-bottom:24px}}.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:12px;margin-bottom:28px}}
.card{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px 16px}}
.lbl{{color:var(--muted);font-size:13px}}.val{{font-size:22px;font-weight:600;margin-top:4px;color:var(--accent)}}
.tbl{{overflow-x:auto;margin-bottom:28px}}table{{border-collapse:collapse;width:100%;background:var(--card);border:1px solid var(--line);border-radius:10px}}
th,td{{padding:8px 10px;border-bottom:1px solid var(--line);text-align:right;white-space:nowrap}}th:nth-child(-n+2),td:nth-child(-n+2){{text-align:left}}
figure{{margin:0 0 24px;background:#fff;border:1px solid var(--line);border-radius:10px;padding:8px}}img{{width:100%;height:auto;display:block}}
figcaption{{color:#667085;font-size:13px;padding:4px 6px}}footer{{color:var(--muted);font-size:13px;border-top:1px solid var(--line);padding-top:16px}}
a{{color:var(--accent)}}
</style></head><body><main>
<h1>Tokenized Gold Tracker</h1>
<div class="sub">Public market data on gold-backed tokens · updated {html.escape(updated)} UTC</div>
<div class="grid">{card_html}</div>
<div class="tbl"><table><thead><tr><th>Token</th><th>Name</th><th>Market cap</th><th>Share</th><th>Price (USD)</th><th>24h volume</th><th>30d change</th></tr></thead>
<tbody>{rows}</tbody></table></div>
{figs}
<footer>Data: <a href="https://www.coingecko.com">CoinGecko</a> and <a href="https://defillama.com">DefiLlama</a> public APIs, refreshed daily by GitHub Actions.
Market share is among the tokens tracked here, not the whole market. For information only; not investment advice.</footer>
</main></body></html>"""


def now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
