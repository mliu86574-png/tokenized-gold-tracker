"""Render the bilingual gold & macro dashboard (docs/index.html).

Static HTML with an embedded JSON payload; charts are drawn client-side with
Apache ECharts so readers can zoom and hover.
"""
from __future__ import annotations

import html
import json
import math
import re

import pandas as pd

from .macro import STANCE_TEXT

ECHARTS = "https://cdn.jsdelivr.net/npm/echarts@5.5.1/dist/echarts.min.js"


# ---------------------------------------------------------------- small helpers
def L(en: str, zh: str, raw: bool = False) -> str:
    """Bilingual inline text; CSS shows one language at a time."""
    e, z = (en, zh) if raw else (html.escape(en), html.escape(zh))
    return f'<span lang="en">{e}</span><span lang="zh">{z}</span>'


def _ok(x) -> bool:
    return x is not None and not (isinstance(x, float) and math.isnan(x))


def num(x, dp=2, prefix="") -> str:
    return f"{prefix}{x:,.{dp}f}" if _ok(x) else "–"


def pct(x, dp=1, colour=True) -> str:
    if not _ok(x):
        return '<span class="na">–</span>'
    cls = "pos" if x > 0 else "neg" if x < 0 else ""
    return f'<span class="{cls if colour else ""}">{x:+.{dp}f}%</span>'


def chg(x, dp=2, unit="") -> str:
    if not _ok(x):
        return '<span class="na">–</span>'
    cls = "pos" if x > 0 else "neg" if x < 0 else ""
    return f'<span class="{cls}">{x:+,.{dp}f}{unit}</span>'


TREND = {"up": ("Uptrend", "上升", "up"), "down": ("Downtrend", "下降", "down"), "mixed": ("Range", "震荡", "flat")}


def trend_pill(t) -> str:
    en, zh, cls = TREND.get(t or "mixed", TREND["mixed"])
    return f'<span class="pill {cls}">{L(en, zh)}</span>'


def signal_pill(s) -> str:
    if s is None:
        return f'<span class="pill flat">{L("n/a", "无数据")}</span>'
    if s > 0:
        return f'<span class="pill up">▲ {L("Supportive", "利好")}</span>'
    if s < 0:
        return f'<span class="pill down">▼ {L("Headwind", "利空")}</span>'
    return f'<span class="pill flat">● {L("Neutral", "中性")}</span>'


def series_points(s: pd.Series | None, days: int | None = None, dp: int = 4) -> list:
    if s is None or len(s) == 0:
        return []
    s = s.dropna()
    if s.empty:
        return []
    if days:
        s = s[s.index >= s.index[-1] - pd.Timedelta(days=days)]
    return [[d.strftime("%Y-%m-%d"), round(float(v), dp)] for d, v in s.items()]


def _table(head: list[tuple[str, str]], rows: list[list[str]], cls: str = "") -> str:
    th = "".join(f"<th>{L(e, z)}</th>" for e, z in head)
    body = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows)
    return f'<div class="tbl {cls}"><table><thead><tr>{th}</tr></thead><tbody>{body}</tbody></table></div>'


def _card(label_en, label_zh, value, sub="") -> str:
    return (f'<div class="card"><div class="lbl">{L(label_en, label_zh)}</div>'
            f'<div class="val">{value}</div><div class="subv">{sub}</div></div>')


def _chart(cid: str, title_en: str, title_zh: str, note_en: str = "", note_zh: str = "", tall=False) -> str:
    note = f'<div class="note">{L(note_en, note_zh)}</div>' if note_en else ""
    return (f'<figure class="chartbox"><figcaption>{L(title_en, title_zh)}</figcaption>'
            f'<div class="chart{" tall" if tall else ""}" id="{cid}"></div>{note}</figure>')


def _summary(en: str, zh: str) -> str:
    return f'<p class="summary"><span lang="en">{en}</span><span lang="zh">{zh}</span></p>'


def render_notes(md: str | None) -> str:
    """Very small Markdown subset for the optional author's notes file."""
    if not md:
        return ""
    md = re.sub(r"<!--.*?-->", "", md, flags=re.S).strip()
    if not md:
        return ""
    out, in_list = [], False
    for line in md.splitlines():
        line = line.rstrip()
        if line.startswith(("- ", "* ")):
            if not in_list:
                out.append("<ul>")
                in_list = True
            out.append(f"<li>{html.escape(line[2:])}</li>")
            continue
        if in_list:
            out.append("</ul>")
            in_list = False
        if line.startswith("#"):
            out.append(f"<h4>{html.escape(line.lstrip('#').strip())}</h4>")
        elif line:
            out.append(f"<p>{html.escape(line)}</p>")
    if in_list:
        out.append("</ul>")
    body = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", "".join(out))
    return (f'<div class="notes"><div class="lbl">{L("Author’s notes", "作者观点")}</div>{body}'
            f'<div class="note">{L("Written by the author; separate from the rules-based score above.", "作者手写观点，与上方规则打分相互独立。")}</div></div>')


# ---------------------------------------------------------------- page
def render(ctx: dict) -> str:
    sc = ctx["scorecard"]
    st_en, st_zh = STANCE_TEXT[sc["stance"]]
    gp, gt = ctx["gold_perf"], ctx["gold_tech"]
    fomc = ctx.get("fomc")

    # ---------- overview
    pos = (sc["score"] + 9) / 18 * 100
    gauge = (f'<div class="gauge"><div class="track"></div><div class="mark" style="left:{pos:.1f}%"></div>'
             f'<div class="ticks"><span>−9</span><span>{L("Cautious", "偏谨慎")}</span><span>0</span>'
             f'<span>{L("Constructive", "偏多")}</span><span>+9</span></div></div>')
    hero = (f'<div class="hero"><div class="stance {sc["stance"]}"><div class="lbl">{L("Gold scorecard", "黄金综合判断")}</div>'
            f'<div class="big">{L(st_en, st_zh)}</div>'
            f'<div class="score">{L("Score", "得分")} <b>{sc["score"]:+d}</b> / {sc["n"]} {L("factors", "项因子")}</div>{gauge}</div>'
            f'<div class="price"><div class="lbl">{L("Gold, COMEX front month", "黄金 COMEX 主力")}</div>'
            f'<div class="big">${num(gp.get("last"))}</div><div class="subv">{pct(gp.get("d1"), 2)} {L("1D", "日")} · '
            f'{pct(gp.get("m1"))} {L("1M", "月")} · {pct(gp.get("ytd"))} {L("YTD", "年内")}</div>'
            + (f'<div class="fomc">{L("Next FOMC decision", "下次 FOMC 议息")}: <b>{fomc["date"]}</b> · '
               f'{L("in " + str(fomc["days"]) + " days", str(fomc["days"]) + " 天后")}'
               f'{L(" · with projections", " · 含经济预测") if fomc["sep"] else ""}</div>' if fomc else "")
            + '</div></div>')
    factor_rows = [[f'<b>{L(f["en"], f["zh"])}</b>', signal_pill(f.get("signal")), L(*f["text"]),
                    f'<span class="rule">{L(f["rule_en"], f["rule_zh"])}</span>'] for f in sc["factors"]]
    overview = (hero + _summary(*ctx["text"]["gold"]) + render_notes(ctx.get("notes"))
                + _table([("Factor", "因子"), ("Signal", "信号"), ("Latest reading", "最新读数"), ("Rule", "规则")],
                         factor_rows, "factors")
                + _chart("c_score", "Scorecard history vs gold price", "历史打分与金价",
                         "Bars: daily composite score (left axis). Line: gold (right axis).",
                         "柱：每日综合得分（左轴）；线：金价（右轴）。"))

    # ---------- gold
    cards = "".join([
        _card("52-week range", "52 周区间", f'{num(gt.get("lo52"), 0)} – {num(gt.get("hi52"), 0)}',
              f'{L("From high", "距高点")} {pct(gt.get("from_hi"))}'),
        _card("50 / 200-day average", "50 / 200 日均线", f'{num(gt.get("ma50"), 0)} / {num(gt.get("ma200"), 0)}',
              f'{L("vs 200-day", "较 200 日线")} {pct(gt.get("vs_ma200"))}'),
        _card("14-day RSI", "14 日 RSI", num(gt.get("rsi14"), 0), trend_pill(gt.get("trend"))),
        _card("30-day realised vol", "30 日实现波动率", f'{num(gt.get("vol30"), 1)}%', L("annualised", "年化")),
    ])
    gic_rows = [[f'{g["ccy"]}', L(g["unit_en"], g["unit_zh"]), num(g["last"]), pct(g["m1"]), pct(g["ytd"]),
                 pct(g["y1"]), pct(g["from_hi"])] for g in ctx["gold_ccy"]]
    gold = (f'<div class="grid4">{cards}</div>'
            + _chart("c_gold", "Gold price with 50- and 200-day averages", "金价与 50 / 200 日均线",
                     "Drag the slider to change the window.", "拖动下方滑块可调整时间区间。", tall=True)
            + '<h3>' + L("Gold in other currencies", "以不同货币计价的黄金") + '</h3>'
            + _table([("Currency", "货币"), ("Unit", "单位"), ("Last", "最新"), ("1M", "1个月"), ("YTD", "年初至今"),
                      ("1Y", "1年"), ("From 52w high", "距52周高点")], gic_rows, "left2"))

    # ---------- macro
    mrows = []
    for r in ctx["macro_rows"]:
        unit = r["unit"]
        dp = 0 if unit == "k" else 2
        val = num(r["last"], dp) + ("" if unit in ("index",) else ("k" if unit == "k" else f" {unit}" if unit != "%" else "%"))
        if unit == "%" and r["id"] not in ("CPIAUCSL", "CPILFESL", "PCEPILFE", "UNRATE"):
            change = chg(None if r["change"] is None else r["change"] * 100, 0, " bp")
        elif unit == "%":
            change = chg(r["change"], 1, " pp")
        else:
            change = chg(r["change"], dp)
        mrows.append([L(r["en"], r["zh"]), f"<b>{val}</b>", r["date"],
                      change + f' <span class="muted">{L("vs prior" if r["monthly"] else "1M", "较上期" if r["monthly"] else "1个月")}</span>',
                      num(r["y1"], dp)])
    macro = (_summary(*ctx["text"]["macro"])
             + _table([("Indicator", "指标"), ("Latest", "最新"), ("As of", "日期"), ("Change", "变动"), ("1Y ago", "1年前")],
                      mrows)
             + '<div class="grid2">'
             + _chart("c_realyield", "Gold vs 10Y real yield (inverted)", "金价 vs 10年期实际利率（倒置）",
                      "Real-yield axis is inverted: a rising line means falling real yields.",
                      "实际利率轴为倒置：线向上代表实际利率下降。")
             + _chart("c_rates", "US Treasury yields and breakeven inflation", "美债收益率与盈亏平衡通胀")
             + _chart("c_infl", "Inflation and the policy rate", "通胀与政策利率")
             + _chart("c_risk", "Risk gauges: VIX and high-yield spread", "风险指标：VIX 与高收益债利差")
             + '</div>')

    # ---------- USD & FX
    fx_rows = [[L(r["en"], r["zh"]), num(r["last"], 4), pct(r["ccy_d1"], 2), pct(r["ccy_w1"]), pct(r["ccy_m1"]),
                pct(r["ccy_ytd"]), pct(r["ccy_y1"]), trend_pill(r["trend"])] for r in ctx["fx_rows"]]
    dp_, dt_ = ctx["dxy_perf"], ctx["dxy_tech"]
    fx = (_summary(*ctx["text"]["fx"])
          + '<div class="grid4">'
          + _card("DXY", "美元指数", num(dp_.get("last")), f'{pct(dp_.get("m1"))} {L("1M", "1个月")}')
          + _card("DXY vs 200-day", "DXY 较 200 日线", pct(dt_.get("vs_ma200")), trend_pill(dt_.get("trend")))
          + _card("DXY YTD", "DXY 年初至今", pct(dp_.get("ytd")), f'{pct(dp_.get("y1"))} {L("1Y", "1年")}')
          + _card("DXY 52-week range", "DXY 52 周区间", f'{num(dt_.get("lo52"))} – {num(dt_.get("hi52"))}', "")
          + '</div>'
          + _table([("Pair", "货币对"), ("Last", "最新"), ("1D", "1日"), ("1W", "1周"), ("1M", "1个月"), ("YTD", "年初至今"),
                    ("1Y", "1年"), ("Trend", "趋势")], fx_rows)
          + f'<div class="note">{L("Changes show each currency against the US dollar: positive means the currency strengthened.", "涨跌幅均为该货币对美元的变动：正数代表该货币升值。")}</div>'
          + '<div class="grid2">'
          + _chart("c_dxy", "Gold vs US dollar index", "金价 vs 美元指数")
          + _chart("c_fx", "Currencies vs USD", "各货币对美元表现", "One-month and year-to-date change.", "近一月与年初至今变动。")
          + '</div>')

    # ---------- commodities
    crow = [[L(r["en"], r["zh"]), f'<span class="muted">{html.escape(r["unit"])}</span>', num(r.get("last")),
             pct(r.get("w1")), pct(r.get("m1")), pct(r.get("ytd")), pct(r.get("y1")), pct(r.get("vs_ma200")),
             num(r.get("rsi14"), 0), f'{num(r.get("vol30"), 0)}%', trend_pill(r.get("trend"))] for r in ctx["cmdty_rows"]]
    cm = (_summary(*ctx["text"]["cmdty"])
          + _table([("Commodity", "品种"), ("Unit", "单位"), ("Last", "最新"), ("1W", "1周"), ("1M", "1个月"),
                    ("YTD", "年初至今"), ("1Y", "1年"), ("vs 200D", "较200日线"), ("RSI", "RSI"), ("30D vol", "30日波动"),
                    ("Trend", "趋势")], crow, "left2")
          + f'<div class="note">{L("Continuous front-month futures; contract rolls can cause small jumps. Trend: price above both 50- and 200-day averages with the 50 above the 200 = uptrend, the reverse = downtrend.", "期货主力连续合约，换月可能带来小幅跳空。趋势定义：价格高于 50 日和 200 日均线且 50 日线在上 = 上升；反之 = 下降。")}</div>'
          + '<div class="grid2">'
          + _chart("c_cmdty", "Commodity performance", "大宗商品表现", "One-month and year-to-date change.", "近一月与年初至今变动。")
          + _chart("c_gsr", "Gold/silver ratio", "金银比", "Ounces of silver per ounce of gold.", "一盎司黄金可兑换的白银盎司数。")
          + _chart("c_cugold", "Copper/gold ratio vs 10Y yield", "铜金比 vs 10年期美债收益率",
                   "Copper per lb ÷ gold per oz × 1,000. Often moves with growth expectations.",
                   "铜价（磅）÷ 金价（盎司）× 1000，常随增长预期变化。")
          + _chart("c_goldoil", "Gold/Brent ratio", "金油比", "Barrels of Brent per ounce of gold.", "一盎司黄金可兑换的布伦特原油桶数。")
          + '</div>')

    # ---------- positioning
    cot_rows = [[L(r["en"], r["zh"]), r["date"], num(r["net"], 0), f'{num(r["net_pct_oi"], 1)}%', chg(r["wk_change"], 0),
                 f'{num(r["pctile_3y"], 0)}%', num(r["oi"], 0)] for r in ctx["cot_rows"]]
    posn = (_summary(*ctx["text"]["cot"])
            + _table([("Market", "品种"), ("Report date", "报告日"), ("MM net (contracts)", "管理基金净持仓（手）"),
                      ("% of OI", "占总持仓"), ("Weekly change", "周变动"), ("3Y percentile", "3年分位"),
                      ("Open interest", "总持仓")], cot_rows)
            + _chart("c_cot", "Gold: managed-money net position vs price", "黄金：管理基金净持仓 vs 金价",
                     "CFTC disaggregated Commitments of Traders, futures only, weekly (Tuesday positions).",
                     "CFTC 分类持仓报告（仅期货），每周二持仓，周五发布。"))

    # ---------- tokenized gold
    tk = ctx["token"]
    trows = [[f'<b>{html.escape(r["symbol"])}</b>', html.escape(r["name"]), num(r["market_cap_usd"] / 1e6, 1, "$") + "m",
              f'{num(r["market_share_pct"], 1)}%', num(r["price_usd"]), num(r["volume_24h_usd"] / 1e6, 2, "$") + "m",
              pct(r.get("change_30d_pct"))] for r in tk["snapshot"]]
    a, b = tk["pair"]
    k = tk["kpis"]
    tok = ('<div class="grid4">'
           + _card("Tracked market cap", "追踪总市值", num((k.get("total_mcap") or 0) / 1e9, 2, "$") + "bn", "")
           + _card("Largest token", "最大代币", f'{k.get("leader") or "–"}', f'{num(k.get("leader_share"), 1)}%')
           + _card("Ounces outstanding (XAU₮+PAXG)", "流通盎司（XAU₮+PAXG）",
                   num(tk.get("oz_last"), 0), f'{pct(tk.get("oz_m1"))} {L("30D", "30天")}')
           + _card(f"{a} vs {b} spread", f"{a} 与 {b} 价差",
                   "–" if k.get("spread_bps") is None else f'{k["spread_bps"]:+.0f} bp', "")
           + '</div>'
           + _table([("Token", "代币"), ("Name", "名称"), ("Market cap", "市值"), ("Share", "份额"), ("Price", "价格"),
                     ("24h volume", "24小时成交"), ("30D", "30天")], trows, "left2")
           + '<div class="grid2">'
           + _chart("c_tokmcap", "Market capitalisation by token", "各代币市值")
           + _chart("c_tokoz", "Implied ounces outstanding", "隐含流通盎司数",
                    "Market cap ÷ price for XAU₮ and PAXG; strips out the gold price effect.",
                    "XAU₮ 与 PAXG 的市值 ÷ 价格，剔除金价影响，反映真实申购赎回。")
           + _chart("c_spread", f"{a} vs {b} price spread", f"{a} 与 {b} 价差", "Basis points, daily.", "基点，日频。")
           + _chart("c_chain", "XAU₮ distribution by chain", "XAU₮ 各链分布", "DefiLlama, where tracked.", "数据来自 DefiLlama。")
           + '</div>')

    # ---------- methodology
    frows = [[L(f["en"], f["zh"]), L(f["rule_en"], f["rule_zh"])] for f in sc["factors"]]
    status_rows = [[html.escape(s["source"]), html.escape(s["item"]),
                    ('<span class="pill up">OK</span>' if s["ok"] else '<span class="pill down">' + L("Failed", "失败") + '</span>'),
                    html.escape(s.get("last") or "–")] for s in ctx["status"]]
    method = (f'<p>{L("The scorecard adds +1 for each factor in a supportive state, −1 for each headwind and 0 otherwise. A total of +3 or more reads as constructive, −3 or less as cautious, anything between as neutral. Factors with no data are left out. The rules are deliberately simple and published here so that every reading can be checked.", "打分规则：每项因子处于利好状态记 +1，利空记 −1，其余记 0。合计 ≥ +3 为偏多，≤ −3 为偏谨慎，介于之间为中性；缺数据的因子不计入。规则刻意保持简单并全部公开，便于核对每一个读数。")}</p>'
              + _table([("Factor", "因子"), ("Rule", "规则")], frows, "left2 wrap2")
              + f'<p>{L("Sources: Yahoo Finance (futures, FX, indices), FRED / Federal Reserve Bank of St. Louis (rates, inflation, labour, dollar index, credit spreads), CFTC Commitments of Traders, CoinGecko and DefiLlama (tokenized gold), Federal Reserve (FOMC calendar). When a feed is unavailable the build falls back to US Treasury, New York Fed, Cboe, BLS, ECB, Nasdaq and LBMA data; the source actually used for each series is listed in the data-status table. All public; refreshed daily by GitHub Actions.", "数据来源：Yahoo Finance（期货、外汇、指数）、FRED 圣路易斯联储（利率、通胀、就业、美元指数、信用利差）、CFTC 持仓报告、CoinGecko 与 DefiLlama（代币化黄金）、美联储（FOMC 日程）。某个数据源不可用时，自动改用美国财政部、纽约联储、Cboe、美国劳工统计局、欧洲央行、Nasdaq 和 LBMA 的数据；每个序列实际使用的来源见“数据状态”表。均为公开数据，每天由 GitHub Actions 自动更新。")}</p>'
              + '<details><summary>' + L("Data status for this build", "本次更新的数据状态") + '</summary>'
              + _table([("Source", "来源"), ("Series", "序列"), ("Status", "状态"), ("Latest", "最新日期")], status_rows, "left2")
              + '</details>')

    nav = [("overview", "Overview", "总览"), ("gold", "Gold", "黄金"), ("macro", "Macro & rates", "宏观利率"),
           ("fx", "USD & FX", "美元外汇"), ("cmdty", "Commodities", "大宗商品"), ("cot", "Positioning", "持仓"),
           ("token", "Tokenized gold", "代币化黄金"), ("method", "Method", "方法")]
    nav_html = "".join(f'<a href="#{i}">{L(e, z)}</a>' for i, e, z in nav)

    def section(i, e, z, body):
        return f'<section id="{i}"><h2>{L(e, z)}</h2>{body}</section>'

    body = (section("overview", "Gold view", "黄金综合判断", overview)
            + section("gold", "Gold market", "黄金行情", gold)
            + section("macro", "Macro & rates", "宏观与利率", macro)
            + section("fx", "US dollar & FX", "美元与外汇", fx)
            + section("cmdty", "Commodities", "大宗商品", cm)
            + section("cot", "Futures positioning", "期货持仓", posn)
            + section("token", "Tokenized gold", "代币化黄金", tok)
            + section("method", "Methodology & sources", "方法与数据来源", method))

    payload = json.dumps(ctx["payload"], separators=(",", ":"), ensure_ascii=False)
    updated = html.escape(ctx["updated"])
    return (PAGE.replace("%%NAV%%", nav_html).replace("%%BODY%%", body).replace("%%UPDATED%%", updated)
            .replace("%%DATA%%", payload.replace("</", "<\\/")).replace("%%ECHARTS%%", ECHARTS))


PAGE = r"""<!doctype html>
<html lang="en" data-lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Gold & Macro Monitor</title>
<meta name="description" content="Daily rules-based gold scorecard with macro, US dollar, commodities, positioning and tokenized gold data.">
<style>
:root{--bg:#f7f5f0;--fg:#1c2230;--muted:#6b7280;--card:#ffffff;--line:#e5e0d5;--accent:#a8780a;--navy:#1b355e;
--pos:#1f7a3a;--neg:#b42318;--flat:#6b7280;--posbg:#e6f4ea;--negbg:#fdecea;--flatbg:#eef0f3;--hero:#fffaf0}
@media (prefers-color-scheme:dark){:root{--bg:#111418;--fg:#e7e5e0;--muted:#9aa1ad;--card:#1a1e24;--line:#2b3038;--accent:#d9a83a;--navy:#8fb1e3;
--pos:#5cc97b;--neg:#f28b82;--flat:#9aa1ad;--posbg:#143321;--negbg:#3a1a18;--flatbg:#23272e;--hero:#1d1c17}}
*{box-sizing:border-box}html{scroll-behavior:smooth}
body{margin:0;background:var(--bg);color:var(--fg);font:14.5px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,"PingFang SC","Hiragino Sans GB","Microsoft YaHei",sans-serif}
html[data-lang=en] [lang=zh],html[data-lang=zh] [lang=en]{display:none}
header{position:sticky;top:0;z-index:10;background:color-mix(in srgb,var(--bg) 92%,transparent);backdrop-filter:blur(8px);border-bottom:1px solid var(--line)}
.bar{max-width:1180px;margin:0 auto;padding:10px 16px;display:flex;align-items:center;gap:16px;flex-wrap:wrap}
.brand{font-weight:700;font-size:17px;letter-spacing:.2px}.brand small{display:block;font-weight:400;color:var(--muted);font-size:12px}
nav{display:flex;gap:4px;flex-wrap:wrap;flex:1}nav a{color:var(--fg);text-decoration:none;padding:4px 10px;border-radius:999px;font-size:13px}
nav a:hover{background:var(--flatbg)}
.lang{border:1px solid var(--line);background:var(--card);color:var(--fg);border-radius:999px;padding:4px 12px;cursor:pointer;font-size:13px}
main{max-width:1180px;margin:0 auto;padding:8px 16px 64px}
section{padding-top:28px}h2{font-size:21px;margin:0 0 14px;padding-bottom:6px;border-bottom:2px solid var(--accent);display:inline-block}
h3{font-size:16px;margin:22px 0 10px}
.hero{display:grid;grid-template-columns:1.3fr 1fr;gap:14px;margin-bottom:14px}
.stance,.price{background:var(--hero);border:1px solid var(--line);border-radius:14px;padding:18px 20px}
.stance .big{font-size:34px;font-weight:700;line-height:1.2;margin:4px 0}
.stance.constructive .big{color:var(--pos)}.stance.cautious .big{color:var(--neg)}.stance.neutral .big{color:var(--accent)}
.price .big{font-size:30px;font-weight:700;margin:4px 0}.score{color:var(--muted)}.score b{color:var(--fg);font-size:18px}
.fomc{margin-top:10px;font-size:13px;color:var(--muted)}.fomc b{color:var(--fg)}
.gauge{position:relative;margin-top:14px;height:38px}.gauge .track{height:8px;border-radius:4px;background:linear-gradient(90deg,var(--neg),var(--flat) 50%,var(--pos))}
.gauge .mark{position:absolute;top:-4px;width:4px;height:16px;background:var(--fg);border-radius:2px;transform:translateX(-50%)}
.gauge .ticks{display:flex;justify-content:space-between;font-size:11px;color:var(--muted);margin-top:6px}
.lbl{color:var(--muted);font-size:12.5px;text-transform:none}
.summary{background:var(--card);border:1px solid var(--line);border-left:4px solid var(--accent);border-radius:10px;padding:12px 16px;margin:0 0 14px}
.notes{background:var(--card);border:1px dashed var(--accent);border-radius:10px;padding:12px 16px;margin:0 0 14px}.notes h4{margin:6px 0}
.grid4{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:14px}
.grid2{display:grid;grid-template-columns:repeat(2,1fr);gap:14px}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px 14px}
.card .val{font-size:20px;font-weight:650;margin-top:2px}.card .subv{font-size:12.5px;color:var(--muted);margin-top:2px}
.tbl{overflow-x:auto;margin-bottom:14px;border:1px solid var(--line);border-radius:12px;background:var(--card)}
table{border-collapse:collapse;width:100%}th,td{padding:8px 10px;border-bottom:1px solid var(--line);text-align:right;white-space:nowrap;font-variant-numeric:tabular-nums}
th{font-size:12px;color:var(--muted);font-weight:600;background:var(--flatbg)}
th:first-child,td:first-child{text-align:left}tr:last-child td{border-bottom:none}
.factors td:nth-child(3),.factors th:nth-child(3){text-align:left}.factors td:nth-child(4),.factors th:nth-child(4){text-align:left;white-space:normal;min-width:260px}
.factors td:nth-child(2),.factors th:nth-child(2){text-align:center}
.left2 td:nth-child(2),.left2 th:nth-child(2){text-align:left}.wrap2 td:nth-child(2){white-space:normal}.rule{color:var(--muted);font-size:12.5px}
.pos{color:var(--pos)}.neg{color:var(--neg)}.na,.muted{color:var(--muted)}
.pill{display:inline-block;padding:1px 9px;border-radius:999px;font-size:12px;font-weight:600}
.pill.up{background:var(--posbg);color:var(--pos)}.pill.down{background:var(--negbg);color:var(--neg)}.pill.flat{background:var(--flatbg);color:var(--flat)}
.chartbox{margin:0 0 14px;background:var(--card);border:1px solid var(--line);border-radius:12px;padding:10px 12px}
.chartbox figcaption{font-weight:600;font-size:14px}.chart{height:300px}.chart.tall{height:400px}
.note{color:var(--muted);font-size:12px;margin-top:4px}
details{margin-top:8px}summary{cursor:pointer;color:var(--muted)}
footer{max-width:1180px;margin:0 auto;padding:18px 16px 40px;color:var(--muted);font-size:12.5px;border-top:1px solid var(--line)}
@media (max-width:860px){.factors td:nth-child(4),.factors th:nth-child(4){display:none}.factors td:nth-child(3){white-space:normal}
.hero,.grid2{grid-template-columns:1fr}.grid4{grid-template-columns:repeat(2,1fr)}nav{display:none}.stance .big{font-size:28px}}
</style></head><body>
<header><div class="bar"><div class="brand"><span lang="en">Gold & Macro Monitor</span><span lang="zh">黄金宏观看板</span>
<small><span lang="en">Updated</span><span lang="zh">更新于</span> %%UPDATED%% UTC</small></div>
<nav>%%NAV%%</nav><button class="lang" id="langBtn" type="button">中文 / EN</button></div></header>
<main>%%BODY%%</main>
<footer><span lang="en">For information only. This page is generated automatically from public data and is not investment advice. Readings can be revised by their sources.</span>
<span lang="zh">仅供参考。本页由公开数据自动生成，不构成任何投资建议；数据可能被来源方修订。</span></footer>
<script>window.DATA=%%DATA%%;</script>
<script src="%%ECHARTS%%"></script>
<script>
(function(){
var D=window.DATA, root=document.documentElement, charts=[];
var lang='en';
try{var saved=localStorage.getItem('gm-lang'); if(saved){lang=saved;} else if((navigator.language||'').toLowerCase().indexOf('zh')===0){lang='zh';}}catch(e){if((navigator.language||'').toLowerCase().indexOf('zh')===0){lang='zh';}}
function setLang(l){lang=l;root.setAttribute('data-lang',l);root.setAttribute('lang',l==='zh'?'zh-CN':'en');try{localStorage.setItem('gm-lang',l);}catch(e){}draw();}
document.getElementById('langBtn').addEventListener('click',function(){setLang(lang==='en'?'zh':'en');});
var dark=window.matchMedia&&window.matchMedia('(prefers-color-scheme: dark)').matches;
var TXT=dark?'#c9ccd1':'#3b4252', GRID=dark?'#2b3038':'#ece7dc';
var C={gold:'#b8860b',navy:dark?'#8fb1e3':'#1b355e',teal:'#0f8a8a',plum:'#9b5c84',olive:'#6b8f3a',grey:'#8a8f98',red:'#c0392b',green:'#2e7d32'};
function t(o){return typeof o==='string'?o:(o[lang]||o.en);}
function base(){return{animation:false,textStyle:{color:TXT,fontFamily:'inherit'},grid:{left:56,right:56,top:36,bottom:40},
 tooltip:{trigger:'axis',valueFormatter:function(v){return v==null?'–':(Math.abs(v)>=1000?v.toLocaleString(undefined,{maximumFractionDigits:0}):(+v).toFixed(2));}},
 legend:{top:0,textStyle:{color:TXT}},xAxis:{type:'time',axisLine:{lineStyle:{color:GRID}},axisLabel:{color:TXT},splitLine:{show:false}}};}
function cmp(v){var a=Math.abs(v);return a>=1e9?(v/1e9)+'B':(a>=1e6?(v/1e6)+'M':v.toLocaleString());}
function yax(o){o=o||{};return Object.assign({type:'value',scale:true,axisLabel:{color:TXT,formatter:cmp},splitLine:{lineStyle:{color:GRID}},nameTextStyle:{color:TXT}},o);}
function ln(name,data,color,o){return Object.assign({name:t(name),type:'line',data:data||[],showSymbol:false,lineStyle:{width:1.6,color:color},itemStyle:{color:color}},o||{});}
function mk(id,opt){var el=document.getElementById(id);if(!el)return;var c=echarts.init(el,null,{renderer:'canvas'});c.setOption(opt);charts.push(c);}
function zoom(startPct){return [{type:'inside',start:startPct,end:100},{type:'slider',start:startPct,end:100,height:18,bottom:6,borderColor:GRID,textStyle:{color:TXT}}];}
function bars(id,rows){var cats=rows.map(function(r){return t(r.name);});var o=base();
 o.xAxis={type:'value',axisLabel:{color:TXT,formatter:'{value}%'},splitLine:{lineStyle:{color:GRID}}};
 o.yAxis={type:'category',data:cats,inverse:true,axisLabel:{color:TXT}};o.grid={left:110,right:24,top:30,bottom:24};
 o.tooltip={trigger:'axis',axisPointer:{type:'shadow'},valueFormatter:function(v){return v==null?'–':(+v).toFixed(1)+'%';}};
 o.series=[{name:t({en:'1 month',zh:'1个月'}),type:'bar',data:rows.map(function(r){return r.m1;}),itemStyle:{color:C.navy}},
  {name:t({en:'Year to date',zh:'年初至今'}),type:'bar',data:rows.map(function(r){return r.ytd;}),itemStyle:{color:C.gold}}];mk(id,o);}
function draw(){
 if(typeof echarts==='undefined')return;
 charts.forEach(function(c){c.dispose();});charts=[];var S=D.series,o;
 // scorecard history
 o=base();o.yAxis=[yax({min:-9,max:9,interval:3,name:t({en:'Score',zh:'得分'})}),yax({name:'USD/oz',splitLine:{show:false}})];
 o.series=[{name:t({en:'Score',zh:'得分'}),type:'bar',data:(S.score||[]).map(function(p){return {value:p,itemStyle:{color:p[1]>=3?C.green:(p[1]<=-3?C.red:C.grey)}};}),barCategoryGap:'0%'},
  ln({en:'Gold',zh:'黄金'},S.gold_2y,C.gold,{yAxisIndex:1,lineStyle:{width:2,color:C.gold}})];
 o.dataZoom=zoom(0);o.grid.bottom=56;mk('c_score',o);
 // gold with MAs
 o=base();o.yAxis=yax({name:'USD/oz'});o.series=[ln({en:'Gold',zh:'黄金'},S.gold,C.gold,{lineStyle:{width:2,color:C.gold}}),
  ln({en:'50-day',zh:'50日线'},S.ma50,C.navy),ln({en:'200-day',zh:'200日线'},S.ma200,C.plum)];o.dataZoom=zoom(75);o.grid.bottom=56;mk('c_gold',o);
 // gold vs real yield
 o=base();o.yAxis=[yax({name:'USD/oz'}),yax({name:t({en:'Real yield %',zh:'实际利率 %'}),inverse:true,splitLine:{show:false}})];
 o.series=[ln({en:'Gold',zh:'黄金'},S.gold,C.gold),ln({en:'10Y real yield (inverted)',zh:'10年期实际利率（倒置）'},S.DFII10,C.navy,{yAxisIndex:1})];
 o.dataZoom=zoom(60);o.grid.bottom=56;mk('c_realyield',o);
 // rates
 o=base();o.yAxis=yax({name:'%'});o.series=[ln({en:'10Y nominal',zh:'10年期名义'},S.DGS10,C.navy),ln({en:'2Y',zh:'2年期'},S.DGS2,C.teal),
  ln({en:'10Y real',zh:'10年期实际'},S.DFII10,C.gold),ln({en:'10Y breakeven',zh:'10年期通胀预期'},S.T10YIE,C.plum)];o.dataZoom=zoom(50);o.grid.bottom=56;mk('c_rates',o);
 // inflation & policy
 o=base();o.yAxis=yax({name:'%'});o.series=[ln({en:'CPI y/y',zh:'CPI 同比'},S.CPIAUCSL,C.red),ln({en:'Core CPI y/y',zh:'核心 CPI 同比'},S.CPILFESL,C.plum),
  ln({en:'Core PCE y/y',zh:'核心 PCE 同比'},S.PCEPILFE,C.teal),ln({en:'Fed funds (upper)',zh:'联邦基金利率上限'},S.DFEDTARU,C.navy,{step:'end'})];mk('c_infl',o);
 // risk
 o=base();o.yAxis=[yax({name:'VIX'}),yax({name:t({en:'HY spread %',zh:'高收益利差 %'}),splitLine:{show:false}})];
 o.series=[ln('VIX',S.VIXCLS,C.grey),ln({en:'HY spread',zh:'高收益利差'},S.BAMLH0A0HYM2,C.red,{yAxisIndex:1})];o.dataZoom=zoom(50);o.grid.bottom=56;mk('c_risk',o);
 // gold vs dxy
 o=base();o.yAxis=[yax({name:'USD/oz'}),yax({name:'DXY',inverse:true,splitLine:{show:false}})];
 o.series=[ln({en:'Gold',zh:'黄金'},S.gold,C.gold),ln({en:'DXY (inverted)',zh:'美元指数（倒置）'},S.dxy,C.navy,{yAxisIndex:1})];o.dataZoom=zoom(60);o.grid.bottom=56;mk('c_dxy',o);
 bars('c_fx',D.bars.fx||[]);bars('c_cmdty',D.bars.cmdty||[]);
 // ratios
 o=base();o.yAxis=yax();o.series=[ln({en:'Gold/silver',zh:'金银比'},S.gold_silver,C.grey,{markLine:{silent:true,symbol:'none',lineStyle:{type:'dashed',color:C.gold},data:[{type:'average',name:'avg'}],label:{color:TXT}}})];
 o.dataZoom=zoom(0);o.grid.bottom=56;mk('c_gsr',o);
 o=base();o.yAxis=[yax({name:t({en:'Cu/Au ×1000',zh:'铜金比×1000'})}),yax({name:'10Y %',splitLine:{show:false}})];
 o.series=[ln({en:'Copper/gold',zh:'铜金比'},S.copper_gold,C.olive),ln({en:'10Y yield',zh:'10年期收益率'},S.DGS10,C.navy,{yAxisIndex:1})];o.dataZoom=zoom(40);o.grid.bottom=56;mk('c_cugold',o);
 o=base();o.yAxis=yax();o.series=[ln({en:'Gold/Brent',zh:'金油比'},S.gold_oil,C.plum)];o.dataZoom=zoom(0);o.grid.bottom=56;mk('c_goldoil',o);
 // COT
 o=base();o.yAxis=[yax({name:t({en:'Contracts',zh:'手'}),scale:false}),yax({name:'USD/oz',splitLine:{show:false}})];
 o.series=[{name:t({en:'Managed money net',zh:'管理基金净持仓'}),type:'bar',data:S.cot_gold||[],itemStyle:{color:C.navy},barCategoryGap:'10%'},
  ln({en:'Gold',zh:'黄金'},S.gold,C.gold,{yAxisIndex:1})];o.dataZoom=zoom(40);o.grid.bottom=56;mk('c_cot',o);
 // tokens
 o=base();o.yAxis=yax({name:'USD m'});var pal=[C.navy,C.gold,C.teal,C.plum,C.olive];o.series=(D.tokens||[]).map(function(tk,i){return ln(tk.symbol,tk.mcap,pal[i%pal.length],{stack:'mc',areaStyle:{opacity:.25}});});mk('c_tokmcap',o);
 o=base();o.yAxis=yax({name:'oz'});o.series=[ln({en:'Ounces',zh:'盎司'},S.token_oz,C.gold,{areaStyle:{opacity:.15}})];mk('c_tokoz',o);
 o=base();o.yAxis=yax({name:'bp'});o.series=[ln({en:'Spread',zh:'价差'},S.spread,C.navy,{markLine:{silent:true,symbol:'none',data:[{yAxis:0}],lineStyle:{color:C.grey}}})];mk('c_spread',o);
 if(D.chains&&D.chains.length){o=base();o.xAxis={type:'value',axisLabel:{color:TXT,formatter:'{value}%'},splitLine:{lineStyle:{color:GRID}}};
  o.yAxis={type:'category',data:D.chains.map(function(c){return c.chain;}),inverse:true,axisLabel:{color:TXT}};o.grid={left:90,right:24,top:10,bottom:24};o.legend={show:false};
  o.tooltip={trigger:'axis',axisPointer:{type:'shadow'},valueFormatter:function(v){return (+v).toFixed(1)+'%';}};
  o.series=[{type:'bar',name:'%',data:D.chains.map(function(c){return c.share;}),itemStyle:{color:C.gold}}];mk('c_chain',o);}
}
window.addEventListener('resize',function(){charts.forEach(function(c){c.resize();});});
setLang(lang);
})();
</script>
</body></html>"""
