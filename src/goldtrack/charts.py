"""Charts for the tracker. Each function writes a PNG and returns its path."""
from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

PALETTE = ["#1B355E", "#B8860B", "#0F7C8A", "#8E5572", "#6B8F3A", "#8A8F98"]
plt.rcParams.update({
    "figure.dpi": 130, "axes.spines.top": False, "axes.spines.right": False,
    "axes.grid": True, "grid.alpha": 0.3, "font.size": 10,
})


def _colours(symbols: list[str]) -> dict[str, str]:
    return {s: PALETTE[i % len(PALETTE)] for i, s in enumerate(symbols)}


def market_cap_history(history: pd.DataFrame, out: Path, order: list[str]) -> Path | None:
    if history.empty:
        return None
    colours = _colours(order)
    fig, ax = plt.subplots(figsize=(8, 3.8))
    for sym in order:
        s = history[history["symbol"] == sym]
        if s.empty:
            continue
        ax.plot(pd.to_datetime(s["date"]), s["market_cap_usd"] / 1e9, label=sym, color=colours[sym], lw=1.8)
    ax.set(ylabel="Market cap (USD bn)", title="Tokenized gold market capitalisation")
    ax.legend(frameon=False, ncol=len(order))
    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig(out)
    plt.close(fig)
    return out


def market_share(snapshot: pd.DataFrame, out: Path, order: list[str]) -> Path | None:
    if snapshot.empty:
        return None
    colours = _colours(order)
    df = snapshot.sort_values("market_share_pct")
    fig, ax = plt.subplots(figsize=(8, 0.6 * len(df) + 1.2))
    bars = ax.barh(df["symbol"], df["market_share_pct"], color=[colours.get(s, PALETTE[-1]) for s in df["symbol"]])
    for bar, val in zip(bars, df["market_share_pct"]):
        ax.text(bar.get_width() + 0.5, bar.get_y() + bar.get_height() / 2, f"{val:.1f}%", va="center")
    ax.set(xlabel="Share of tracked market cap (%)", title="Market share among tracked tokens")
    ax.set_xlim(0, max(df["market_share_pct"]) * 1.15)
    ax.grid(axis="y", visible=False)
    fig.tight_layout()
    fig.savefig(out)
    plt.close(fig)
    return out


def spread_chart(spread: pd.DataFrame, out: Path, a: str, b: str) -> Path | None:
    if spread.empty:
        return None
    fig, ax = plt.subplots(figsize=(8, 3.2))
    ax.plot(pd.to_datetime(spread["date"]), spread["spread_bps"], color=PALETTE[0], lw=1.3)
    ax.axhline(0, color=PALETTE[-1], lw=1)
    ax.set(ylabel="Basis points", title=f"{a} price relative to {b} (daily close)")
    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig(out)
    plt.close(fig)
    return out


def chain_chart(chains: pd.DataFrame, out: Path, symbol: str, top: int = 8) -> Path | None:
    if chains.empty:
        return None
    df = chains.head(top).iloc[::-1]
    fig, ax = plt.subplots(figsize=(8, 0.45 * len(df) + 1.2))
    ax.barh(df["chain"], df["share_pct"], color=PALETTE[1])
    for y, val in enumerate(df["share_pct"]):
        ax.text(val + 0.5, y, f"{val:.1f}%", va="center")
    ax.set(xlabel="Share of value (%)", title=f"{symbol}: distribution by chain (DefiLlama)")
    ax.set_xlim(0, max(df["share_pct"]) * 1.15)
    ax.grid(axis="y", visible=False)
    fig.tight_layout()
    fig.savefig(out)
    plt.close(fig)
    return out
