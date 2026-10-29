"""Auto-generated commentary in English and Chinese.

Every sentence is filled from the computed numbers; nothing is written by hand.
"""
from __future__ import annotations

from .macro import STANCE_TEXT


def _p(x, dp=1):
    return "n/a" if x is None else f"{x:+.{dp}f}%"


def _n(x, dp=2):
    return "n/a" if x is None else f"{x:,.{dp}f}"


def _bp(x):
    return "n/a" if x is None else f"{x:+.0f} bp"


def _ord(x):
    if x is None:
        return "n/a"
    n = int(round(x))
    suf = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suf}"


def factor_reading(f: dict, levels: dict) -> tuple[str, str]:
    k, r, e = f["key"], f.get("reading"), f.get("extra")
    if r is None:
        return "no data", "暂无数据"
    if k == "real_yield":
        lv = levels.get("DFII10")
        return (f"{_n(lv)}%, {_bp(r)} in 30 days", f"{_n(lv)}%，30 天 {_bp(r)}")
    if k == "usd":
        return (f"{_p(r)} in 30 days", f"30 天 {_p(r)}")
    if k == "policy":
        lv = levels.get("DGS2")
        return (f"2Y at {_n(lv)}%, {_bp(r)} in 30 days", f"2年期 {_n(lv)}%，30 天 {_bp(r)}")
    if k == "inflation":
        lv = levels.get("T10YIE")
        return (f"{_n(lv)}%, {_bp(r)} in 30 days", f"{_n(lv)}%，30 天 {_bp(r)}")
    if k == "risk":
        vix = "n/a" if e is None else f"{e:.1f}"
        return (f"HY spread {_bp(r)} in 30 days, VIX {vix}", f"高收益利差 30 天 {_bp(r)}，VIX {vix}")
    if k == "trend":
        return (f"{_p(r)} vs 200-day, {_p(e)} vs 50-day", f"较 200 日线 {_p(r)}，较 50 日线 {_p(e)}")
    if k == "stretch":
        return (f"RSI {r:.0f}", f"RSI {r:.0f}")
    if k == "positioning":
        return (f"{_ord(r)} percentile of 3-year range", f"处于 3 年区间 {r:.0f}% 分位")
    if k == "onchain":
        return (f"{_p(r)} ounces outstanding in 30 days", f"流通盎司 30 天 {_p(r)}")
    return (f"{r:.2f}", f"{r:.2f}")


def _join(items: list[str], lang: str) -> str:
    if not items:
        return "none" if lang == "en" else "无"
    return ", ".join(items) if lang == "en" else "、".join(items)


GOLD_LABELS = {"futures": ("Gold (COMEX front month)", "黄金（COMEX 主力合约）"),
               "etf": ("Gold (GLD, rescaled to a per-ounce price)", "黄金（以 GLD 换算为每盎司价格）"),
               "token": ("Gold (via the XAU₮ token price)", "黄金（以 XAU₮ 代币价格代替）")}


def gold_summary(gold_perf: dict, gold_tech: dict, sc: dict, basis: str = "futures") -> tuple[str, str]:
    lab_en, lab_zh = GOLD_LABELS.get(basis, GOLD_LABELS["futures"])
    st_en, st_zh = STANCE_TEXT[sc["stance"]]
    pos = [f for f in sc["factors"] if f.get("signal") == 1]
    neg = [f for f in sc["factors"] if f.get("signal") == -1]
    neu = [f for f in sc["factors"] if f.get("signal") == 0]
    last = gold_perf.get("last")
    en = (f"{lab_en} last closed at ${_n(last)}/oz: {_p(gold_perf.get('d1'), 2)} on the day, "
          f"{_p(gold_perf.get('m1'))} over one month and {_p(gold_perf.get('ytd'))} year to date, "
          f"{_p(gold_tech.get('from_hi'))} from its 52-week high. "
          f"The rules-based scorecard sums to {sc['score']:+d} across {sc['n']} factors, which reads as "
          f"<b>{st_en.lower()}</b>. Supportive: {_join([f['en'].lower() for f in pos], 'en')}. "
          f"Headwinds: {_join([f['en'].lower() for f in neg], 'en')}. "
          f"Neutral: {_join([f['en'].lower() for f in neu], 'en')}.")
    zh = (f"{lab_zh}最新收盘 {_n(last)} 美元/盎司，日内 {_p(gold_perf.get('d1'), 2)}，"
          f"近一月 {_p(gold_perf.get('m1'))}，年初至今 {_p(gold_perf.get('ytd'))}，"
          f"较 52 周高点 {_p(gold_tech.get('from_hi'))}。"
          f"规则打分合计 {sc['score']:+d}（共 {sc['n']} 项因子），综合判断为<b>{st_zh}</b>。"
          f"利好：{_join([f['zh'] for f in pos], 'zh')}；利空：{_join([f['zh'] for f in neg], 'zh')}；"
          f"中性：{_join([f['zh'] for f in neu], 'zh')}。")
    return en, zh


def macro_summary(rows: dict, fomc: dict | None) -> tuple[str, str]:
    def v(i):
        r = rows.get(i)
        return None if r is None else r["last"]

    def c(i):
        r = rows.get(i)
        return None if r is None else r["change"]

    curve = v("T10Y2Y")
    en = [f"The 10-year Treasury yields {_n(v('DGS10'))}% ({_bp(None if c('DGS10') is None else c('DGS10') * 100)} in a month); "
          f"the real (TIPS) yield is {_n(v('DFII10'))}% and the breakeven {_n(v('T10YIE'))}%."]
    zh = [f"10年期美债收益率 {_n(v('DGS10'))}%（近一月 {_bp(None if c('DGS10') is None else c('DGS10') * 100)}），"
          f"实际利率 {_n(v('DFII10'))}%，盈亏平衡通胀 {_n(v('T10YIE'))}%。"]
    if curve is not None:
        en.append(f"The 10Y–2Y curve is {'positive' if curve >= 0 else 'inverted'} at {curve * 100:+.0f} bp.")
        zh.append(f"10年-2年利差为 {curve * 100:+.0f} bp（{'正斜率' if curve >= 0 else '倒挂'}）。")
    en.append(f"Fed funds target upper bound {_n(v('DFEDTARU'))}%; CPI {_n(v('CPIAUCSL'), 1)}% y/y, "
              f"core PCE {_n(v('PCEPILFE'), 1)}% y/y, unemployment {_n(v('UNRATE'), 1)}%.")
    zh.append(f"联邦基金目标利率上限 {_n(v('DFEDTARU'))}%；CPI 同比 {_n(v('CPIAUCSL'), 1)}%，"
              f"核心 PCE 同比 {_n(v('PCEPILFE'), 1)}%，失业率 {_n(v('UNRATE'), 1)}%。")
    if fomc:
        sep_en = " (with projections)" if fomc["sep"] else ""
        sep_zh = "（含经济预测）" if fomc["sep"] else ""
        en.append(f"Next FOMC decision: {fomc['date']}{sep_en}, in {fomc['days']} days.")
        zh.append(f"下次 FOMC 议息决议：{fomc['date']}{sep_zh}，还有 {fomc['days']} 天。")
    return " ".join(en), "".join(zh)


def fx_summary(dxy_perf: dict, dxy_tech: dict, fx: list[dict], gic: list[dict]) -> tuple[str, str]:
    trend = {"up": ("uptrend", "上升趋势"), "down": ("downtrend", "下降趋势"), "mixed": ("no clear trend", "无明确趋势")}
    t_en, t_zh = trend.get(dxy_tech.get("trend") or "mixed")
    en = [f"The dollar index (DXY) is at {_n(dxy_perf.get('last'))}, {_p(dxy_perf.get('m1'))} over one month and "
          f"{_p(dxy_perf.get('ytd'))} year to date ({t_en})."]
    zh = [f"美元指数（DXY）报 {_n(dxy_perf.get('last'))}，近一月 {_p(dxy_perf.get('m1'))}，年初至今 {_p(dxy_perf.get('ytd'))}（{t_zh}）。"]
    ranked = [r for r in fx if r.get("ccy_m1") is not None]
    if ranked:
        ranked.sort(key=lambda r: r["ccy_m1"], reverse=True)
        b, w = ranked[0], ranked[-1]
        ccy = lambda r: r["en"].replace("USD/", "").replace("/USD", "")
        en.append(f"Against the dollar over one month, {ccy(b)} is strongest ({_p(b['ccy_m1'])}) and {ccy(w)} weakest ({_p(w['ccy_m1'])}).")
        zh.append(f"近一月对美元表现最强的是{ccy(b)}（{_p(b['ccy_m1'])}），最弱的是{ccy(w)}（{_p(w['ccy_m1'])}）。")
    cny = next((g for g in gic if g["ccy"] == "CNY"), None)
    if cny and cny.get("last"):
        en.append(f"In renminbi, gold is {_n(cny['last'])} CNY/g ({_p(cny.get('ytd'))} year to date).")
        zh.append(f"以人民币计价，金价为 {_n(cny['last'])} 元/克（年初至今 {_p(cny.get('ytd'))}）。")
    return " ".join(en), "".join(zh)


def commodity_summary(rows: list[dict], ratios_now: dict) -> tuple[str, str]:
    r = [x for x in rows if x.get("m1") is not None and x["group"] != "index"]
    en, zh = [], []
    if r:
        r.sort(key=lambda x: x["m1"], reverse=True)
        en.append(f"Over one month the strongest commodity is {r[0]['en'].lower()} ({_p(r[0]['m1'])}) and the weakest "
                  f"{r[-1]['en'].lower()} ({_p(r[-1]['m1'])}).")
        zh.append(f"近一月表现最强的是{r[0]['zh']}（{_p(r[0]['m1'])}），最弱的是{r[-1]['zh']}（{_p(r[-1]['m1'])}）。")
        up = [x for x in rows if x.get("trend") == "up" and x["group"] != "index"]
        dn = [x for x in rows if x.get("trend") == "down" and x["group"] != "index"]
        en.append(f"In uptrends: {_join([x['en'].lower() for x in up], 'en')}. In downtrends: {_join([x['en'].lower() for x in dn], 'en')}.")
        zh.append(f"处于上升趋势：{_join([x['zh'] for x in up], 'zh')}；处于下降趋势：{_join([x['zh'] for x in dn], 'zh')}。")
    gs = ratios_now.get("gold_silver")
    if gs:
        en.append(f"The gold/silver ratio is {gs['last']:.1f}, at the {_ord(gs['pctile'])} percentile of its 5-year range.")
        zh.append(f"金银比为 {gs['last']:.1f}，处于 5 年区间的 {gs['pctile']:.0f}% 分位。")
    cg = ratios_now.get("copper_gold")
    if cg and cg.get("m3") is not None:
        en.append(f"The copper/gold ratio, a common gauge of growth expectations, moved {_p(cg['m3'])} over three months.")
        zh.append(f"铜金比（常用的增长预期指标）近三个月 {_p(cg['m3'])}。")
    return " ".join(en), "".join(zh)


def cot_summary(rows: list[dict]) -> tuple[str, str]:
    g = next((r for r in rows if r["key"] == "gold"), None)
    if not g:
        return "Positioning data unavailable.", "暂无持仓数据。"
    wk = g.get("wk_change")
    en = (f"In the CFTC report of {g['date']}, managed money held a net {'long' if g['net'] >= 0 else 'short'} of "
          f"{abs(g['net']):,.0f} gold contracts ({g['net_pct_oi']:.1f}% of open interest), "
          f"{'n/a' if wk is None else f'{wk:+,.0f}'} on the week, at the {_ord(g['pctile_3y'])} percentile of its 3-year range.")
    zh = (f"根据 CFTC {g['date']} 的报告，管理基金在黄金期货上持有净{'多' if g['net'] >= 0 else '空'} {abs(g['net']):,.0f} 手"
          f"（占总持仓 {g['net_pct_oi']:.1f}%），周变动 {'n/a' if wk is None else f'{wk:+,.0f}'} 手，处于 3 年区间 {g['pctile_3y']:.0f}% 分位。")
    return en, zh
