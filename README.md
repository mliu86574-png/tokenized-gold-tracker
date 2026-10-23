# Tokenized Gold Tracker

A small, automated tracker of gold-backed tokens using only public data. Every day a GitHub Actions job pulls market data, rebuilds the charts and publishes a static dashboard with GitHub Pages.

> 中文简介：一个每天自动更新的代币化黄金追踪看板，只使用公开数据（CoinGecko、DefiLlama）。追踪 XAU₮、PAXG、XAUm、KAU 等黄金代币的市值、市场份额、成交量、各链分布，以及 XAU₮ 与 PAXG 之间的价差。

**Live dashboard:** `https://<your-username>.github.io/tokenized-gold-tracker/` (available after the setup steps below)

## Why this exists

Tokenized gold is one of the largest real-world-asset categories on-chain. Two questions come up whenever an exchange, lender or wallet considers adding a gold token:

1. **How big and how liquid is each token?** Market cap, share and turnover show which tokens have real depth.
2. **Do tokens that represent the same ounce trade at the same price?** XAU₮ and PAXG each represent one fine troy ounce. A persistent spread between them points to differences in liquidity, redemption access or market structure.

## What it tracks

| Metric | Definition | Source |
|---|---|---|
| Market cap, price, 24h volume | Latest values per token | CoinGecko `/coins/markets` |
| Market share | Token market cap ÷ total of the tokens tracked here (not the whole market) | Derived |
| Volume / market cap | 24h volume ÷ market cap, a simple turnover measure | Derived |
| Market-cap history | Daily market cap over the past year | CoinGecko `/coins/{id}/market_chart` |
| XAU₮–PAXG spread | (XAU₮ price ÷ PAXG price − 1) × 10,000, in basis points | Derived |
| Chain distribution | Value by blockchain, where DefiLlama tracks the asset as a protocol | DefiLlama `/protocols` |

Tokens are listed in [`config.json`](config.json) and can be changed without touching code. Note that KAU is denominated per gram, so its unit price is not comparable with the per-ounce tokens; market cap and share are still comparable.

## Latest snapshot

<!-- SNAPSHOT:START -->
_No data yet. The first scheduled or manual run of the workflow fills this table._
<!-- SNAPSHOT:END -->

## How it works

```
GitHub Actions (daily 01:17 UTC)
  └─ python -m goldtrack.build
       ├─ fetch.py      CoinGecko + DefiLlama public APIs (retries, optional API key)
       ├─ transform.py  tidy tables: snapshot, history, spread, chain split
       ├─ charts.py     PNG charts  -> docs/img/
       └─ report.py     docs/index.html dashboard + README snapshot table
  └─ commit data/, docs/, README.md
GitHub Pages serves docs/
```

The pipeline is tested offline with synthetic responses that mimic the API formats (`tests/test_pipeline.py`), including a DefiLlama outage case so a single failing source does not stop the daily build.

## Set up your own copy

1. Push this repository to GitHub.
2. **Settings → Actions → General → Workflow permissions:** choose *Read and write permissions* so the job can commit updated data.
3. **Settings → Pages:** deploy from branch `main`, folder `/docs`.
4. **Actions → update-data → Run workflow** to populate the data immediately. After that it runs daily.
5. Optional: add a free CoinGecko demo key as the repository secret `COINGECKO_API_KEY` to avoid rate limits.

Run locally:

```bash
pip install -e ".[dev]"
pytest
python -m goldtrack.build
```

## Data notes

- Market share is among the tokens tracked here only.
- CoinGecko daily data is the last observation of each UTC day.
- Chain distribution appears only for tokens that DefiLlama tracks as a protocol under the name given in `config.json`.
- For information only. Not investment advice.

## License

MIT
