"""
build_site.py - builds the site in the site/ folder: the home page (index.html), a page for Trade Like
Berlin (berlin.html), one for each signal channel (akash.html) and the order ticket (ticket.html).

GitHub Actions runs this every weekday evening and publishes site/ with GitHub Pages.
You can also run it yourself (python build_site.py) and open site/index.html in a browser.

FOR LEARNING ONLY. No real orders are placed. Not investment advice.
"""

import datetime as dt
import html
import json
import os
import re

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import matplotlib.dates  # noqa: E402
import matplotlib.ticker  # noqa: E402
import pandas as pd  # noqa: E402

import asset_arena  # noqa: E402
import berlin  # noqa: E402
import berlin_calls  # noqa: E402
try:
    import berlin_etf  # noqa: E402
except ImportError:          # berlin_etf.py or zerodha.py not uploaded yet
    berlin_etf = None
import berlin_study  # noqa: E402
import channels  # noqa: E402
try:
    import events  # noqa: E402
except ImportError:          # events.py not uploaded yet
    events = None
import fno_arena  # noqa: E402
import logbook  # noqa: E402
import market_context as mc  # noqa: E402
import nifty_backtest as bt  # noqa: E402
import paper_arena as pa  # noqa: E402
try:
    import real_money  # noqa: E402
except ImportError:          # real_money.py or zerodha.py not uploaded yet
    real_money = None
try:
    import risk_engine  # noqa: E402
except ImportError:          # risk_engine.py not uploaded yet
    risk_engine = None
import scorecard  # noqa: E402
import signal_calls  # noqa: E402

SITE = "site"
DATA_URL = "https://github.com/aswinv90/indian-market-historical-data"
IST = dt.timezone(dt.timedelta(hours=5, minutes=30))

COLORS = {  # same colour for an agent on every chart; light and dark versions
    "light": {"Cash only": "#8A948F", "Buy & hold": "#2F6FB0", "200-day trend": "#D2572E",
              "Golden cross": "#2E9461", "RSI(2) dip-buy": "#8A5BC2", "Momentum rotation": "#C98A00"},
    "dark": {"Cash only": "#9AA59F", "Buy & hold": "#6EA8E6", "200-day trend": "#F07F55",
             "Golden cross": "#55C48A", "RSI(2) dip-buy": "#B68CF0", "Momentum rotation": "#E5B23A"},
}
EXTRA = {"light": ["#1F9E9E", "#C2417F", "#5B6FD0", "#6F8F00", "#D9622B", "#2F6FB0", "#8A5BC2", "#B8860B",
                   "#7A4A2B", "#4A5568"],
         "dark": ["#4CC9C9", "#E879AE", "#93A3F0", "#A7C93B", "#F08A5D", "#6EA8E6", "#B68CF0", "#E5B23A",
                  "#D9A679", "#C3CBD6"]}
THEMES = {"light": {"fg": "#1E2B25", "muted": "#5C6B63", "bg": "#FFFFFF", "grid": "#DCE3DF"},
          "dark": {"fg": "#DDE6E1", "muted": "#93A49B", "bg": "#17211C", "grid": "#2E3C35"}}


# ------------------------------- formatting -------------------------------------
def esc(text):
    return html.escape(str(text))


def minus(text):
    return text.replace("-", "\u2212")


def inr(x):
    if x >= 1e7:
        return f"\u20b9{x / 1e7:,.2f} crore"
    if x >= 1e5:
        return f"\u20b9{x / 1e5:,.2f} lakh"
    return f"\u20b9{x:,.0f}"


def pct(v, signed=False, digits=1):
    return minus(f"{v:+.{digits}%}" if signed else f"{v:.{digits}%}")


def tone(v):
    return "up" if v > 1e-9 else "down" if v < -1e-9 else ""


def day(d):
    return f"{d.day} {d:%b %Y}"


# --------------------------------- charts ---------------------------------------
TWINS = getattr(fno_arena, "TWINS", {})      # whole-lot agents share their fractional twin's colour, dashed


def twin_in(name, order):
    return name in TWINS and TWINS[name] in order


def color_for(name, theme, order):
    known = COLORS[theme]
    if twin_in(name, order):
        name = TWINS[name]
    if name in known:
        return known[name]
    extras = [n for n in order if n not in known and not twin_in(n, order)]
    return EXTRA[theme][extras.index(name) % len(EXTRA[theme])]


def draw(series, filename, log=False, split=None, money_axis="plain"):
    names = list(series)
    for theme, c in THEMES.items():
        fig, ax = plt.subplots(figsize=(9, 4.6))
        fig.patch.set_facecolor(c["bg"])
        ax.set_facecolor(c["bg"])
        for name, s in series.items():
            dashed = name == "Cash only" or twin_in(name, names)
            ax.plot(s.index, s.values, label=name, color=color_for(name, theme, names),
                    lw=1.1 if name == "Cash only" else 1.7, ls="--" if dashed else "-")
        if log:
            ax.set_yscale("log")
            lo = min(s.min() for s in series.values()) * 0.92
            hi = max(s.max() for s in series.values()) * 1.08
            ax.set_ylim(lo, hi)
            ax.yaxis.set_minor_formatter(matplotlib.ticker.NullFormatter())
            ax.set_yticks([v * 1e5 for v in (0.5, 0.75, 1, 1.5, 2, 3, 4, 5, 6, 8, 10) if lo <= v * 1e5 <= hi])
        if money_axis == "lakh":
            ax.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: f"\u20b9{v / 1e5:g} lakh"))
        else:
            ax.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: f"\u20b9{v:,.0f}"))
        if split:
            ax.axvline(pd.Timestamp(split), color=c["muted"], ls=":", lw=1)
        ax.grid(color=c["grid"], lw=0.8)
        ax.tick_params(colors=c["muted"], labelsize=9)
        for spine in ax.spines.values():
            spine.set_visible(False)
        span = max(v.index[-1] for _, v in series.items()) - min(v.index[0] for _, v in series.items())
        locator = (matplotlib.dates.DayLocator(interval=max(1, span.days // 6)) if span.days < 20
                   else matplotlib.dates.AutoDateLocator())
        ax.xaxis.set_major_locator(locator)
        ax.xaxis.set_major_formatter(matplotlib.dates.ConciseDateFormatter(locator))
        leg = ax.legend(fontsize=8.5, frameon=False, loc="upper center", bbox_to_anchor=(0.5, -0.09),
                        ncol=4, handlelength=1.8)
        for text in leg.get_texts():
            text.set_color(c["fg"])
        fig.savefig(os.path.join(SITE, f"{filename}-{theme}.png"), dpi=150, facecolor=c["bg"],
                    bbox_inches="tight", pad_inches=0.15)
        plt.close(fig)


def draw_breadth(series, filename):
    labels = {"above_200": "Above 200-day average", "above_50": "Above 50-day average"}
    colors = {"light": {"above_200": "#0F4D3A", "above_50": "#C98A00"},
              "dark": {"above_200": "#6FD39C", "above_50": "#E5B23A"}}
    for theme, c in THEMES.items():
        fig, ax = plt.subplots(figsize=(9, 3.6))
        fig.patch.set_facecolor(c["bg"])
        ax.set_facecolor(c["bg"])
        for col in ("above_200", "above_50"):
            ax.plot(series.index, series[col] * 100, label=labels[col], color=colors[theme][col],
                    lw=1.8 if col == "above_200" else 1.2)
        ax.axhline(50, color=c["muted"], ls=":", lw=1)
        ax.set_ylim(0, 100)
        ax.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: f"{v:.0f}%"))
        span = max(v.index[-1] for _, v in series.items()) - min(v.index[0] for _, v in series.items())
        locator = (matplotlib.dates.DayLocator(interval=max(1, span.days // 6)) if span.days < 20
                   else matplotlib.dates.AutoDateLocator())
        ax.xaxis.set_major_locator(locator)
        ax.xaxis.set_major_formatter(matplotlib.dates.ConciseDateFormatter(locator))
        ax.grid(color=c["grid"], lw=0.8)
        ax.tick_params(colors=c["muted"], labelsize=9)
        for spine in ax.spines.values():
            spine.set_visible(False)
        leg = ax.legend(fontsize=8.5, frameon=False, loc="upper center", bbox_to_anchor=(0.5, -0.12), ncol=2)
        for text in leg.get_texts():
            text.set_color(c["fg"])
        fig.savefig(os.path.join(SITE, f"{filename}-{theme}.png"), dpi=150, facecolor=c["bg"],
                    bbox_inches="tight", pad_inches=0.15)
        plt.close(fig)


def picture(filename, alt):
    return (f'<picture><source srcset="{filename}-dark.png" media="(prefers-color-scheme: dark)">'
            f'<img src="{filename}-light.png" alt="{esc(alt)}" loading="lazy"></picture>')


# -------------------------------- backtest --------------------------------------
def backtest_summary():
    closes = bt.load_all()
    R = closes / closes.shift(1) - 1
    end = bt.END or closes.index[-1]
    rows, curves = {}, {}
    for name, W in bt.make_strategies(closes).items():
        r, _ = bt.backtest(R, W, bt.DELAY, bt.START, end)
        s = bt.stats(r)
        row = {"ret": s["Return per year"], "day": s["Avg per trading day"],
               "fall": s["Worst fall (max drawdown)"], "final": s["Final value (Rs)"]}
        if bt.SPLIT:
            row["in"] = bt.stats(r[r.index < bt.SPLIT])["Return per year"]
            row["out"] = bt.stats(r[r.index >= bt.SPLIT])["Return per year"]
        rows[name] = row
        curves[name] = bt.CAPITAL * (1 + r).cumprod()
    first = next(iter(curves.values())).index
    return rows, curves, first[0], first[-1]


# ---------------------------------- page ----------------------------------------
CSS = """
:root{--bg:#F3F6F4;--surface:#FFFFFF;--ink:#1E2B25;--muted:#5C6B63;--rule:#D5DDD8;
--board:#0F4D3A;--board-ink:#EEF5F0;--board-muted:#A6C3B4;--board-rule:rgba(238,245,240,.14);
--score:#F2C14E;--up:#1D7A49;--down:#B3362B;--board-up:#8EE3B5;--board-down:#FFA295;color-scheme:light}
@media (prefers-color-scheme:dark){:root{--bg:#0F1613;--surface:#17211C;--ink:#DDE6E1;--muted:#93A49B;
--rule:#2B3832;--board:#123B2D;--up:#6FD39C;--down:#FF8C7E;color-scheme:dark}}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--bg);color:var(--ink);font:400 1.0625rem/1.55 "Barlow",system-ui,
-apple-system,"Segoe UI",Roboto,Arial,sans-serif}
.wrap{max-width:68rem;margin:0 auto;padding:1rem 1.25rem 4rem}
.topnav{display:flex;flex-wrap:wrap;gap:0 .25rem;margin:0 0 1.75rem;border-bottom:1px solid var(--rule)}
.topnav a{display:flex;align-items:center;min-height:2.9rem;padding:0 .8rem;margin-bottom:-1px;font-weight:600;
color:var(--muted);text-decoration:none;border-bottom:3px solid transparent}
.topnav a:first-child{padding-left:0}
.topnav a:hover{color:var(--ink)}
.topnav a[aria-current=page]{color:var(--ink);border-bottom-color:var(--score)}
h1,h2,.rank,.num-big{font-family:"Barlow Condensed","Arial Narrow",system-ui,sans-serif}
h1{font-size:clamp(2.4rem,7vw,3.6rem);font-weight:600;line-height:1;margin:0 0 .75rem;letter-spacing:-.01em}
h2{font-size:1.6rem;font-weight:600;line-height:1.15;margin:0 0 .75rem}
p{margin:0 0 .75rem;max-width:42rem}
.lede{font-size:1.15rem;color:var(--ink)}
.meta{color:var(--muted);font-size:.95rem}
section{margin-top:3rem}
.board{background:var(--board);color:var(--board-ink);border-radius:.75rem;padding:1.25rem 1rem 1rem;margin-top:2rem}
.board h2{color:var(--board-ink);padding:0 .25rem}
.board .meta{color:var(--board-muted);padding:0 .25rem}
.scroll{overflow-x:auto;-webkit-overflow-scrolling:touch}
table.risk td{white-space:normal}table.risk td.r{white-space:nowrap}
table.risk .sub2{display:block;font-size:.88rem;color:var(--muted);margin-top:.15rem;white-space:normal}
table.risk .sub2.down{color:var(--down)}
table{border-collapse:collapse;width:100%;font-variant-numeric:tabular-nums}
th,td{padding:.6rem .55rem;text-align:left;vertical-align:baseline;white-space:nowrap}
th{font-weight:500;color:var(--muted);font-size:.9rem;border-bottom:1px solid var(--rule)}
td{border-bottom:1px solid var(--rule)}
td.ev-what{white-space:normal;min-width:13rem}
@media (max-width:600px){td.ev-what{min-width:9.5rem}td.ev-when{white-space:normal;min-width:5.5rem}}
.board th{color:var(--board-muted);border-bottom-color:var(--board-rule)}
.board td{border-bottom-color:var(--board-rule)}
.board tr:last-child td{border-bottom:0}
.r{text-align:right}
.rank{color:var(--score);font-size:1.7rem;font-weight:700;line-height:1;width:2.2rem}
.agent{font-weight:600}
.num-big{font-size:1.25rem;font-weight:600}
.up{color:var(--up)}.down{color:var(--down)}
.board .up{color:var(--board-up)}.board .down{color:var(--board-down)}
.chip{display:inline-block;white-space:nowrap;background:var(--score);color:#1E2B25;border-radius:999px;padding:.1rem .6rem;
font-weight:600;font-size:.9rem}
.quiet{color:var(--board-muted)}
.sub-h{font:600 1.2rem/1.2 "Barlow Condensed","Arial Narrow",system-ui,sans-serif;margin:1.75rem 0 .6rem}
.stats + .meta{margin-top:.9rem}
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(8rem,1fr));gap:1rem 1.5rem;margin:0}
.stats div{border-left:3px solid var(--rule);padding-left:.75rem}
.stats dt{color:var(--muted);font-size:.9rem}
.stats dd{margin:0;font:600 1.45rem/1.2 "Barlow Condensed","Arial Narrow",system-ui,sans-serif}
dl.why{margin:0}
dl.why dt{font-weight:600;margin-top:.9rem}
dl.why dd{margin:.1rem 0 0;color:var(--muted);max-width:44rem}
figure{margin:1rem 0 0}
img{max-width:100%;height:auto;display:block;border-radius:.5rem;background:var(--surface)}
figcaption{color:var(--muted);font-size:.9rem;margin-top:.5rem}
.panel{background:var(--surface);border-radius:.5rem;padding:.25rem .75rem}
.tlist{list-style:none;margin:0}.tlist li{padding:.6rem 0;border-bottom:1px solid var(--rule)}.tlist li:last-child{border-bottom:0}.tlist .meta{display:block}.tl-what{display:block;margin-top:.15rem}
.decision{background:var(--surface);border-left:3px solid var(--board);border-radius:.25rem;padding:.9rem 1rem;margin-top:1rem}
.decision h3{font:600 1.15rem/1.2 "Barlow Condensed","Arial Narrow",system-ui,sans-serif;margin:0 0 .4rem}
.decision ul{margin:.25rem 0 .5rem;padding-left:1.2rem}
.decision p{margin:0 0 .35rem}
.warn{background:var(--surface);border-left:3px solid var(--down);border-radius:.25rem;padding:.9rem 1rem;margin-top:1.5rem}
.links{margin:.5rem 0 0;padding-left:1.2rem}
section>h3{font:600 1.15rem/1.2 "Barlow Condensed","Arial Narrow",system-ui,sans-serif;margin:1.6rem 0 .5rem}
.links li{margin:.3rem 0}
.how{background:var(--surface);border-left:3px solid var(--score);padding:.9rem 1rem;border-radius:.25rem;margin-top:1rem}
code{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:.9em;background:var(--rule);
padding:.05rem .3rem;border-radius:.25rem}
footer{margin-top:4rem;padding-top:1.25rem;border-top:1px solid var(--rule);color:var(--muted);font-size:.9rem}
a{color:inherit;text-decoration-thickness:1px;text-underline-offset:2px}
a:focus-visible{outline:2px solid var(--score);outline-offset:2px}
.board td.c-holding,.board td.c-today,.board td.c-next{white-space:normal;min-width:6.5rem}
.m-label{display:none}
@media (max-width:40rem){.wrap{padding-top:.5rem}.topnav{margin-bottom:1.25rem}th,td{padding:.5rem .45rem}.rank{font-size:1.4rem}
.board{padding:1rem .75rem .5rem}
.board thead{display:none}.board table,.board tbody{display:block}.board .scroll{overflow:visible}
.board tr{display:grid;grid-template-columns:2rem 1fr auto;grid-template-areas:"rank agent value" "rank holding since" "rank next next";
column-gap:.6rem;row-gap:.1rem;padding:.75rem .1rem;border-bottom:1px solid var(--board-rule)}
.board tr:last-child{border-bottom:0}
.board td{display:block;padding:0;border:0;white-space:normal;min-width:0}
.board td.c-holding,.board td.c-next{min-width:0}
.board .c-rank{grid-area:rank}.board .c-agent{grid-area:agent}.board .c-value{grid-area:value}
.board .c-holding{grid-area:holding;color:var(--board-muted)}.board .c-since{grid-area:since}
.board .c-next{grid-area:next;margin-top:.35rem}.m-label{display:inline;color:var(--board-muted)}
.board .c-fall,.board .c-trades,.board .c-today{display:none}}

.scoreboard{background:var(--board);color:var(--board-ink);border-radius:.75rem;padding:1rem 1rem .5rem;margin-top:1.75rem}
.scoreboard h2{color:var(--board-ink);margin-bottom:.25rem}
.scoreboard .meta{color:var(--board-muted)}
.scoreboard th{color:var(--board-muted);border-bottom-color:var(--board-rule)}
.scoreboard td{border-bottom-color:var(--board-rule);vertical-align:top}
.scoreboard tr.grp td{color:var(--score);font:600 1.05rem/1.2 "Barlow Condensed","Arial Narrow",system-ui,sans-serif;
padding-top:1.1rem;border-bottom:1px solid var(--board-rule)}
.scoreboard td.name{white-space:normal;font-weight:600}
.scoreboard .sub{display:block;font-weight:400;font-size:.88rem;color:var(--board-muted);margin-top:.1rem}
.scoreboard .up{color:var(--board-up)}.scoreboard .down{color:var(--board-down)}
.scoreboard tr.main td{border-bottom:0;padding-bottom:0}
.scoreboard tr.more td{padding-top:0;white-space:normal}
.scoreboard tr.more td>div{width:0;min-width:100%}
.scoreboard tbody:last-child tr.more td{border-bottom:0}
.scoreboard .n{white-space:nowrap}
.scoreboard>.meta+.scroll{margin-top:.5rem}
.scoreboard details.mini summary{color:var(--board-muted)}
details.more{background:var(--surface);border-radius:.6rem;margin-top:.9rem;padding:0 1rem}
details.more>summary{cursor:pointer;list-style:none;padding:.95rem 0;display:flex;justify-content:space-between;
align-items:baseline;gap:1rem;font:600 1.3rem/1.2 "Barlow Condensed","Arial Narrow",system-ui,sans-serif}
details.more>summary::-webkit-details-marker{display:none}
details.more>summary::after{content:"+";color:var(--muted);font-size:1.4rem}
details.more[open]>summary::after{content:"\\2212"}
details.more>summary .hint{flex:1;font:400 .92rem/1.35 "Barlow",system-ui,sans-serif;color:var(--muted)}
details.more[open]{padding-bottom:1rem}
details.more section{margin-top:1.25rem}
details.more section h2{font-size:1.3rem}
details.more.solo>section>h2:first-child{display:none}
details.more.solo>section{margin-top:0}
details.mini summary{cursor:pointer;color:var(--muted);font-size:.95rem;margin-top:.4rem}
.calls li .tl-what{white-space:normal}
.tl-fix{display:block;margin-top:.4rem;padding:.35rem .6rem;border-left:3px solid var(--score);background:var(--bg);font-size:.92rem}
.tl-what strong,.tl-claim strong{white-space:nowrap}
.tl-claim{display:block;margin-top:.3rem;padding-left:.6rem;border-left:2px solid var(--rule);color:var(--muted);font-size:.92rem}
.checks{margin:.8rem 0 1rem}.checks .verdict{margin:0 0 .35rem}.checklist{list-style:none;margin:0;padding:0}
.checklist li{padding:.15rem 0 .15rem 1.2rem;text-indent:-1.2rem;font-size:.95rem}.checklist .mark{display:inline-block;width:1.2rem;text-indent:0;font-weight:700}
.checklist .ok .mark{color:var(--up)}.checklist .no .mark{color:var(--down)}.checklist .wait .mark{color:var(--muted)}
@media (max-width:40rem){.scoreboard{padding:.85rem .6rem .4rem}details.more>summary{flex-wrap:wrap}
details.more>summary .hint{flex-basis:100%;order:3}}
"""


def board_html(res):
    if not res["started"]:
        rows = "".join(
            f"<tr><td class='agent'>{esc(n)}</td><td>{esc(p)}</td></tr>" for n, p in res["plan"].items())
        return (f"<section class='board' aria-labelledby='board-h'><h2 id='board-h'>Day-one positions</h2>"
                f"<p class='meta'>Paper trading starts on {day(pd.Timestamp(pa.START))}. At that day's close, "
                f"each agent puts its {inr(pa.CAPITAL)} into the position below.</p>"
                f"<div class='scroll'><table><thead><tr><th>Agent</th><th>Will hold</th></tr></thead>"
                f"<tbody>{rows}</tbody></table></div></section>")
    rows = []
    for rank, (name, r) in enumerate(res["board"].iterrows(), start=1):
        today = esc(r["today"]) if isinstance(r["today"], str) else "<span class='quiet'>No trade</span>"
        nxt = (f"<span class='chip'>{esc(r['next'])}</span>" if isinstance(r["next"], str)
               else "<span class='quiet'>Hold</span>")
        rows.append(
            f"<tr><td class='rank c-rank'>{rank}</td><td class='agent c-agent'>{esc(name)}</td>"
            f"<td class='c-holding'>{esc(r['holding'])}</td>"
            f"<td class='r num-big c-value'>{inr(r['value'])}</td>"
            f"<td class='r c-since {tone(r['since_start'])}'>{pct(r['since_start'], True, 2)}</td>"
            f"<td class='r c-fall'>{pct(r['worst_fall'])}</td><td class='r c-trades'>{r['trades']}</td>"
            f"<td class='c-today'>{today}</td><td class='c-next'><span class='m-label'>At next close: </span>{nxt}</td></tr>")
    return (f"<section class='board' aria-labelledby='board-h'><h2 id='board-h'>Standings</h2>"
            f"<p class='meta'>Each agent started with {inr(pa.CAPITAL)} on {day(res['s0'])}. "
            f"Trades happen at the close, and “At next close” shows what each agent will do next.</p>"
            f"<div class='scroll'><table><thead><tr><th><span class='visually-hidden'>Rank</span>#</th>"
            f"<th>Agent</th><th>Holding now</th><th class='r'>Value</th><th class='r'>Since start</th>"
            f"<th class='r'>Worst fall</th><th class='r'>Trades</th><th>Today</th><th>At next close</th></tr>"
            f"</thead><tbody>{''.join(rows)}</tbody></table></div></section>")


def market_html(res, ctx):
    m = res["market"]
    items = [("Close", f"{m['close']:,.2f}", ""), ("On the day", pct(m["change"], True, 2), tone(m["change"])),
             ("200-day average", f"{m['sma200']:,.0f}", ""), ("50-day average", f"{m['sma50']:,.0f}", ""),
             ("5-day average", f"{m['sma5']:,.0f}", ""), ("RSI(2)", f"{m['rsi2']:.0f}", "")]
    cells = "".join(f"<div><dt>{esc(k)}</dt><dd class='{c}'>{v}</dd></div>" for k, v, c in items)
    return (f"<section aria-labelledby='mkt-h'><h2 id='mkt-h'>Nifty 50 at the latest close</h2>"
            f"<p class='meta'>{day(res['latest'])}</p><dl class='stats'>{cells}</dl>{context_html(ctx)}</section>")


def crore(v):
    sign = "+" if v > 0 else "\u2212" if v < 0 else ""
    return f"{sign}\u20b9{abs(v):,.0f} cr"


def context_html(ctx):
    b, f = ctx.get("breadth"), ctx.get("flows")
    if not b and (f is None or not len(f)):
        return ""
    items, notes = [], []
    if b:
        items += [("Stocks above 200-day avg", f"{b['above_200']:.0%}", ""),
                  ("Stocks above 50-day avg", f"{b['above_50']:.0%}", "")]
        notes.append(f"Breadth is the share of the Nifty 50's stocks trading above their own averages, as of "
                     f"{day(b['date'])}. As a rough guide, below about 30% means most stocks are falling and above "
                     f"about 70% means most are rising.")
    if f is not None and len(f):
        last = f.iloc[-1]
        items += [("FII net", crore(last["FII_Net_Cr"]), tone(last["FII_Net_Cr"])),
                  ("DII net", crore(last["DII_Net_Cr"]), tone(last["DII_Net_Cr"])),
                  ("FII, last 5 sessions", crore(f["FII_Net_Cr"].tail(5).sum()), tone(f["FII_Net_Cr"].tail(5).sum()))]
        notes.append(f"FII and DII figures are net cash-market buying or selling on {day(f.index[-1])}"
                     + (" (NSE’s provisional figures)." if f.attrs.get("nse") else "."))
    cells = "".join(f"<div><dt>{esc(k)}</dt><dd class='{c}'>{v}</dd></div>" for k, v, c in items)
    chart = ""
    if b and len(b["series"]) > 20:
        draw_breadth(b["series"], "breadth")
        chart = ("<figure>" + picture("breadth", "Line chart of the share of Nifty 50 stocks above their "
                                      "200-day and 50-day averages over the past year") + "</figure>")
    return (f"<h3 class='sub-h'>Breadth and institutional flows</h3><dl class='stats'>{cells}</dl>"
            + "".join(f"<p class='meta'>{esc(n)}</p>" for n in notes) + chart)


def why_html(res):
    order = list(res["board"].index) if res["started"] else list(res["plan"])
    items = "".join(f"<dt>{esc(n)}</dt><dd>{esc(res['why'][n])}</dd>" for n in order)
    return f"<section aria-labelledby='why-h'><h2 id='why-h'>Why each agent holds what it holds</h2><dl class='why'>{items}</dl></section>"


def arena_chart_html(res):
    if not res["started"] or len(res["values"]) < 2:
        return ("<section aria-labelledby='val-h'><h2 id='val-h'>Value since the start</h2>"
                "<p class='meta'>The chart appears after the second trading day of paper trading.</p></section>")
    draw({n: res["values"][n] for n in res["values"].columns}, "arena")
    return ("<section aria-labelledby='val-h'><h2 id='val-h'>Value since the start</h2><figure>"
            + picture("arena", "Line chart of each agent's virtual portfolio value since paper trading began")
            + "</figure></section>")


def trades_html(res):
    if not res["started"] or not res["trades"]:
        return ("<section aria-labelledby='tr-h'><h2 id='tr-h'>Trades</h2><p class='meta'>No trades yet. "
                "The first ones happen at the close on the first day of paper trading.</p></section>")
    rows = "".join(
        f"<tr><td>{day(t['date'])}</td><td class='agent'>{esc(t['agent'])}</td><td>{esc(t['what'])}</td>"
        f"<td class='r'>{t['nifty']:,.2f}</td></tr>" for t in res["trades"])
    return (f"<section aria-labelledby='tr-h'><h2 id='tr-h'>Trades</h2><div class='panel scroll'><table>"
            f"<thead><tr><th>Date</th><th>Agent</th><th>Trade at the close</th><th class='r'>Nifty 50 close</th>"
            f"</tr></thead><tbody>{rows}</tbody></table></div></section>")


def claude_html(res):
    log = res.get("claude_log") or []
    intro = ("<p class='meta'>Claude reads the rule agents' signals and the day's market news after each close, "
             "then picks 0, half or all in Nifty 50. Each decision is filled at the next close.</p>")
    if not log:
        return (f"<section aria-labelledby='cl-h'><h2 id='cl-h'>Claude's decisions</h2>{intro}"
                f"<p class='meta'>No decisions yet.</p></section>")
    items = []
    for d in log[:15]:
        reasons = "".join(f"<li>{esc(r)}</li>" for r in d.get("reasons", []))
        conds = ""
        if d.get("go_to_cash_if"):
            conds += f"<p class='meta'>Goes to cash if {esc(d['go_to_cash_if'].rstrip('.'))}.</p>"
        if d.get("go_fully_in_if"):
            conds += f"<p class='meta'>Goes fully in if {esc(d['go_fully_in_if'].rstrip('.'))}.</p>"
        items.append(
            f"<article class='decision'><h3>{day(pd.Timestamp(d['date']))}: {float(d['position']):.0%} in Nifty 50</h3>"
            f"<p>{esc(d.get('summary', ''))}</p>{'<ul>' + reasons + '</ul>' if reasons else ''}{conds}</article>")
    return (f"<section aria-labelledby='cl-h'><h2 id='cl-h'>Claude's decisions</h2>{intro}{''.join(items)}"
            f"<p class='meta'>If no new decision appears after a close, the API key isn't set up or the call "
            f"failed, and Claude keeps its last position.</p></section>")


def calls_html(res):
    how = ("<div class='how'><p><strong>Add your call:</strong> open <code>paper_arena.py</code> on GitHub, click "
           "the pencil icon, and add a line under <code>\"Me\"</code> such as <code>\"2026-10-23\": 1.0,</code> "
           "using that evening's date. 0 means all cash, 0.5 half in Nifty, 1 fully in Nifty. Commit the change "
           "and this page rebuilds in a few minutes.</p><p>Never add a call with a past date; that would use "
           "hindsight.</p></div>")
    calls = {k: v for k, v in res["manual"].items() if not (k == "Claude" and res.get("claude_log"))}
    if not calls:
        return (f"<section aria-labelledby='calls-h'><h2 id='calls-h'>Your calls</h2><p class='meta'>You haven't "
                f"joined the arena yet. Add your own calls to see whether your judgment beats the rules and "
                f"Claude.</p>{how}</section>")
    rows = "".join(
        f"<tr><td class='agent'>{esc(agent)}</td><td>{day(pd.Timestamp(d))}</td><td class='r'>{float(v):.0%}</td></tr>"
        for agent, entries in calls.items() for d, v in sorted(entries.items(), reverse=True))
    return (f"<section aria-labelledby='calls-h'><h2 id='calls-h'>Your calls</h2><div class='panel scroll'><table>"
            f"<thead><tr><th>Agent</th><th>Decided on</th><th class='r'>Share in Nifty 50</th></tr></thead>"
            f"<tbody>{rows}</tbody></table></div>{how}</section>")


def drift_html(view):
    found = logbook.drift(view)
    if not found:
        return ""
    span = (day(found['first']) if found['first'] == found['last']
            else f"{day(found['first'])} to {day(found['last'])}")
    return (f"<p class='meta'>Note: tonight’s replay differs from the saved log on {found['rows']} "
            f"{'row' if found['rows'] == 1 else 'rows'}, all on {span} and all "
            f"{'F&amp;O agents' if found['fno_only'] else 'in ' + esc(', '.join(found['agents']))} "
            f"(largest {inr(found['largest'])}, {esc(found['agent'])} on {day(found['date'])}). Those rows were saved "
            f"the night they happened, before NSE’s option prices for the day had arrived, so they used estimated "
            f"prices; the replay uses the real ones. Saved rows are never rewritten, so the saved log stays the "
            f"official record and this note stays with it. Rows after {day(found['last'])} match.</p>")


def logs_html():
    info = logbook.summary()
    repo = os.environ.get("GITHUB_REPOSITORY", "")

    def link(path, text, folder=False):
        if not repo:
            return f"<code>{esc(path)}</code>"
        return f"<a href='https://github.com/{repo}/{'tree' if folder else 'blob'}/main/{path}'>{esc(text)}</a>"

    if info:
        intro = (f"<p>The saved log covers {day(info['first'])} to {day(info['last'])}: {info['days']} trading "
                 f"days and {info['trades']} trades. Each night adds new rows; old rows are never rewritten.</p>")
    else:
        intro = "<p class='meta'>The saved log starts with the first nightly run after paper trading begins.</p>"
    items = [("logs/daily.csv", "Daily log", False, "every agent's holding and value each day"),
             ("logs/trades.csv", "Trade log", False, "every trade, with Nifty 50's close"),
             ("decisions/snapshots", "Claude's snapshots", True, "the data behind each Claude decision"),
             ("data/fno", "NSE option prices", True, "the daily option prices the F&O agents traded at"),
             ("data/market", "Saved market prices", True, "daily ETF, gold, silver and S&P 500 prices for the gold "
                                                         "and multi-asset agents, and Brent and the rupee for events"),
             ("data/events", "Market events", True, "the calendar of scheduled events and the log of what happened, "
                                                     "each with its source"),
             ("logs/starts.json", "Start dates", False, "when each newer agent started paper trading"),
             ("logs/risk_orders.csv", "Risk engine decisions", False, "every paper order the risk engine checked, "
                                                                       "and why it let it through or refused it"),
             ("data/berlin/telegram_posts.csv", "Telegram archive", False, "every Trade Like Berlin Telegram post, "
                                                                          "saved the night it appeared"),
             ("data/berlin/telegram_calls.csv", "Tagged calls", False, "which posts count as trade calls, and their levels"),
             ("logs/berlin_calls.csv", "Call results", False, "how each call did when paper traded"),
             ("data/berlin/telegram_updates.csv", "His later posts", False, "his exits, stop moves and claims about "
                                                                            "each call, and whether the record agrees"),
             ("logs/berlin_variants.csv", "Late and reversed checks", False, "each call taken 15 and 30 minutes late, "
                                                                            "and reversed"),
             ("logs/berlin_etf.csv", "NIFTYBEES copy", False, "his Nifty calls copied onto NIFTYBEES at Zerodha’s "
                                                               "charges, on time and late"),
             ("data/berlin/call_corrections.csv", "Corrections", False, "calls we misread, noted without changing "
                                                                        "their scores"),
             ("data/berlin/telegram_reviewed.csv", "Decision log", False, "what Claude decided about each post, "
                                                                          "and why"),
             ("data/real/orders.csv", "Real-money ledger", False, "orders you placed yourself at Zerodha, written "
                                                                   "down afterwards"),
             ("logs/journal.md", "Your journal", False, "your evening notes, which you edit on GitHub")]
    for ch in channels.CHANNELS.values():
        if ch["tagging"] != "parser":
            continue
        f, name = ch["folder"], ch["name"]
        items[-1:-1] = [(f, f"{name}: saved posts and signals", True, "every post as first seen, the decision "
                                                                       "on each, the signals and his later posts"),
                        (ch["results"], f"{name}: results", False, "how each signal did when paper traded"),
                        (ch["results"].replace("_calls.csv", "_variants.csv"), f"{name}: late and reversed checks",
                         False, "each signal taken 15 and 30 minutes late, and reversed")]
    links = "".join(f"<li>{link(p, t, f)}: {esc(d)}</li>" for p, t, f, d in items)
    return (f"<section aria-labelledby='log-h'><h2 id='log-h'>Permanent record</h2>{intro}"
            f"<ul class='links'>{links}</ul></section>")


def fno_backtest_html(fbt):
    if not fbt:
        return ""
    rows, first, last = fbt
    items = []
    for r in rows:
        if r["fixed"] or abs(r["high"] - r["low"]) < 0.005:
            ret = f"<span class='{tone(r['mid'])}'>{pct(r['mid'], True)}</span>"
        else:
            ret = f"{pct(r['low'], True, 0)} to {pct(r['high'], True, 0)}"
        items.append(f"<li><strong>{esc(r['agent'])}</strong><span class='tl-what'>Return a year {ret} · "
                     f"worst fall {pct(r['worst_fall'], digits=0)}</span></li>")
    return (f"<h3>Backtest, {day(first)} to {day(last)}</h3><ul class='panel tlist'>{''.join(items)}</ul>"
            f"<p class='meta'>After costs, with {inr(pa.CAPITAL)} at 3x exposure (option buying: 3% of capital a "
            f"week); the whole-lot rows use ₹5 lakh in today’s lot of 65 and are shown per {inr(pa.CAPITAL)}. Free "
            f"data has no past option prices, so the backtest estimates them from India VIX; the "
            f"ranges show results at three different estimates, and worst falls use the middle one. The futures "
            f"rows use real index prices. Paper trading above uses NSE’s real prices where it has them.</p>")


def rupee_text(text):
    """Trade notes say "+Rs 1,234" / "-Rs 1,234"; show them with the rupee sign and a true minus."""
    return esc(text).replace("-Rs ", "\u2212\u20b9").replace("+Rs ", "+\u20b9")


def fno_html(fres, fbt):
    head = "<section aria-labelledby='fno-h'><h2 id='fno-h'>F&amp;O arena</h2>"
    whole = (f" The {len(TWINS)} marked “whole lots” trade real lots of 65 on ₹5 lakh each, with margin checked: "
             f"what the same rules need at the smallest real size. Their values are shown per {inr(pa.CAPITAL)} so "
             f"they compare (dashed lines on the chart), and the rupees in their trade notes are the ₹5 lakh "
             f"account’s." if TWINS else "")
    intro = (f"<p>{len(fno_arena.RULES)} futures and options strategies. Most trade {inr(pa.CAPITAL)} of virtual "
             f"money in fractions of a lot, as a test of the rule.{whole} They are kept apart from the Nifty agents "
             f"because they use leverage. In SEBI’s study of FY26, 87.7% of individual F&amp;O traders lost money.</p>")
    if fres is None:
        return head + intro + "<p class='meta'>The F&amp;O agents couldn’t be updated tonight.</p>" + \
            fno_backtest_html(fbt) + "</section>"
    rules = "".join(f"<li><strong>{esc(n)}:</strong> {esc(r['rule'])}</li>" for n, r in fres["board"].iterrows())
    if not fres["started"]:
        when = (f"on {day(fres['start'])}" if fres.get("start") is not None
                else "on the first trading day after these files are added")
        body = (f"<p class='meta'>Paper trading starts {when}.</p>"
                f"<ul class='links'>{rules}</ul>")
    else:
        rows = []
        for rank, (name, r) in enumerate(fres["board"].iterrows(), start=1):
            today = rupee_text(r["today"]) if isinstance(r["today"], str) else "<span class='quiet'>No trade</span>"
            rows.append(
                f"<tr><td class='rank c-rank'>{rank}</td><td class='agent c-agent'>{esc(name)}</td>"
                f"<td class='c-holding'>{esc(r['holding'])}</td>"
                f"<td class='r num-big c-value'>{inr(r['value'])}</td>"
                f"<td class='r c-since {tone(r['since_start'])}'>{pct(r['since_start'], True, 2)}</td>"
                f"<td class='r c-fall'>{pct(r['worst_fall'])}</td><td class='r c-trades'>{r['trades']}</td>"
                f"<td class='c-today'>{today}</td></tr>")
        real = (f"Option prices: NSE’s real prices on {fres['real_days']} of {fres['days']} trading days"
                + ("." if fres["real_days"] == fres["days"] else ", estimates on the rest."))
        began = {d for d in fres["board"]["start"] if d is not None and not pd.isna(d)}
        started = (f"Started with {inr(pa.CAPITAL)} each on {day(fres['start'])}." if len(began) <= 1 else
                   f"Each started with {inr(pa.CAPITAL)} on its own start date, the first on {day(fres['start'])}.")
        body = (f"<p class='meta'>{started} {real}</p>"
                f"<div class='board'><div class='scroll'><table><thead><tr><th><span class='visually-hidden'>Rank"
                f"</span>#</th><th>Agent</th><th>Holding now</th><th class='r'>Value</th><th class='r'>Since start"
                f"</th><th class='r'>Worst fall</th><th class='r'>Trades</th><th>Today</th></tr></thead>"
                f"<tbody>{''.join(rows)}</tbody></table></div></div>")
        since = fres["values"].loc[fres["start"]:]
        running = [n for n in since.columns if fres["board"].at[n, "holding"] != "Not started yet"]
        if len(since) >= 2:
            draw({n: since[n] for n in running}, "fno")
            body += "<figure>" + picture("fno", "Line chart of each F&O agent's virtual value since it started") \
                + "</figure>"
        recent = fres["trades"][:20]
        if recent:
            items = "".join(f"<li><span class='meta'>{day(t['date'])} · {esc(t['agent'])}</span>"
                            f"<span class='tl-what'>{rupee_text(t['what'])}</span></li>" for t in recent)
            body += (f"<h3>Latest F&amp;O trades</h3><ul class='panel tlist'>{items}</ul>"
                     f"<p class='meta'>Every trade is in the trade log under Permanent record.</p>")
        body += f"<h3>Rules</h3><ul class='links'>{rules}</ul>"
    return head + intro + body + fno_backtest_html(fbt) + "</section>"


def asset_backtest_html(abt, names=None):
    if not abt:
        return ""
    rows, sources = abt
    rows = [r for r in rows if names is None or r["agent"] in names]
    if not rows:
        return ""
    items = []
    for r in rows:
        verdict = (f"<span class='{tone(1)}'>passes</span>" if r["pass"] else f"<span class='{tone(-1)}'>fails</span>")
        items.append(f"<li><strong>{esc(r['agent'])}</strong><span class='tl-what'>{pct(r['cagr'], True)} a year, "
                     f"worst fall {pct(r['dd'], digits=0)}. {esc(r['bench'])}: {pct(r['bench_cagr'], True)}, worst "
                     f"{pct(r['bench_dd'], digits=0)}. Pass bar {verdict}.</span>"
                     f"<span class='meta'>{day(r['start'])} to {day(r['end'])}</span></li>")
    return (f"<h3>Backtest after costs</h3><ul class='panel tlist'>{''.join(items)}</ul>"
            f"<p class='meta'>ETF trades cost 0.05% a buy or sell, Gold Petal futures 0.05% plus a monthly roll, and "
            f"idle cash earns {pa.CASH_RATE:.0%}. Every rule acts at the close the day after its signal. The pass bar "
            f"is the research report's test for each agent, met in both halves of the period at normal and double "
            f"costs. Gold prices: {esc(sources.get('GOLDBEES', ''))}. Past results don’t predict future ones.</p>")


def asset_html(ares, abt):
    names = [n for n in asset_arena.AGENTS if n not in berlin.STRATEGIES]
    ares = only(ares, names)
    head = "<section aria-labelledby='asset-h'><h2 id='asset-h'>Gold and multi-asset arena</h2>"
    intro = (f"<p>Four agents built from the research's evidence and from strategies shared on Reddit and X, "
             f"each with {inr(pa.CAPITAL)} of virtual money. They trade NSE gold, silver and Nifty ETFs, which "
             f"Indian residents can legally use. The channel’s own two rules are under Trade Like Berlin.</p>")
    if ares is None:
        return head + intro + "<p class='meta'>These agents couldn’t be updated tonight.</p>" + \
            asset_backtest_html(abt, names) + "</section>"
    why = ares.get("why", {})
    rules = "".join(f"<li><strong>{esc(n)}:</strong> {esc(r['rule'])}"
                    + (f" <span class='meta'>Now: {esc(why[n])}</span>" if n in why else "") + "</li>"
                    for n, r in ares["board"].iterrows())
    if not ares["started"]:
        first = ares.get("first_start")
        when = f"on {day(first)}" if first is not None else "on the first trading day after these files are added"
        body = f"<p class='meta'>Paper trading starts {when}.</p><ul class='links'>{rules}</ul>"
    else:
        rows = []
        for rank, (name, r) in enumerate(ares["board"].iterrows(), start=1):
            today = esc(r["today"]) if isinstance(r["today"], str) else "<span class='quiet'>No trade</span>"
            nxt = (f"<span class='chip'>{esc(r['next'])}</span>" if isinstance(r["next"], str)
                   else "<span class='quiet'>Hold</span>")
            rows.append(
                f"<tr><td class='rank c-rank'>{rank}</td><td class='agent c-agent'>{esc(name)}</td>"
                f"<td class='c-holding'>{esc(r['holding'])}</td>"
                f"<td class='r num-big c-value'>{inr(r['value'])}</td>"
                f"<td class='r c-since {tone(r['since_start'])}'>{pct(r['since_start'], True, 2)}</td>"
                f"<td class='r c-fall'>{pct(r['worst_fall'])}</td><td class='r c-trades'>{r['trades']}</td>"
                f"<td class='c-today'>{today}</td><td class='c-next'><span class='m-label'>At next close: </span>"
                f"{nxt}</td></tr>")
        body = (f"<p class='meta'>Prices up to the close on {day(ares['latest'])}. Each agent started with "
                f"{inr(pa.CAPITAL)} on its own start date.</p>"
                f"<div class='board'><div class='scroll'><table><thead><tr><th><span class='visually-hidden'>Rank"
                f"</span>#</th><th>Agent</th><th>Holding now</th><th class='r'>Value</th><th class='r'>Since start"
                f"</th><th class='r'>Worst fall</th><th class='r'>Trades</th><th>Today</th><th>At next close</th>"
                f"</tr></thead><tbody>{''.join(rows)}</tbody></table></div></div>")
        first = ares.get("first_start")
        since = ares["values"].loc[first:] if first is not None else ares["values"].iloc[0:0]
        if len(since) >= 2:
            draw({n: since[n] for n in since.columns}, "assets")
            body += "<figure>" + picture("assets", "Line chart of each gold and multi-asset agent's virtual value") \
                + "</figure>"
        recent = ares["trades"][:20]
        if recent:
            items = "".join(f"<li><span class='meta'>{day(t['date'])} · {esc(t['agent'])}</span>"
                            f"<span class='tl-what'>{esc(t['what'])}</span></li>" for t in recent)
            body += f"<h3>Latest trades</h3><ul class='panel tlist'>{items}</ul>"
        body += f"<h3>Rules and where each signal stands</h3><ul class='links'>{rules}</ul>"
    return head + intro + body + asset_backtest_html(abt, names) + "</section>"


def only(res, names):
    """A copy of an arena's results with just some of its agents."""
    if res is None:
        return None
    out = dict(res)
    out["board"] = res["board"][res["board"].index.isin(names)]
    out["values"] = res["values"][[c for c in res["values"].columns if c in names]]
    out["trades"] = [t for t in res["trades"] if t["agent"] in names]
    out["started"] = bool((out["board"]["holding"] != "Not started yet").any())
    starts_ = [d for d in out["board"].get("start", pd.Series(dtype=object)) if d is not None and not pd.isna(d)]
    out["first_start"] = min(starts_) if starts_ else None
    return out


def ist(ts):
    t = pd.Timestamp(ts).tz_convert("Asia/Kolkata")
    return f"{t.day} {t:%b}, {t:%H:%M}"


# ------------------------------- the scoreboard ----------------------------------
def board_rows(res, names=None):
    """(name, value, since start, small note) for each agent of one arena, best first."""
    if res is None:
        return []
    board = res["board"] if names is None else res["board"][res["board"].index.isin(names)]
    out = []
    for name, r in board.iterrows():
        if r["holding"] == "Not started yet":
            start = r.get("start")
            note = (f"Starts {day(start)}" if start is not None and not pd.isna(start) else "Starts soon")
            out.append((name, None, None, note))
        else:
            out.append((name, r["value"], r["since_start"], r["holding"]))
    return sorted(out, key=lambda x: -(x[1] or 0))


CONFIDENCE_LEVELS = (          # set on 11 Nov 2026; like the luck test's own bar, they don't change
    "fewer than 20 trading days: too early to say anything",
    f"20 to {scorecard.MIN_DAYS - 1} days: still too early for the luck test",
    f"{scorecard.MIN_DAYS} days or more, but no better than luck so far, or behind cash",
    "passes the luck test: ahead of cash, with under a 1-in-20 chance that it is luck",
    "passes it over 250 trading days or more",
    "passes it over 250 days or more and is ahead of buy-and-hold Nifty over the same days",
)
NIFTY_HOLD = "Buy & hold"      # the agent whose value is Nifty 50 bought on day one and held


def started_values(view):
    """Each agent's daily values from the close at which its Rs 1 lakh went in, which is always the first
    value, to the day the board shows; without the flat days before it began. An agent that hasn't begun
    gets an empty series."""
    out = {}
    for block in view or ():
        for name in block["values"].columns:
            v = pd.to_numeric(block["values"][name], errors="coerce")
            labels = block["labels"].get(name)
            began = ([True] * len(v) if labels is None else
                     pd.Series(labels).reindex(v.index).ne("Not started yet").tolist())
            if True not in began:
                out[name] = v.iloc[:0]
                continue
            first = began.index(True)
            if first and abs(float(v.iloc[first]) - pa.CAPITAL) > 0.005:
                first -= 1          # it earned or lost on its first day, so its money went in at the close before
            out[name] = v.iloc[first:].dropna()
    return out


def beats_luck(lk):
    """The luck test's pass (scorecard.agent_luck): enough days, ahead of cash, and under a 1-in-20 chance
    that it is luck. Ahead means by more than a paisa in Rs 1 lakh: an agent sitting in cash differs from
    cash only by rounding inside the computer, and that must never count as an edge."""
    return bool(lk and lk["enough"] and lk["excess"] > 1e-7 and lk["p"] is not None and lk["p"] < 0.05)


def nifty_over(nifty, values):
    """Buy-and-hold Nifty's return over the days an agent has run, from the close its money went in.
    None when Nifty's own values don't reach the agent's last day."""
    if nifty is None or not len(nifty) or not len(values) or nifty.index[-1] < values.index[-1]:
        return None
    base = nifty.loc[:values.index[0]]
    if not len(base):
        return None
    return float(nifty.loc[:values.index[-1]].iloc[-1] / base.iloc[-1] - 1)


def confidence(values, nifty=None):
    """(score 0 to 5, a few words why) for one agent, by CONFIDENCE_LEVELS: how much evidence there is that
    its result isn't luck. Built on the luck test (scorecard.agent_luck); a high return alone never raises it."""
    lk = scorecard.agent_luck(values, pa.CASH_DAILY)
    days = lk["days"] if lk else max(len(values) - 1, 0)
    if days < scorecard.MIN_DAYS:
        return (0 if days < 20 else 1), f"{days} of {scorecard.MIN_DAYS} days"
    if not beats_luck(lk):
        return 2, "no better than luck so far"
    if days < 250:
        return 3, "passes the luck test"
    over = nifty_over(nifty, values)
    ahead = over is not None and values.iloc[-1] / values.iloc[0] - 1 > over
    return (5, "passes, over a year, ahead of Nifty") if ahead else (4, "passes, over a year")


def score_groups(res, fres, ares, tg, sigs=()):
    """The scoreboards: {"home": groups, "berlin": groups, <channel page>: groups}. A group is (title, rows);
    a row is (label, value, since start, note, key). key is the agent's name in the daily values, or None
    for a book of calls, which has no daily values."""
    keyed = lambda rows: [(n, v, c, note, n) for n, v, c, note in rows]
    berlin_names = [n for n, i in berlin.STRATEGIES.items() if i["kind"] == "agent"]
    nifty = (keyed(board_rows(res)) if res["started"] else
             [(n, None, None, f"Starts {day(pd.Timestamp(pa.START))}", None) for n in res["plan"]])
    tl = [(berlin.STRATEGIES[n]["title"], v, c, note, n) for n, v, c, note in board_rows(ares, berlin_names)]
    if tg:
        for book, title, what in (("events", "Forex news-event plan", "event"), ("calls", "His Telegram calls", "call")):
            b = tg["books"][book]
            done = b["wins"] + b["losses"]
            note = (f"{done} {what}{'s' if done != 1 else ''} closed, {b['wins']} won" if done else
                    f"No {what}s closed yet") + (f"; {b['pending']} open" if b["pending"] else "")
            tl.append((title, b["value"], b["value"] / berlin_calls.CAPITAL - 1, note, None))
        ob = tg["books"].get("options")
        if ob and ob["scored"] + ob["pending"]:
            done = ob["wins"] + ob["losses"]
            note = (f"{done} closed, {ob['wins']} won" if done else "None closed yet") + (
                f"; {ob['pending']} open" if ob["pending"] else "")
            tl.append(("His options trades, on the market", ob["value"], ob["value"] / berlin_calls.CAPITAL - 1, note, None))
        for info in (i for i in berlin.STRATEGIES.values() if i["kind"] == "series"):
            trades, n, ours, _ = series_numbers(info, tg)
            tl.append(("Small-capital series", pa.CAPITAL + ours, ours / pa.CAPITAL,
                       f"{n} of 10 trades closed, Rs 10,000 risk each", None))
    out = {"home": [("Nifty 50 agents and Claude", nifty),
                    ("Gold and multi-asset", keyed(board_rows(ares, [n for n in asset_arena.AGENTS
                                                                     if n not in berlin.STRATEGIES]))),
                    ("F&amp;O (3x leverage)", keyed(board_rows(fres)))],
           "berlin": [("His strategies and calls", tl)]}
    for ch, sm in sigs or ():
        if sm is None:
            continue
        b = sm["book"]
        done = b["wins"] + b["losses"]
        note = (f"{done} signal{'s' if done != 1 else ''} closed, {b['wins']} won" if done else
                "No signals closed yet") + (f"; {b['pending']} open" if b["pending"] else "")
        row = (("His signals", b["value"], b["value"] / berlin_calls.CAPITAL - 1, note, None) if len(sm["calls"]) else
               ("His signals", None, None, f"Saving posts since {day(pd.Timestamp(ch['since']))}; no signals yet", None))
        out[slug(ch)] = [("His signals, paper traded", [row])]
    return out


def board_section(groups, view, intro, heading="Every strategy", checks=None, home=False):
    """One scoreboard: each strategy's value and change, with its confidence score and what buy-and-hold
    Nifty made over the same days, and what the score means. checks: {label: words} to show under a book
    of calls, which has no confidence score."""
    if not any(items for _, items in groups):
        return ""
    began = started_values(view)
    nifty = began.get(NIFTY_HOLD)
    rows, scored = [], False
    for title, items in groups:
        if not items:
            continue
        rows.append(f"<tbody><tr class='grp'><td colspan='3'>{title}</td></tr></tbody>")
        for label, value, since, note, key in items:
            val = inr(value) if value is not None else "–"
            chg = f"<span class='{tone(since)}'>{pct(since, True, 2)}</span>" if since is not None else ""
            more_ = ""
            if key and value is not None and len(began.get(key, ())):
                score, why = confidence(began[key], nifty)
                over = nifty_over(nifty, began[key]) if key != NIFTY_HOLD else None
                more_ = f"Confidence {score} of 5: {esc(why)}" + (
                    f"<span class='n'> · Nifty {pct(over, True, 2)}</span>" if over is not None else "")
                scored = True
            elif not key and value is not None and checks and checks.get(label):
                more_ = esc(checks[label])
            rows.append(f"<tbody class='row'><tr class='main'><td class='name'>{esc(label)}</td>"
                        f"<td class='r num-big'>{val}</td><td class='r'>{chg}</td></tr>"
                        f"<tr class='more'><td colspan='3'><div><span class='sub'>{esc(note)}</span>"
                        f"<span class='sub'>{more_}</span></div></td></tr></tbody>")
    about = ""
    if scored:
        levels = "; ".join(f"<b>{i}</b>, {esc(text)}" for i, text in enumerate(CONFIDENCE_LEVELS))
        about = (f"<details class='mini'><summary>What the confidence score means</summary><p class='meta'>How much "
                 f"evidence there is that a strategy’s result isn’t luck, from 0 to 5, by rules set on 11 Nov 2026: "
                 f"{levels}. A high return alone never raises it, and it says nothing about the future. With "
                 f"this many strategies one can pass by luck, so a pass has to keep passing. “Nifty” beside a "
                 f"score is what buy-and-hold Nifty made over the same days. The luck test itself is "
                 f"{'' if home else 'on the Home page, '}under “Skill or luck?” in Details.</p></details>")
    return (f"<section class='scoreboard' aria-labelledby='sb-h'><h2 id='sb-h'>{heading}</h2>"
            f"<p class='meta'>{intro}</p><div class='scroll'><table><thead><tr><th>Strategy</th>"
            f"<th class='r'>Worth now</th><th class='r'>Change</th></tr></thead>{''.join(rows)}"
            f"</table></div>{about}</section>")


def overview_html(res, fres, ares, tg, sigs=(), view=None):
    """The home page's board: every agent, the quickest answer to "is it making money?". The Telegram
    channels have boards on their own pages."""
    names = (["<a href='berlin.html'>Trade Like Berlin</a>"]
             + [f"<a href='{slug(ch)}.html'>{esc(ch['name'])}</a>" for ch, _ in sigs or ()])
    intro = (f"Each started with {inr(pa.CAPITAL)} of virtual money on its own start date"
             + (" (the whole-lot F&amp;O agents run on ₹5 lakh and are shown per ₹1 lakh). " if TWINS else ". ")
             + f"{' and '.join(names)} {'have pages' if len(names) > 1 else 'has a page'} of "
             f"{'their' if len(names) > 1 else 'its'} own. A high value here is not proof of skill: see each "
             f"strategy’s confidence score.")
    return board_section(score_groups(res, fres, ares, tg, sigs)["home"], view, intro, home=True)


INDIA_NOTES = {
    "NIFTY": "scored on the Nifty 50 index itself; from India that is NIFTYBEES (an ETF: his Nifty calls are copied onto it below) or Nifty futures (lots of 65, margin)",
    "GOLD": "scored on COMEX gold futures (GC=F); from India the nearest instrument is MCX gold, a different contract in rupees",
    "CRUDE": "scored on NYMEX WTI futures (CL=F); from India the nearest instrument is MCX crude oil",
    "BTC": "scored on BTC-USD; from India that is an Indian exchange, with 30% tax on gains and 1% TDS per trade",
    "XAUUSD": "scored on spot gold at an offshore CFD broker; from India the nearest instrument is MCX gold",
    "XAGUSD": "spot silver at an offshore CFD broker; from India, MCX silver",
    "NAS100": "an index CFD at an offshore broker; not tradable from India",
    "US30": "an index CFD at an offshore broker; not tradable from India",
    "SPX500": "an index CFD at an offshore broker; not tradable from India",
    "BTCUSD": "Bitcoin at an offshore CFD broker; from India that is an Indian exchange, with 30% tax and 1% TDS",
    "ETHUSD": "Ether at an offshore CFD broker; from India that is an Indian exchange, with 30% tax and 1% TDS",
    "USOIL": "oil at an offshore CFD broker; from India, MCX crude oil",
}


def india_note_html(instruments):
    """Where each market a channel trades is scored, and what it would be from India. Currency pairs are
    offshore forex, which isn't permitted for Indian residents."""
    seen, parts = [], []
    for sym in instruments:
        sym = str(sym)
        if sym in seen or not sym:
            continue
        seen.append(sym)
        if sym in INDIA_NOTES:
            parts.append(f"<b>{esc(market_name(sym))}</b>: {esc(INDIA_NOTES[sym])}")
        elif len(sym) == 6 and sym.isalpha():
            parts.append(f"<b>{esc(market_name(sym))}</b>: offshore forex, not permitted for Indian residents")
    if not parts:
        return ""
    return ("<details class='mini'><summary>Where these are scored, and what they would be from India</summary>"
            "<p class='meta'>Scores answer whether the calls have an edge on the market he quotes. From India the "
            "same trade would use a different instrument, with its own prices, lots, margin and tax, so the numbers "
            "here are not what following him from India would make. " + "; ".join(parts) + ".</p></details>")


def luck_html(view):
    """Each agent's daily returns over cash, tested for luck (scorecard.agent_luck). Written down on 5 Nov 2026."""
    if not view:
        return ""
    rows, n_agents = [], 0
    began = started_values(view)                  # the flat days before an agent began don't count as days run
    for block in view:
        for agent in block["values"].columns:
            n_agents += 1
            lk = scorecard.agent_luck(began.get(agent, block["values"][agent]), pa.CASH_DAILY)
            if not lk:
                rows.append((agent, "–", "–", "not enough days yet"))
                continue
            verdict = ("passes" if beats_luck(lk) else
                       "fails: no better than luck" if lk["enough"] else f"needs {scorecard.MIN_DAYS} days ({lk['days']} so far)")
            excess = 0.0 if abs(lk["excess"]) < 1e-7 else lk["excess"]      # under a paisa in Rs 1 lakh is rounding, not a result
            rows.append((agent, pct(excess, True), f"{lk['p']:.2f}" if lk["p"] is not None else "–", verdict))
    body = "".join(f"<tr><td class='agent'>{esc(a)}</td><td class='r'>{e}</td><td class='r'>{p}</td><td>{esc(v)}</td></tr>"
                   for a, e, p, v in rows)
    return (f"<section aria-labelledby='luck-h'><h2 id='luck-h'>Skill or luck?</h2>"
            f"<p>{n_agents} strategies are running. With that many, the best one will look good by chance: twenty "
            f"strategies with no edge at Nifty-like volatility show a best-of-twenty return of about +35% in a "
            f"typical year. So no strategy is judged by being the best of the lot. Each is tested on its own daily "
            f"returns over cash, one-sided, after at least {scorecard.MIN_DAYS} trading days: it passes if a strategy "
            f"with no edge would do this well less than one time in twenty. The test and its bar were written down "
            f"on 5 Nov 2026 and don't change. Passing once isn't proof either; it has to keep passing.</p>"
            f"<div class='panel scroll'><table><thead><tr><th>Strategy</th><th class='r'>Over cash</th>"
            f"<th class='r'>Chance it's luck</th><th>Verdict</th></tr></thead><tbody>{body}</tbody></table></div>"
            f"</section>")


def claude_latest_html(res):
    log = res.get("claude_log") or []
    if not log:
        return ""
    d = log[0]
    conds = ""
    if d.get("go_to_cash_if"):
        conds += f"<li>Goes to cash if {esc(d['go_to_cash_if'].rstrip('.'))}.</li>"
    if d.get("go_fully_in_if"):
        conds += f"<li>Goes fully in if {esc(d['go_fully_in_if'].rstrip('.'))}.</li>"
    return (f"<section aria-labelledby='cl-h'><h2 id='cl-h'>Claude’s latest call</h2>"
            f"<article class='decision'><h3>{day(pd.Timestamp(d['date']))}: {float(d['position']):.0%} in Nifty 50"
            f"</h3><p>{esc(d.get('summary', ''))}</p><ul>{conds}</ul></article></section>")


# --------------------------------- market events ----------------------------------
KIND_NAMES = {"central_bank": "Central bank", "data": "Economic data", "election": "Election", "budget": "Budget",
              "policy": "Policy", "geopolitics": "Geopolitics", "oil": "Oil", "earnings": "Earnings",
              "holiday": "Market holiday", "session": "Special session", "other": "Other"}


def event_when(t, timed=True, end=""):
    t = pd.Timestamp(t).tz_convert(events.IST)
    return f"{t:%a} {t.day} {t:%b}" + (f", {t:%H:%M}" if timed else "") + (f"\u2013{end}" if timed and end else "")


def move_cell(v):
    return "<td class='r'>\u2013</td>" if v is None else f"<td class='r {tone(v)}'>{pct(v, True)}</td>"


def events_html(now=None):
    """What's scheduled and what moved the market, from data/events (events.py)."""
    if events is None or not (os.path.exists(events.CALENDAR) or os.path.exists(events.LOG)):
        return ""
    try:
        now = now or pd.Timestamp.now(tz="UTC")
        up = events.upcoming(now, 14)
        rec = events.recent(now, 45).iloc[::-1]
        moves = [events.reaction(t) for t in rec["at"]]
    except Exception as exc:  # the page still builds without this section
        print(f"  ! Market events skipped: {exc}")
        return ""
    if len(up):
        rows = "".join(
            f"<tr><td class='ev-when'>{esc(event_when(r['at'], bool(r['time_ist']), r['end_ist']))}</td><td class='ev-what'>{esc(r['event'])}</td>"
            f"<td>{esc(KIND_NAMES.get(r['kind'], r['kind']))}"
            f"{', ' + esc(r['market'] or r['country']) if r['market'] or r['country'] else ''}</td></tr>"
            for _, r in up.iterrows())
        coming = (f"<div class='panel scroll'><table><thead><tr><th>When (IST)</th><th>Event</th><th>Kind</th></tr>"
                  f"</thead><tbody>{rows}</tbody></table></div>")
    else:
        coming = "<p class='meta'>Nothing scheduled in the next 14 days.</p>"
    if len(rec):
        rows = ""
        for (_, r), m in zip(rec.iterrows(), moves):
            link = (f"<a href='{esc(r['source'])}'>{esc(r['headline'])}</a>" if r["source"].startswith("http")
                    else esc(r["headline"]))
            detail = f"<br><span class='meta'>{esc(r['detail'])}</span>" if r["detail"] else ""
            rows += (f"<tr><td class='ev-when'>{esc(event_when(r['at']))}</td><td class='ev-what'>{link}{detail}</td>"
                     + "".join(move_cell(m.get(k)) for k in ("Nifty 50", events.NIFTY3, "Gold", "Brent",
                                                              "USD/INR", "S&P 500")) + "</tr>")
        happened = (f"<div class='panel scroll'><table><thead><tr><th>Became public (IST)</th><th>What happened</th>"
                    f"<th class='r'>Nifty, next close</th><th class='r'>Nifty, 3 closes</th><th class='r'>Gold</th>"
                    f"<th class='r'>Brent</th><th class='r'>USD/INR</th><th class='r'>S&amp;P 500</th></tr></thead>"
                    f"<tbody>{rows}</tbody></table></div>"
                    "<p class='meta'>Each move runs from that market's last close before the news became public to its "
                    "first close after it, so other news on the same day is mixed in: one event proves little, many of "
                    "the same kind show a pattern. USD/INR going up means a weaker rupee.</p>")
    else:
        happened = "<p class='meta'>Nothing logged in the last 45 days.</p>"
    return ("<section aria-labelledby='ev-h'><h2 id='ev-h'>Market events</h2>"
            "<p class='meta'>Scheduled events, and what happened with the time it first became public. Claude adds "
            "them every weekday night; rows are only ever added. The Claude agent sees them before deciding.</p>"
            f"<h3 class='sub-h'>Coming up</h3>{coming}<h3 class='sub-h'>What moved the market</h3>{happened}</section>")


def more(title, hint, inner, solo=False):
    if not inner:
        return ""
    return (f"<details class='more{' solo' if solo else ''}'><summary>{title}<span class='hint'>{hint}</span>"
            f"</summary>{inner}</details>")


# ------------------------------- Trade Like Berlin --------------------------------
CORRECTIONS = os.path.join("data", "berlin", "call_corrections.csv")


def read_corrections(path=CORRECTIONS):
    """Notes on calls we tagged wrongly, from data/<channel>/call_corrections.csv (id, added, source, note).
    The file is only ever added to. A correction never changes a score: the call keeps the result it was
    tagged with, and the note says what his actual levels would have given and where they come from."""
    if not os.path.exists(path):
        return {}
    out = {}
    for _, r in pd.read_csv(path, dtype=str, keep_default_na=False).iterrows():
        out.setdefault(str(r["id"]), []).append(r)
    return out


def correction_lines(fixes):
    return "".join(
        f"<span class='tl-fix'><strong>Correction, {day(pd.Timestamp(f['added']))}:</strong> {esc(f['note'])}"
        + (f" <a href='{esc(f['source'])}'>Source</a>" if f["source"].startswith("http") else "") + "</span>"
        for f in fixes)


def money(x):
    return f"{'+' if x >= 0 else '−'}₹{abs(x):,.0f}"


def deleted_line(cid, deleted):
    """A call he deleted from the channel after we saved it."""
    if deleted is None or not len(deleted):
        return ""
    hit = deleted[deleted["id"].astype(str) == str(cid)]
    if not len(hit):
        return ""
    return (f"<span class='tl-fix'><strong>He deleted this post</strong> after it was saved here (noticed "
            f"{ist(hit['noticed_at'].iloc[0])} IST). It stays in the record.</span>")


def update_lines(ups):
    """His later posts about one call: claims, with whether the record agrees, and exits or stop moves."""
    out = []
    if ups is None or not len(ups):
        return ""
    for _, u in ups.sort_values("posted_at").iterrows():
        when = ist(u["posted_at"])
        if u["action"] == "claim":
            tag = {"matches": "<strong class='up'>matches the record</strong>",
                   "doesn't match": "<strong class='down'>doesn’t match the record</strong>"}.get(u.get("verdict", ""), "")
            out.append(f"<span class='tl-claim'>He said, {when}: {esc(u['note'])}" + (f" · {tag}" if tag else "") + "</span>")
        elif u["action"] == "exit":
            out.append(f"<span class='tl-claim'>His exit post, {when}, ends the trade: {esc(u['note'])}</span>")
        elif u["action"] == "target":
            out.append(f"<span class='tl-claim'>Target moved to {esc(u['price'])}, {when}: {esc(u['note'])}</span>")
        else:
            to = "the entry" if str(u.get("price", "")) in ("", "entry") else esc(u["price"])
            once = (f" once the price reaches {level(u['trigger']) if re.fullmatch(r'[0-9.]+', str(u['trigger'])) else esc(u['trigger'])}"
                    if u["action"] == "stop_when" and u.get("trigger") else "")
            out.append(f"<span class='tl-claim'>Stop to {to}{once}, {when}: {esc(u['note'])}</span>")
    return "".join(out)


def scorecard_html(sc, what):
    marks = {True: ("ok", "✓"), False: ("no", "✗"), None: ("wait", "·")}
    items = "".join(f"<li class='{marks[ok][0]}'><span class='mark'>{marks[ok][1]}</span>{esc(label)}: "
                    f"<span class='meta'>{esc(detail)}</span></li>" for label, ok, detail in sc["rows"])
    started = any(ok is not None for _, ok, _ in sc["rows"][:-1]) or sc["rows"][-1][1] is False
    return (f"<div class='checks'><p class='verdict'><strong>Worth following {esc(what)}?</strong> {esc(sc['verdict'])}"
            f"</p>" + (f"<ul class='checklist'>{items}</ul>" if started else "") +
            f"<p class='meta'>The same {len(sc['rows'])} checks for every channel, written down on 4 Nov 2026 and "
            f"never changed"
            + ("" if started else ": enough calls, profit after costs, in both halves, not two lucky calls, a "
               "15-minute delay, his direction, how many calls can be checked, his claims against the record, "
               "whether the profit could be luck, and whether his calls stay up")
            + ".</p></div>")


def call_line(call, res, waiting=None):
    """One Telegram call for the page: what he said and what paper trading it did."""
    note = esc(call["note"])
    if call["scorable"] != "yes":
        under = res[(res["id"].astype(str) == str(call["id"])) & (res["leg"] == "underlying")] if len(res) else res
        if len(under):
            pnl = pd.to_numeric(under["pnl_rs"]).sum()
            return (f"{note} <span class='meta'>Option premiums can’t be scored; on the market itself:</span> "
                    f"<strong class='{tone(pnl)}'>{money(pnl)}</strong> <span class='meta'>({esc(under['outcome'].iloc[0])})"
                    f"</span>")
        if berlin_calls.option_on_underlying(call):
            return f"{note} <span class='meta'>Options trade: on the market itself it’s open, or waiting for prices.</span>"
        return f"{note} <span class='meta'>Not scored.</span>"
    mine = res[res["id"].astype(str) == str(call["id"])] if len(res) else res
    if not len(mine):
        if waiting and str(call["id"]) in waiting:
            return f"{note} <span class='meta'>Finished; waiting for Claude to review his later posts before scoring.</span>"
        return f"{note} <span class='meta'>Open, or waiting for its prices.</span>"
    if (mine["outcome"] == "not filled").all():
        return f"{note} <span class='meta'>Never triggered.</span>"
    pnl = pd.to_numeric(mine["pnl_rs"]).sum()
    legs = ", ".join(f"{r['leg']} {r['side']} {r['outcome']}" if call["kind"] == "event" else r["outcome"]
                     for _, r in mine.iterrows())
    return f"{note} <strong class='{tone(pnl)}'>{money(pnl)}</strong> <span class='meta'>({esc(legs)})</span>"


ETF_NO_TRADE = {"not filled": "His level never triggered on NIFTYBEES.",
                "after 3:10 pm": "Posted after 3:10 pm: too late for an intraday trade.",
                "short can't be held overnight": "A short can't be held overnight in NIFTYBEES, so it isn't copied.",
                "no saved prices": "No NIFTYBEES prices were saved for that day.",
                "too small": "Too small to buy one unit."}


def etf_html(etf, calls):
    """His Nifty calls copied onto NIFTYBEES at Zerodha's charges (berlin_etf.py)."""
    if not etf or (not etf["books"] and not etf["waiting"]):
        return ""
    head = "<h3>The same Nifty calls on NIFTYBEES</h3>"
    intro = ("Nobody can buy the Nifty index itself. With a small account the nearest thing is NIFTYBEES, an ETF "
             "that tracks it, bought or sold short for the day at Zerodha.")
    waiting = (f"<p class='meta'>{len(etf['waiting'])} scored call{'s' if len(etf['waiting']) != 1 else ''} "
               f"wait{'' if len(etf['waiting']) != 1 else 's'} for NIFTYBEES prices.</p>" if etf["waiting"] else "")
    if not etf["books"]:
        return head + f"<p>{intro}</p>" + waiting
    rows, when = etf["rows"], {}
    if len(calls):
        when = dict(zip(calls["id"].astype(str), calls["posted_at"]))
    b, parts = etf["books"].get("calls"), []
    if b and b["ontime"]["n"]:
        o = b["ontime"]
        parts.append(
            f"<p>{intro} His {b['copied']} Nifty calls with levels, copied that way with {inr(etf['position'])} a "
            f"call: {o['n']} traded and {o['wins']} won, for <strong class='{tone(o['net'])}'>{money(o['net'])}"
            f"</strong> after costs. The price moves alone came to {money(o['move'])}; the spread and slippage "
            f"took ₹{o['slip']:,.0f} and Zerodha’s charges ₹{o['charges']:,.0f}. Acting 15 minutes late: "
            f"{money(b['late15']['net'])}; 30 minutes late: {money(b['late30']['net'])}.</p>")
        if o["risk"] > 0:
            on_index, on_etf = minus(format(b["index_r"], "+.1f")), minus(format(o["r"], "+.1f"))
            parts.append(
                f"<p class='meta'>Costs came to {pct((o['slip'] + o['charges']) / o['risk'], digits=0)} of the money "
                f"these trades risked to their stops, before the price had moved at all. In units of that risk (R), "
                f"the same calls made {on_index}R on the index, where the record charges 0.03% a side, and "
                f"{on_etf}R on NIFTYBEES.</p>")
    elif b:
        parts.append(f"<p>{intro} None of his {b['copied']} Nifty calls with levels has traded on it yet.</p>")
    else:
        parts.append(f"<p>{intro}</p>")
    ob = etf["books"].get("options")
    if ob and ob["ontime"]["n"]:
        o = ob["ontime"]
        parts.append(f"<p class='meta'>His options trades, copied as plain NIFTYBEES trades in his direction: "
                     f"<strong class='{tone(o['net'])}'>{money(o['net'])}</strong> from {o['n']}, {o['wins']} won.</p>")
    items = []
    ontime = rows[rows["variant"] == "ontime"].copy()
    ontime["posted"] = ontime["id"].astype(str).map(when)
    for _, r in ontime.sort_values("posted", ascending=False).iterrows():
        mine = rows[rows["id"] == r["id"]]
        label = (f"{ist(r['posted'])} IST · " if isinstance(r["posted"], str) else "") + (
            "sell short" if r["side"] == "short" else "buy") + (" · his options trade" if r["book"] == "options" else "")
        if r["units"] > 0:
            late = "; ".join(f"{v[4:]} minutes late {money(x['pnl_rs'])}" if x["units"] > 0 else f"{v[4:]} minutes late: no trade"
                             for v in ("late15", "late30") for _, x in mine[mine["variant"] == v].iterrows())
            how_out = ("closed at 3:10 pm" if r["outcome"] == "time" and r["product"] == "MIS" else
                       "window ended" if r["outcome"] == "time" else r["outcome"])
            what = (f"{int(r['units'])} units in at ₹{r['fill']:,.2f}, out at ₹{float(r['exit']):,.2f} "
                    f"({esc(how_out)}): move {money(r['move_rs'])}, costs ₹{r['slip_rs'] + r['charges_rs']:,.0f}, "
                    f"<strong class='{tone(r['pnl_rs'])}'>{money(r['pnl_rs'])}</strong>."
                    + (f" <span class='meta'>{late[0].upper() + late[1:]}.</span>" if late else ""))
        else:
            what = f"<span class='meta'>{esc(ETF_NO_TRADE.get(r['outcome'], r['outcome']))}</span>"
        items.append(f"<li><span class='meta'>{label}</span><span class='tl-what'>{what}</span></li>")
    detail = (f"<details class='mini'><summary>Each call on NIFTYBEES ({len(items)})</summary>"
              f"<ul class='panel tlist calls'>{''.join(items)}</ul></details>" if items else "")
    how = (f"<p class='meta'>How it’s copied: his Nifty levels become NIFTYBEES prices at the ratio of the two when "
           f"he posts, and the stop and target then sit on NIFTYBEES’s own price. That price wanders a few "
           f"hundredths of a percent around Nifty during the day, so a level can trigger on one and not on the "
           f"other. Intraday trades are closed at 3:10 pm. Every fill except a target loses "
           f"{etf['slip']:.3%} to the spread, and the charges are <a href='{esc(zerodha_source())}'>Zerodha’s</a> "
           f"for an intraday trade. A call is copied once the record has scored it and is never redone. "
           f"Someone watching Nifty and trading by hand would get different entries and exits.</p>")
    return head + "".join(parts) + waiting + detail + how


def zerodha_source():
    try:
        import zerodha
        return zerodha.SOURCE
    except Exception:
        return "https://zerodha.com/charges/"


def telegram_html(tg):
    if not tg:
        return "<p class='meta'>The Telegram record couldn’t be read tonight.</p>"
    calls, res = tg["calls"], tg["results"]
    b = tg["books"]["calls"]
    fixes = read_corrections()
    ups, waiting, deleted = tg.get("updates"), tg.get("waiting", {}), tg.get("deleted")
    def li(c):
        mine = ups[ups["call_id"].astype(str) == str(c["id"])] if ups is not None and len(ups) else None
        return (f"<li><span class='meta'>{ist(c['posted_at'])} IST · {esc(c['instrument'])}</span>"
                f"<span class='tl-what'>{call_line(c, res, waiting)}</span>{update_lines(mine)}"
                f"{deleted_line(c['id'], deleted)}{correction_lines(fixes.get(str(c['id']), []))}</li>")
    ordered = [c for _, c in calls.sort_values("posted_at", ascending=False).iterrows()] if len(calls) else []
    items = [li(c) for c in ordered[:6]]
    older = "".join(li(c) for c in ordered[6:])
    scored = int((calls["scorable"] == "yes").sum()) if len(calls) else 0
    names = {"NIFTY": "Nifty", "GOLD": "gold", "BTC": "Bitcoin", "CRUDE": "crude oil"}
    traded = set(calls.loc[(calls["kind"] == "level") & (calls["scorable"] == "yes"), "instrument"]) if len(calls) else set()
    markets = [names[k] for k in names if k in traded] + sorted(traded - set(names))
    book = (", ".join(markets[:-1]) + " and " + markets[-1] if len(markets) > 1 else "".join(markets)) or "market"
    sc = scorecard.berlin_checks(tg)
    ob = tg["books"].get("options")
    options = (f"<p class='meta'>Options trades, scored on the market they’re on (in at the next 5-minute bar, the "
               f"usual default stop, out at his exit or the window’s end), kept apart from the calls above: "
               f"<strong>{inr(ob['value'])}</strong> from {ob['wins'] + ob['losses']} closed"
               + (f", {ob['pending']} open" if ob["pending"] else "") + ".</p>") if ob and ob["scored"] + ob["pending"] else ""
    return (f"<h3>His Telegram calls, paper traded</h3>"
            f"<p>Every post on <a href='{berlin.TELEGRAM}'>his Telegram channel</a> since "
            f"{day(pd.Timestamp(berlin.TELEGRAM_FROM))} is saved within about half an hour ({tg['posts']} so far"
            + (f", {tg['changed']} changed after saving" if tg["changed"] else "")
            + (f", {len(tg['deleted'])} deleted by him later" if tg.get("deleted") is not None and len(tg["deleted"]) else "")
            + "). "
            f"Of {len(calls)} trade calls, {scored} have levels free data can check; each risks ₹1,000. "
            f"{book[0].upper() + book[1:]} calls: <strong>{inr(b['value'])}</strong>, {b['wins']} won and "
            f"{b['losses']} lost" + (f", {b['pending']} still open" if b["pending"] else "") + ".</p>"
            + scorecard_html(sc, "his calls") +
            f"<ul class='panel tlist calls'>{''.join(items)}</ul>"
            + (f"<details class='mini'><summary>Older calls ({len(ordered) - 6})</summary>"
               f"<ul class='panel tlist calls'>{older}</ul></details>" if older else "") + options +
            f"<p class='meta'>Market calls fill at the next 5-minute bar after the post, or when his level breaks. "
            f"A missing stop is added and said so (for example 0.2% for Nifty intraday, 1.5% for gold positional, "
            f"1% for Bitcoin intraday). A call is scored once its window ends: the close for Nifty intraday, "
            f"24 hours for other intraday calls, 14 days for positional ones, or his exit post. Option-premium "
            f"trades and levels drawn only on chart images can’t be scored. Claims made after the move don’t "
            f"count. If we misread a call, a correction is added under it, but its score stays as tagged.</p>"
            + etf_html(tg.get("etf"), calls))


def study_line(st):
    if not st:
        return ""
    call = st.get("call")
    after = (f" On 28 Oct the move was {pct(call['move'], True, 2)} against a {call['bias']} bias: "
             f"{'a hit' if call['hit'] else 'a miss'}." if call else
             f" The 28 Oct decision is checked once the Fed’s weekly rates include it.")
    return (f"In {st['n']} RBNZ decisions since {st['first'].year}, the next move followed the last 5 days "
            f"{pct(st['hit'], digits=0)} of the time (ordinary days {pct(st['control_hit'], digits=0)}), so the "
            f"direction rule is a coin flip. The size claim holds better: decision days moved a median "
            f"{pct(st['median_move'], digits=2)} against {pct(st['control_median'], digits=2)} on other days."
            + after)


def series_numbers(info, tg):
    """(his series trades, how many closed, our rupees at his size, his reported rupees for the closed ones)."""
    trades = dict(info.get("trades", {}))
    if tg and len(tg["calls"]):
        for cid in tg["calls"].loc[tg["calls"]["note"].str.startswith("[series]"), "id"]:
            trades.setdefault(str(cid), None)
    res = tg["results"] if tg else pd.DataFrame()
    done = res[res["id"].astype(str).isin(trades) & (res["outcome"] != "not filled")] if len(res) else res
    ours = float(pd.to_numeric(done["r"]).sum() * info["risk_rs"]) if len(done) else 0.0
    n = done["id"].nunique() if len(done) else 0
    reported = [v for k, v in trades.items() if v is not None and k in set(done["id"].astype(str) if len(done) else [])]
    return trades, n, ours, reported


def series_lines(info, tg):
    """The small-capital series: his trades scored on Nifty at his own size, next to what he reported."""
    trades, n, ours, reported = series_numbers(info, tg)
    sign = "+" if ours >= 0 else "\u2212"
    now = (f"{len(trades)} of his 10 series trades posted so far; {n} closed. Scored on "
           f"Nifty at Rs 10,000 risk each: <strong class='{tone(ours)}'>{sign}\u20b9{abs(ours):,.0f}</strong>"
           + (f" (he reported +\u20b9{sum(reported):,.0f} from his option trades)." if reported else "."))
    result = ("Too early: the claim is about the full 10 trades. At 10% risk a trade, five losses in a row, which "
              "happens in about 1 of 9 runs of 10 trades at 50% accuracy, would cut the account by about 40%.")
    return now, result


def berlin_html(ares, abt, tg, st, heading=True):
    """The channel's strategies: one short card per video, then its Telegram calls. heading=False on its
    own page, where the page's title says it."""
    boards, why, checks = {}, {}, {}
    if ares is not None:
        boards = {n: r for n, r in ares["board"].iterrows()}
        why, checks = ares.get("why", {}), ares.get("checks", {})
    tested = {r["agent"]: r for r in (abt[0] if abt else [])}
    cards = []
    for name, info in berlin.STRATEGIES.items():
        if info["kind"] == "agent":
            r = boards.get(name)
            if r is None:
                now = "Couldn’t be updated tonight."
            elif r["holding"] == "Not started yet":
                now = "Starts paper trading on the next trading day."
            else:
                now = (f"<strong>{inr(r['value'])}</strong> (<span class='{tone(r['since_start'])}'>"
                       f"{pct(r['since_start'], True, 2)}</span> since {day(r['start'])}), holding "
                       f"{esc(r['holding'])}. {esc(why.get(name, ''))}")
            bt_ = tested.get(name)
            past = (f"Backtest {day(bt_['start'])} to {day(bt_['end'])}: {pct(bt_['cagr'], True)} a year against "
                    f"{esc(bt_['bench']).lower()} at {pct(bt_['bench_cagr'], True)}. {esc(bt_.get('check', ''))}"
                    if bt_ else "")
            paper = checks.get(name)
            result = (esc(paper) + " " if paper else "") + past
        elif info["kind"] == "series":
            now, result = series_lines(info, tg)
        else:
            b = tg["books"]["events"] if tg else None
            now = (f"<strong>{inr(b['value'])}</strong> from {b['wins'] + b['losses']} event"
                   f"{'s' if b['wins'] + b['losses'] != 1 else ''} traded so far." if b else "")
            result = study_line(st)
        cards.append(
            f"<article class='decision'><h3>{esc(info['title'])}</h3>"
            f"<p class='meta'>Video: “<a href='{esc(info['url'])}'>{esc(info['video'])}</a>”, "
            f"{day(pd.Timestamp(info['published']))}</p><p>{esc(info['claim'])}</p><dl class='why'>"
            f"<dt>Now</dt><dd>{now}</dd>" + (f"<dt>Does the claim hold?</dt><dd>{result}</dd>" if result else "")
            + f"</dl><details class='mini'><summary>How it’s tested</summary><p class='meta'>{esc(info['changes'])}"
            f"</p></details></article>")
    head = ("<section aria-labelledby='berlin-h'><h2 id='berlin-h'>Trade Like Berlin</h2>" if heading
            else "<section aria-label='Trade Like Berlin'>")
    return (head +
            f"<p>Strategies from the <a href='{berlin.CHANNEL}'>Trade Like Berlin</a> YouTube channel and its "
            f"Telegram calls, all paper traded by fixed rules. Gaps such as a missing stop are filled and stated. "
            f"New video? Send Claude the link.</p>"
            + india_note_html(list(tg["calls"]["instrument"]) if tg and len(tg.get("calls", [])) else [])
            + f"{''.join(cards)}{telegram_html(tg)}</section>")


SIGNAL_MARKETS = {"XAUUSD": "gold", "XAGUSD": "silver", "NAS100": "Nasdaq 100", "US30": "Dow Jones",
                  "SPX500": "S&P 500", "BTCUSD": "Bitcoin", "ETHUSD": "Ether", "USOIL": "US oil"}


def market_name(sym):
    sym = str(sym)
    return SIGNAL_MARKETS.get(sym, sym[:3] + "/" + sym[3:] if len(sym) == 6 and sym.isalpha() else sym)


def level(x):
    v = float(x)
    return f"{int(v):,}" if v == int(v) else format(v, ",")


def signal_text(call):
    """His signal in words, with his levels exactly as posted."""
    side, what = ("Buy" if call["side"] == "long" else "Sell"), market_name(call["instrument"])
    entry = (f"{side} {what} now" if call["entry_type"] == "market" else
             f"{side} {what} at {level(call['entry'])} ({esc(call['entry_type'])} order)")
    aims = [level(t) for t in str(call["target"]).split("|") if t]
    aim = f"target {aims[0]}" if len(aims) == 1 else "targets " + ", ".join(aims[:-1]) + " and " + aims[-1]
    return f"{entry}, stop {level(call['stop'])}, {aim}."


def signal_result(call, res, now, waiting=None):
    mine = res[res["id"].astype(str) == str(call["id"])] if len(res) else res
    if len(mine):
        if (mine["outcome"] == "not filled").all():
            return "<span class='meta'>His price was never reached, so no trade.</span>"
        pnl = pd.to_numeric(mine["pnl_rs"]).sum()
        outcomes = list(dict.fromkeys(mine["outcome"]))       # "stop, stop" reads as "stop"
        return (f"<strong class='{tone(pnl)}'>{money(pnl)}</strong> "
                f"<span class='meta'>({esc(', '.join(outcomes))})</span>")
    if call["scorable"] != "yes":
        return "<span class='meta'>No free one-minute prices for this market, so it isn’t scored.</span>"
    if now < pd.Timestamp(call["posted_at"]) + signal_calls.WINDOW:
        return "<span class='meta'>Open: scored after its 24-hour window ends.</span>"
    if waiting and str(call["id"]) in waiting:
        return "<span class='meta'>Finished; waiting for Claude to review one of his later posts before scoring.</span>"
    return "<span class='meta'>Waiting for prices.</span>"


def price_feed_line():
    """Whether last night's check could read Dukascopy's one-minute prices (channels.check_prices)."""
    try:
        with open(channels.PRICE_CHECK, encoding="utf-8") as f:
            st = json.load(f)
    except Exception:
        return ""
    when = ist(st["checked_at"])
    if st.get("ok"):
        return f"<p class='meta'>Price feed: working (checked {when} IST).</p>"
    return (f"<p class='meta'><strong>Price feed: Dukascopy couldn’t be read</strong> on the last check ({when} IST), "
            f"so finished signals wait for their prices.</p>")


def signal_html(ch, sm, heading=True):
    """One signal channel: what it posted, what paper trading its signals did, and whether its claims hold.
    heading=False on its own page, where the page's title says it."""
    key = re.sub(r"[^a-z0-9]", "", ch["handle"].lower())
    head = (f"<section aria-labelledby='sig-{key}-h'><h2 id='sig-{key}-h'>{esc(ch['name'])}</h2>" if heading
            else f"<section aria-label='{esc(ch['name'])}'>")
    if sm is None:
        return head + "<p class='meta'>This channel’s record couldn’t be read tonight.</p></section>"
    calls, res, b, now = sm["calls"], sm["results"], sm["book"], pd.Timestamp.now(tz="UTC")
    ups = sm["updates"]                                     # claims already checked against the record
    def li(c):
        mine = ups[ups["call_id"].astype(str) == str(c["id"])] if len(ups) else None
        return (f"<li><span class='meta'>{ist(c['posted_at'])} IST · {esc(market_name(c['instrument']))} · "
                f"<a href='{esc(ch['url'])}/{esc(c['id'])}'>his post</a></span><span class='tl-what'>"
                f"{signal_text(c)} {signal_result(c, res, now, sm.get('waiting'))}</span>{update_lines(mine)}"
                f"{deleted_line(c['id'], sm.get('deleted'))}{correction_lines(sm.get('corrections', {}).get(str(c['id']), []))}</li>")
    ordered = [c for _, c in calls.sort_values("posted_at", ascending=False).iterrows()] if len(calls) else []
    counts = calls["instrument"].map(market_name).value_counts() if len(calls) else pd.Series(dtype=int)
    markets = sorted(counts.index, key=lambda m: (-counts[m], m))      # most signalled first
    sc = scorecard.signal_checks(sm)
    done = b["wins"] + b["losses"]
    intro = (f"<p><a href='{esc(ch['url'])}'>{esc(ch['name'])}</a> is a Telegram channel that posts trade signals "
             f"with exact levels. Every post since {day(pd.Timestamp(ch['since']))} is saved within about half an hour "
             f"({sm['posts']} so far" + (f", {sm['promo']} of them ads for his paid group, broker offers or live "
                                         f"streams" if sm["promo"] else "")
             + (f", {len(sm['deleted'])} deleted by him later" if sm.get("deleted") is not None and len(sm["deleted"]) else "")
             + "). "
             f"Code reads the signals by fixed rules, with no judgement calls: "
             + (f"{len(calls)} signal{'s' if len(calls) != 1 else ''} so far, on "
                + (", ".join(markets[:-1]) + " and " + markets[-1] if len(markets) > 1 else markets[0]) if len(calls)
                else "no signals yet") + ". Each risks ₹1,000.</p>"
             + (f"<p class='meta'>{esc(ch['scope'])}</p>" if ch.get("scope") else "")
             + india_note_html(list(calls["instrument"]) if len(calls) else []))
    book = (f"<p>Signals: <strong>{inr(b['value'])}</strong>, {b['wins']} won and {b['losses']} lost"
            + (f", {b['pending']} still open" if b["pending"] else "") + ".</p>") if done or b["pending"] else ""
    items = "".join(li(c) for c in ordered[:6])
    older = "".join(li(c) for c in ordered[6:])
    waiting = []
    if len(sm["review"]):
        n = len(sm["review"])
        waiting.append(f"{n} post{'s' if n != 1 else ''} wait{'' if n != 1 else 's'} for Claude to read: trade posts "
                       f"without a clear stop and target, or instructions that can’t be tied to one signal.")
    if sm["unlinked"]:
        n = sm["unlinked"]
        waiting.append(f"{n} of his “TP done” or “SL hit” posts {'are' if n != 1 else 'is'} about signals never "
                       f"posted here, so {'they' if n != 1 else 'it'} can’t be checked.")
    feed = price_feed_line()
    return (head + intro + book + scorecard_html(sc, "its signals")
            + (f"<ul class='panel tlist calls'>{items}</ul>" if items else "")
            + (f"<details class='mini'><summary>Older signals ({len(ordered) - 6})</summary>"
               f"<ul class='panel tlist calls'>{older}</ul></details>" if older else "")
            + (f"<p class='meta'>{' '.join(waiting)}</p>" if waiting else "") + feed +
            f"<p class='meta'>How it’s scored: one-minute bid and ask prices from Dukascopy. A “now” signal fills at "
            f"the next minute’s price (the ask for a buy, the bid for a sell); limit and stop orders fill when the "
            f"price reaches his level. Each signal risks ₹1,000, split equally over his targets, and is followed "
            f"for 24 hours or until he posts an exit. If one minute touches both his stop and a target, the stop "
            f"counts. “Move to breakeven” puts the stop at the entry from the minute after he posts it. His “TP "
            f"done” and “SL hit” posts are checked against the record, not taken as results. Each signal is also "
            f"tested 15 minutes late and reversed. Trading forex or gold CFDs through offshore brokers isn’t "
            f"permitted for Indian residents, so these signals are only ever paper traded here.</p></section>")


# ----------------------------------- real money -----------------------------------
ORDER_WORDS = {"deposit": "Put in", "withdraw": "Took out", "fee": "Fee", "buy": "Bought", "sell": "Sold"}


def rs(x, signed=False):
    """Rupees to the paisa for the small real account: ₹4,987.30, or +₹12.30 / −₹12.30 when signed."""
    sign = ("+" if x >= 0 else "\u2212") if signed else ("\u2212" if x < 0 else "")
    return f"{sign}\u20b9{abs(x):,.2f}"


def order_text(r):
    """One ledger row in words."""
    a = r["action"]
    if a in ("buy", "sell"):
        unit = "lot" if r["product"] == "MCX" else "unit"
        qty = int(float(r["quantity"]))
        fees, estimate = real_money.order_charges(r)
        return (f"{ORDER_WORDS[a]} {qty} {unit}{'s' if qty != 1 else ''} of {esc(r['symbol'])} at "
                f"\u20b9{float(r['price']):,.2f}" + (" for the day" if r["product"] == "MIS" else "")
                + f" <span class='meta'>charges {rs(fees)}{' (estimated)' if estimate else ''}</span>")
    return f"{ORDER_WORDS[a]} {rs(float(r['amount']))}"


def real_html(rm):
    """The real-money ledger (real_money.py): your own orders at Zerodha next to the paper agent."""
    head = "<section aria-labelledby='real-h'><h2 id='real-h'>Real money</h2>"
    if rm is None:
        return head + "<p class='meta'>The real-money ledger couldn’t be read tonight.</p></section>"
    if not rm["started"]:
        return (head + "<p>No real orders yet: everything else on this page is virtual money. When you place an "
                "order at Zerodha yourself, tell Claude what you bought or sold, how many and at what price. It is "
                "written to <code>data/real/orders.csv</code> and shown here next to the paper agent given the same "
                "money on the same day. The <a href='ticket.html'>order ticket</a> works out the quantity, the "
                "charges and the rule checks before you place an order.</p><p class='meta'>The arena never places "
                "an order. The ledger is public, like everything else in the repository.</p></section>")
    gap = rm["value"] - rm["paper"]
    followed = ", ".join(esc(a) for a in rm["followed"]) or "no paper agent"
    items = [("Put in", rs(rm["put_in"]), ""), ("Worth now", rs(rm["value"]), ""),
             ("Gain or loss", f"{rs(rm['pnl'], True)} ({pct(rm['pnl_pct'], True, 2)})", tone(rm["pnl"])),
             ("Charges paid", rs(rm["charges"]), ""), ("Same money in the paper agent", rs(rm["paper"]), ""),
             ("Real against paper", rs(gap, True), tone(gap))]
    cells = "".join(f"<div><dt>{esc(k)}</dt><dd class='{c}'>{v}</dd></div>" for k, v, c in items)
    body = (f"<p class='meta'>Orders you placed by hand at Zerodha, written down afterwards; the arena never places "
            f"an order. Prices up to the close on {day(rm['priced_to'] if rm['priced_to'] is not None else rm['asof'])}. "
            f"Following: {followed}.</p>"
            f"<dl class='stats'>{cells}</dl>")
    if rm["holdings"]:
        rows = "".join(
            f"<tr><td class='agent'>{esc(h['symbol'])}</td><td class='r'>{h['units']}{' lots' if h['future'] else ''}</td>"
            f"<td class='r'>{h['avg']:,.2f}</td><td class='r'>{h['price']:,.2f}{'' if h['priced'] else '*'}</td>"
            f"<td class='r'>{rs(h['value']) if not h['future'] else '–'}</td>"
            f"<td class='r {tone(h['gain'])}'>{rs(h['gain'], True)}</td></tr>" for h in rm["holdings"])
        body += (f"<h3>Holding now</h3><div class='panel scroll'><table><thead><tr><th>What</th><th class='r'>Units</th>"
                 f"<th class='r'>Average cost</th><th class='r'>Last close</th><th class='r'>Value</th>"
                 f"<th class='r'>Gain or loss</th></tr></thead><tbody>{rows}</tbody></table></div>"
                 f"<p class='meta'>Cash in the account: {rs(rm['cash'])}."
                 + (" * No saved prices: valued at your last trade price." if any(not h["priced"] for h in rm["holdings"]) else "")
                 + "</p>")
    else:
        body += f"<p class='meta'>Holding nothing now. Cash in the account: {rs(rm['cash'])}.</p>"
    ser = rm["series"]
    if len(ser) >= 5:
        draw({"Real account": ser["value"], "Paper agent, same money": ser["paper"], "Money put in": ser["put_in"]},
             "real")
        body += ("<figure>" + picture("real", "Line chart of the real account's value, the paper agent given the "
                                              "same money, and the money put in") + "</figure>")
    orders = [r for _, r in rm["rows"].iloc[::-1].iterrows()]
    li = lambda r: (f"<li><span class='meta'>{day(pd.Timestamp(r['date']))}"
                    + (f" · {esc(r['agent'])}" if r["agent"] else "") + f"</span><span class='tl-what'>{order_text(r)}"
                    + (f" <span class='meta'>{esc(r['note'])}</span>" if r["note"] else "") + "</span></li>")
    body += f"<h3>Ledger</h3><ul class='panel tlist'>{''.join(li(r) for r in orders[:8])}</ul>"
    if len(orders) > 8:
        body += (f"<details class='mini'><summary>Older rows ({len(orders) - 8})</summary><ul class='panel tlist'>"
                 f"{''.join(li(r) for r in orders[8:])}</ul></details>")
    notes = "".join(f"<p class='meta'>{esc(w)}</p>" for w in rm["warnings"])
    how = ("<p class='meta'>The comparison puts each deposit into the paper agent named on it at that day’s close, "
           "and takes withdrawals out the same way. The gap is what real trading costs over the paper model: whole "
           "units, real charges, idle cash, a worse price, an order placed late or not at all. A small account also "
           "pays the fixed ₹15.34 on every sale from the demat account, which the paper model spreads thinner. "
           "Nothing here is advice.</p>")
    return head + body + notes + how + "</section>"


def backtest_html(rows, curves, first, last):
    draw(curves, "backtest", log=True, split=bt.SPLIT, money_axis="lakh")
    split_head = ""
    if bt.SPLIT:
        y = pd.Timestamp(bt.SPLIT).year
        split_head = f"<th class='r'>{first.year}\u2013{str(y - 1)[-2:]}</th><th class='r'>{y}\u2013{str(last.year)[-2:]}</th>"
    body = []
    for name, r in rows.items():
        split_cells = ""
        if bt.SPLIT:
            split_cells = f"<td class='r'>{pct(r['in'])}</td><td class='r'>{pct(r['out'])}</td>"
        body.append(
            f"<tr><td class='agent'>{esc(name)}</td><td class='r'>{pct(r['ret'])}</td>"
            f"<td class='r'>{pct(r['day'], digits=3)}</td><td class='r'>{pct(r['fall'])}</td>"
            f"<td class='r'>{inr(r['final'])}</td>{split_cells}</tr>")
    return (f"<section aria-labelledby='bt-h'><h2 id='bt-h'>How these rules did from {first.year} to now</h2>"
            f"<p>A backtest from {day(first)} to {day(last)} on the Nifty price index (without dividends), after "
            f"{bt.COST_PER_SIDE:.2%} costs per buy or sell, acting at the close the day after each signal. The last "
            f"two columns split the period, to show whether a rule kept working on later years.</p>"
            f"<div class='panel scroll'><table><thead><tr><th>Strategy</th><th class='r'>Return per year</th>"
            f"<th class='r'>Per trading day</th><th class='r'>Worst fall</th><th class='r'>{inr(bt.CAPITAL)} became</th>"
            f"{split_head}</tr></thead><tbody>{''.join(body)}</tbody></table></div>"
            f"<figure>{picture('backtest', 'Growth of one lakh rupees under each strategy since 2010, log scale')}"
            f"<figcaption>Log scale. The dotted line marks the start of the later test years.</figcaption></figure>"
            f"<p class='meta'>Past results don't predict future ones.</p></section>")


# ----------------------------------- the pages -----------------------------------
def slug(ch):
    """A signal channel's page name, from its folder: data/akash -> akash."""
    return re.sub(r"[^a-z0-9]", "", os.path.basename(ch["folder"].rstrip("/")).lower()) or "channel"


def site_pages(sigs=(), has_ticket=False):
    """Every page of the site, in the order of the bar at the top: (key, file, label)."""
    pages = [("home", "index.html", "Home"), ("berlin", "berlin.html", "Berlin")]
    pages += [(slug(ch), f"{slug(ch)}.html", slug(ch).capitalize()) for ch, _ in sigs or ()]
    if has_ticket:
        pages.append(("ticket", "ticket.html", "Ticket"))
    return pages


def nav_html(pages, current):
    """The bar at the top of every page."""
    links = "".join(f"<a href='{file}'" + (" aria-current='page'" if key == current else "") + f">{esc(label)}</a>"
                    for key, file, label in pages)
    return f"<nav class='topnav' aria-label='Pages'>{links}</nav>"


def shell(title, description, nav, header, main, built, live=False):
    """One page: the same head, bar and footer around its own header and content."""
    placed = ("The arena never places an order: the orders in the Real money section were placed by hand."
              if live else "No real orders are placed.")
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)}</title>
<meta name="description" content="{esc(description)}">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Barlow:wght@400;600&family=Barlow+Condensed:wght@500;600;700&display=swap" rel="stylesheet">
<style>{CSS}.visually-hidden{{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap}}</style>
</head>
<body>
<div class="wrap">
{nav}
<header>
{header}
</header>
<main>
{main}
</main>
<footer>
<p>For learning only. Not investment advice. {placed}</p>
<p>Data: free daily index data from <a href="{DATA_URL}">indian-market-historical-data</a>, ETF, gold, silver and S&amp;P 500 prices from Yahoo Finance’s public data, and one-minute forex, gold, index and Bitcoin prices from Dukascopy’s public data feed, all for personal, non-commercial use.</p>
<p>Page built on {day(built)} at {built:%H:%M} IST.</p>
</footer>
</div>
</body>
</html>
"""


RISK_WORDS = {"costs": "charges too big next to the risk", "reward": "target too small after costs",
              "market": "can't be traded from India as posted", "size": "account too small for one unit or lot",
              "session": "outside market hours", "fresh price": "stale price", "price check": "price far from the market",
              "stop": "no stop, or one on the wrong side", "short": "a delivery short", "target": "target already passed",
              "trades today": "three trades already that day", "losses today": "two losses already that day",
              "day loss": "4% already lost that day", "drawdown halt": "the account was halted",
              "kill switch": "the kill switch was on", "repeat": "a repeat order", "order rate": "too many orders a minute",
              "money": "not enough cash", "weight": "it would borrow", "position": "nothing to sell"}


def risk_html(rk):
    """The risk engine (risk_engine.py): every paper order checked as if it were real, and why it was refused."""
    head = "<section aria-labelledby='risk-h'><h2 id='risk-h'>Risk engine</h2>"
    if rk is None:
        return head + "<p class='meta'>The risk engine’s log couldn’t be read tonight, or has no rows yet.</p></section>"
    r, e = rk["rules"], rk["engine"]
    intro = (f"<p>Before an order could ever reach a broker, plain code checks it against limits written down in "
             f"advance, which no AI can talk its way past. The order ticket’s: a {inr(r['account'])} account, at most "
             f"{r['riskPct']:g}% of it at risk on a trade, charges at most {r['maxCostPct']:g}% of that risk, a target "
             f"worth at least {r['minRR']:g} times the stop after costs, at most {r['maxTrades']} trades and "
             f"{r['maxLosses']} losses a day. The engine’s own: no new risk after losing {e['dayLossPct']:g}% in a day, "
             f"a halt once the account is {e['drawdownPct']:g}% below its peak, prices checked for age and typos, no "
             f"repeats. Each night it decides every order the paper strategies would have sent, each strategy in its "
             f"own {inr(r['account'])} account, and logs the decision once. Nothing is sent anywhere.</p>")
    if rk["kill"] is not None:
        kill = (f"<p class='meta'><b>Kill switch: on</b> since {day(rk['kill'].tz_convert(IST))}, "
                f"{rk['kill'].tz_convert(IST):%H:%M} (<code>data/real/HALT</code>). Orders that close a position still "
                f"go through.</p>")
    else:
        kill = ("<p class='meta'><b>Kill switch: off.</b> To stop every new order, add a file named "
                "<code>data/real/HALT</code> with the date and time on its first line; delete it to lift. Orders that "
                "close a position always go through.</p>")
    rows = []
    for x in rk["streams"]:
        why = ("Refused: " + ", ".join(f"{RISK_WORDS.get(k, k)} ({n})" for k, n in x["reasons"][:2])
               if x["reasons"] else "Nothing refused")
        worth = (f"worth {rs(x['value'])}" if x["value"] is not None and x["approved"] else
                 {"trade": "no trade made", "allocation": "nothing bought"}.get(x.get("style"), "can’t be placed"))
        halted = f"<span class='sub2 down'>{esc(x['halted'])}</span>" if x["halted"] else ""
        rows.append(f"<tr><td>{esc(x['name'])}<span class='sub2'>{esc(why)}</span>{halted}</td>"
                    f"<td class='r'>{x['approved']} of {x['orders']}<span class='sub2'>{worth}</span></td></tr>")
    table = ("<table class='risk'><thead><tr><th>Strategy</th><th class='r'>Orders let through</th></tr></thead>"
             "<tbody>" + "".join(rows) + "</tbody></table>")
    skipped = rk.get("skipped") or {}
    fno = [a for a, w in skipped.items() if w.startswith("an F&O agent")]
    other = [f"{esc(a)} ({esc(w)})" for a, w in skipped.items() if not w.startswith("an F&O agent")]
    if fno:
        other.append(f"the {len(fno)} F&amp;O agents (lots and margin a {inr(r['account'])} account doesn’t have)")
    left = f"<p class='meta'>Not checked yet: {'; '.join(other)}.</p>" if other else ""
    note = ("<p class='meta'>“Worth now” is that strategy’s own account at the latest close, with the engine’s "
            "quantities, slippage and Zerodha’s charges. The engine is a rehearsal: the same checks go in front of a "
            "broker only after a strategy passes the luck test (REAL_MONEY.md, go/no-go step 4).</p>")
    return head + intro + kill + table + left + note + "</section>"


def page(res, bt_parts, ctx, fres=None, fbt=None, view=None, ares=None, abt=None, tg=None, st=None, sigs=(),
         rm=None, nav="", built=None, rk=None):
    """The home page: every strategy on one board, Claude's call, market events and the details."""
    built = built or dt.datetime.now(IST)
    live = bool(rm and rm.get("started"))                 # real orders have been written down
    real_note = (" The one exception is the Real money section: orders placed by hand at Zerodha." if live
                 else " Nothing here is real money.")
    real_section = real_html(rm) if real_money is not None else ""
    if res["started"]:
        status = (f"Prices up to the close on {day(res['latest'])}. Day {res['days']} of paper trading, "
                  f"which started on {day(res['s0'])}.")
    else:
        status = (f"Prices up to the close on {day(res['latest'])}. Paper trading starts on "
                  f"{day(pd.Timestamp(pa.START))}.")
    header = f"""<h1>Paper arena</h1>
<p class="lede">Every strategy here trades {inr(pa.CAPITAL)} of virtual money by fixed rules, so you can see which ones actually make money.{real_note}</p>
<p class="meta">{status}</p>"""
    main = f"""{drift_html(view)}
{overview_html(res, fres, ares, tg, sigs, view)}
{real_section if live else ""}
{claude_latest_html(res)}
{events_html()}
<section aria-labelledby='more-h'><h2 id='more-h'>Details</h2>
{more("Nifty 50 agents", "Standings, the market, why each agent holds what it holds, trades",
      board_html(res) + market_html(res, ctx) + why_html(res) + arena_chart_html(res) + trades_html(res))}
{more("Claude’s decisions", "Every decision with its reasons", claude_html(res), solo=True)}
{more("Skill or luck?", "Each strategy’s returns tested against chance", luck_html(view), solo=True)}
{more("Gold and multi-asset arena", "Four ETF agents, their rules and backtests", asset_html(ares, abt), solo=True)}
{more("F&amp;O arena", f"{len(fno_arena.RULES)} futures and options agents, 3x leverage", fno_html(fres, fbt), solo=True)}
{more("Backtest since 2010", "How the Nifty rules did before paper trading", backtest_html(*bt_parts), solo=True)}
{more("Your calls", "Add your own Nifty calls", calls_html(res), solo=True)}
{more("Real money", "Your own orders at Zerodha, once there are any", "" if live else real_section, solo=True)}
{more("Risk engine", "Every paper order checked against limits written down in advance", risk_html(rk) if risk_engine is not None else "", solo=True)}
{more("Permanent record", "The logs and saved data behind this page", logs_html(), solo=True)}
</section>"""
    return shell("Paper arena", "Rule-following agents and Claude trade Nifty with virtual money. For learning only.",
                 nav, header, main, built, live)


def checks_words(sc):
    """A channel's "Worth following?" checks in a line, for its board."""
    passed = sum(1 for _, ok, _ in sc["rows"] if ok is True)
    return f"Worth following? {sc['verdict']} {passed} of {len(sc['rows'])} checks pass so far."


def berlin_page(ares, abt, tg, st, nav="", built=None, live=False, groups=None, view=None):
    """Trade Like Berlin on a page of its own: its board, the videos' strategies, his Telegram calls, the
    NIFTYBEES copy."""
    built = built or dt.datetime.now(IST)
    board = ""
    if groups:
        checks = {}
        try:
            checks["His Telegram calls"] = checks_words(scorecard.berlin_checks(tg)) if tg else ""
        except Exception:
            pass
        board = board_section(groups, view, f"Each started with {inr(pa.CAPITAL)} of virtual money. The two "
                              f"strategies from his videos are agents with daily values; his calls are books "
                              f"that risk ₹1,000 a call.", heading="Where it stands", checks=checks)
    header = ("<h1>Trade Like Berlin</h1><p class='meta'>A YouTube and Telegram channel, paper traded with "
              "virtual money. His posts are saved every half hour and his calls are scored each weekday night.</p>")
    return shell("Trade Like Berlin · Paper arena",
                 "The Trade Like Berlin channel's strategies and Telegram calls, paper traded by fixed rules. "
                 "For learning only.", nav, header, board + berlin_html(ares, abt, tg, st, heading=False), built, live)


def signal_page(ch, sm, nav="", built=None, live=False, groups=None, view=None):
    """One signal channel on a page of its own, with its board."""
    built = built or dt.datetime.now(IST)
    board = ""
    if groups:
        checks = {}
        try:
            checks["His signals"] = checks_words(scorecard.signal_checks(sm)) if sm else ""
        except Exception:
            pass
        board = board_section(groups, view, f"A book of {inr(pa.CAPITAL)} of virtual money that risks ₹1,000 on "
                              f"each signal.", heading="Where it stands", checks=checks)
    header = (f"<h1>{esc(ch['name'])}</h1><p class='meta'>A Telegram signal channel, paper traded with virtual "
              f"money. Its posts are saved every half hour and its signals are scored each night.</p>")
    return shell(f"{ch['name']} · Paper arena",
                 f"{ch['name']}: every signal read by code and paper traded on one-minute prices. For learning only.",
                 nav, header, board + signal_html(ch, sm, heading=False), built, live)


def have_ticket():
    """Whether the order ticket can be built (ticket.py and zerodha.py are there), so the bar links to it only then."""
    try:
        import ticket  # noqa: F401
        return True
    except Exception as exc:
        print(f"  ! Order ticket skipped: {exc}")
        return False


def write(name, text):
    with open(os.path.join(SITE, name), "w", encoding="utf-8") as f:
        f.write(text)


def main():
    os.makedirs(SITE, exist_ok=True)
    res = pa.compute()
    ctx = mc.context()
    bt_parts = backtest_summary()
    fres = logbook.fno_results()
    try:
        fbt = fno_arena.backtest_rows()
    except Exception as exc:  # the page still builds without the F&O backtest
        print(f"  ! F&O backtest skipped: {exc}")
        fbt = None
    ares = logbook.asset_results()
    try:
        abt = asset_arena.backtest_rows(ares["market"] if ares else None)
    except Exception as exc:  # the page still builds without this backtest
        print(f"  ! Gold and multi-asset backtest skipped: {exc}")
        abt = None
    try:
        tg = berlin_calls.summary()
    except Exception as exc:  # the page still builds without the Telegram record
        print(f"  ! Telegram record skipped: {exc}")
        tg = None
    if tg is not None and berlin_etf is not None:
        try:
            tg["etf"] = berlin_etf.summary()
        except Exception as exc:  # the page still builds without the NIFTYBEES copy
            print(f"  ! NIFTYBEES copy skipped: {exc}")
    try:
        st = berlin_study.study(berlin_study.rates(refresh=False))
    except Exception as exc:  # no saved Fed rates yet
        print(f"  ! RBNZ study skipped: {exc}")
        st = None
    sigs = []
    for ch in channels.CHANNELS.values():
        if ch["tagging"] != "parser":
            continue
        try:
            sigs.append((ch, signal_calls.summary(ch)))
        except Exception as exc:  # the page still builds; the section says it couldn't be read
            print(f"  ! {ch['name']} skipped: {exc}")
            sigs.append((ch, None))
    rm = None
    if real_money is not None:
        try:
            rm = real_money.summary()
        except Exception as exc:  # the page still builds; the section says it couldn't be read
            print(f"  ! Real-money ledger skipped: {exc}")
    rk = None
    if risk_engine is not None:
        try:
            rk = risk_engine.summary()
        except Exception as exc:  # the page still builds; the section says it couldn't be read
            print(f"  ! Risk engine skipped: {exc}")
    view = logbook.merged(res, fres, ares)
    built, live = dt.datetime.now(IST), bool(rm and rm.get("started"))
    pages = site_pages(sigs, have_ticket())
    bar = lambda key: nav_html(pages, key)
    write("index.html", page(res, bt_parts, ctx, fres, fbt, view, ares, abt, tg, st, sigs, rm, bar("home"), built, rk))
    boards = score_groups(res, fres, ares, tg, sigs)
    write("berlin.html", berlin_page(ares, abt, tg, st, bar("berlin"), built, live, boards["berlin"], view))
    for ch, sm in sigs:
        write(f"{slug(ch)}.html", signal_page(ch, sm, bar(slug(ch)), built, live, boards.get(slug(ch))))
    if pages[-1][0] == "ticket":
        try:
            import ticket
            write("ticket.html", ticket.page(css=CSS, built=built, nav=bar("ticket")))
        except Exception as exc:  # the other pages never depend on it
            print(f"  ! Order ticket not written: {exc}")
    if view:
        log = pd.concat([b["values"] for b in view], axis=1).round(2)
        log = log.loc[:, ~log.columns.duplicated()]
        log.index.name = "Date"
        log.to_csv(os.path.join(SITE, "paper_arena_log.csv"))
    print(f"Built {SITE}/: " + ", ".join(file for _, file, _ in pages))


if __name__ == "__main__":
    main()

