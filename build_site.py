"""
build_site.py - builds the dashboard web page in the site/ folder from both scripts.

GitHub Actions runs this every weekday evening and publishes site/ with GitHub Pages.
You can also run it yourself (python build_site.py) and open site/index.html in a browser.

FOR LEARNING ONLY. No real orders are placed. Not investment advice.
"""

import datetime as dt
import html
import os

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import matplotlib.dates  # noqa: E402
import matplotlib.ticker  # noqa: E402
import pandas as pd  # noqa: E402

import asset_arena  # noqa: E402
import fno_arena  # noqa: E402
import logbook  # noqa: E402
import market_context as mc  # noqa: E402
import nifty_backtest as bt  # noqa: E402
import paper_arena as pa  # noqa: E402

SITE = "site"
DATA_URL = "https://github.com/aswinv90/indian-market-historical-data"
IST = dt.timezone(dt.timedelta(hours=5, minutes=30))

COLORS = {  # same colour for an agent on every chart; light and dark versions
    "light": {"Cash only": "#8A948F", "Buy & hold": "#2F6FB0", "200-day trend": "#D2572E",
              "Golden cross": "#2E9461", "RSI(2) dip-buy": "#8A5BC2", "Momentum rotation": "#C98A00"},
    "dark": {"Cash only": "#9AA59F", "Buy & hold": "#6EA8E6", "200-day trend": "#F07F55",
             "Golden cross": "#55C48A", "RSI(2) dip-buy": "#B68CF0", "Momentum rotation": "#E5B23A"},
}
EXTRA = {"light": ["#1F9E9E", "#C2417F", "#5B6FD0", "#6F8F00", "#D9622B", "#2F6FB0", "#8A5BC2", "#B8860B"],
         "dark": ["#4CC9C9", "#E879AE", "#93A3F0", "#A7C93B", "#F08A5D", "#6EA8E6", "#B68CF0", "#E5B23A"]}
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
def color_for(name, theme, order):
    known = COLORS[theme]
    if name in known:
        return known[name]
    extras = [n for n in order if n not in known]
    return EXTRA[theme][extras.index(name) % len(EXTRA[theme])]


def draw(series, filename, log=False, split=None, money_axis="plain"):
    names = list(series)
    for theme, c in THEMES.items():
        fig, ax = plt.subplots(figsize=(9, 4.6))
        fig.patch.set_facecolor(c["bg"])
        ax.set_facecolor(c["bg"])
        for name, s in series.items():
            dashed = name == "Cash only"
            ax.plot(s.index, s.values, label=name, color=color_for(name, theme, names),
                    lw=1.1 if dashed else 1.7, ls="--" if dashed else "-")
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
.wrap{max-width:68rem;margin:0 auto;padding:2.5rem 1.25rem 4rem}
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
table{border-collapse:collapse;width:100%;font-variant-numeric:tabular-nums}
th,td{padding:.6rem .55rem;text-align:left;vertical-align:baseline;white-space:nowrap}
th{font-weight:500;color:var(--muted);font-size:.9rem;border-bottom:1px solid var(--rule)}
td{border-bottom:1px solid var(--rule)}
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
@media (max-width:40rem){.wrap{padding-top:1.75rem}th,td{padding:.5rem .45rem}.rank{font-size:1.4rem}
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
        notes.append(f"FII and DII figures are net cash-market buying or selling on {day(f.index[-1])}.")
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
    return (f"<div class='warn' role='status'><strong>The saved log and tonight's replay disagree</strong> on "
            f"{found['rows']} {'row' if found['rows'] == 1 else 'rows'} (largest difference {inr(found['largest'])}, "
            f"for {esc(found['agent'])} on "
            f"{day(found['date'])}). This usually means the data source corrected an old price. The saved log "
            f"stays the official record.</div>")


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
                                                         "and multi-asset agents"),
             ("logs/starts.json", "Start dates", False, "when each newer agent started paper trading"),
             ("logs/journal.md", "Your journal", False, "your evening notes, which you edit on GitHub")]
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
            f"week). Free data has no past option prices, so the backtest estimates them from India VIX; the "
            f"ranges show results at three different estimates, and worst falls use the middle one. The futures "
            f"rows use real index prices. Paper trading above uses NSE’s real prices where it has them.</p>")


def rupee_text(text):
    """Trade notes say "+Rs 1,234" / "-Rs 1,234"; show them with the rupee sign and a true minus."""
    return esc(text).replace("-Rs ", "\u2212\u20b9").replace("+Rs ", "+\u20b9")


def fno_html(fres, fbt):
    head = "<section aria-labelledby='fno-h'><h2 id='fno-h'>F&amp;O arena</h2>"
    intro = (f"<p>Seven futures and options strategies, each with {inr(pa.CAPITAL)} of virtual money. They are kept "
             f"apart from the Nifty agents because they use leverage. In SEBI’s study of FY26, 87.7% of "
             f"individual F&amp;O traders lost money.</p>")
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
        body = (f"<p class='meta'>Started with {inr(pa.CAPITAL)} each on {day(fres['start'])}. {real}</p>"
                f"<div class='board'><div class='scroll'><table><thead><tr><th><span class='visually-hidden'>Rank"
                f"</span>#</th><th>Agent</th><th>Holding now</th><th class='r'>Value</th><th class='r'>Since start"
                f"</th><th class='r'>Worst fall</th><th class='r'>Trades</th><th>Today</th></tr></thead>"
                f"<tbody>{''.join(rows)}</tbody></table></div></div>")
        since = fres["values"].loc[fres["start"]:]
        if len(since) >= 2:
            draw({n: since[n] for n in since.columns}, "fno")
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


def asset_backtest_html(abt):
    if not abt:
        return ""
    rows, sources = abt
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
    head = "<section aria-labelledby='asset-h'><h2 id='asset-h'>Gold and multi-asset arena</h2>"
    intro = (f"<p>Six agents built from research into the Trade Like Berlin YouTube channel and strategies shared "
             f"on Reddit and X, each with {inr(pa.CAPITAL)} of virtual money. They trade NSE ETFs and MCX gold "
             f"futures, which Indian residents can legally use. The two controls test the channel’s own rules; "
             f"the research expects them to lose.</p>")
    if ares is None:
        return head + intro + "<p class='meta'>These agents couldn’t be updated tonight.</p>" + \
            asset_backtest_html(abt) + "</section>"
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
    return head + intro + body + asset_backtest_html(abt) + "</section>"


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


def page(res, bt_parts, ctx, fres=None, fbt=None, view=None, ares=None, abt=None):
    built = dt.datetime.now(IST)
    if res["started"]:
        status = (f"Prices up to the close on {day(res['latest'])}. Day {res['days']} of paper trading, "
                  f"which started on {day(res['s0'])}.")
    else:
        status = (f"Prices up to the close on {day(res['latest'])}. Paper trading starts on "
                  f"{day(pd.Timestamp(pa.START))}.")
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Paper arena</title>
<meta name="description" content="Rule-following agents and Claude trade Nifty with virtual money. For learning only.">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Barlow:wght@400;600&family=Barlow+Condensed:wght@500;600;700&display=swap" rel="stylesheet">
<style>{CSS}.visually-hidden{{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap}}</style>
</head>
<body>
<div class="wrap">
<header>
<h1>Paper arena</h1>
<p class="lede">Six rule-following agents and Claude trade Nifty, each with {inr(pa.CAPITAL)} of virtual money. Seven F&amp;O agents and six gold and multi-asset agents trade in arenas of their own. Nothing here is real money.</p>
<p class="meta">{status}</p>
</header>
<main>
{drift_html(view)}
{board_html(res)}
{market_html(res, ctx)}
{why_html(res)}
{arena_chart_html(res)}
{trades_html(res)}
{claude_html(res)}
{calls_html(res)}
{fno_html(fres, fbt)}
{asset_html(ares, abt)}
{logs_html()}
{backtest_html(*bt_parts)}
</main>
<footer>
<p>For learning only. Not investment advice. No real orders are placed.</p>
<p>Data: free daily index data from <a href="{DATA_URL}">indian-market-historical-data</a>, and ETF, gold, silver and S&amp;P 500 prices from Yahoo Finance’s public data, both for personal, non-commercial use.</p>
<p>Page built on {day(built)} at {built:%H:%M} IST.</p>
</footer>
</div>
</body>
</html>
"""


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
    view = logbook.merged(res, fres, ares)
    with open(os.path.join(SITE, "index.html"), "w", encoding="utf-8") as f:
        f.write(page(res, bt_parts, ctx, fres, fbt, view, ares, abt))
    if view:
        log = pd.concat([b["values"] for b in view], axis=1).round(2)
        log = log.loc[:, ~log.columns.duplicated()]
        log.index.name = "Date"
        log.to_csv(os.path.join(SITE, "paper_arena_log.csv"))
    print(f"Built {SITE}/index.html")


if __name__ == "__main__":
    main()
