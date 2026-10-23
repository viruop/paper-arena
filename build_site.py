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
EXTRA = {"light": ["#1F9E9E", "#C2417F", "#5B6FD0", "#6F8F00"],
         "dark": ["#4CC9C9", "#E879AE", "#93A3F0", "#A7C93B"]}
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
        locator = matplotlib.dates.AutoDateLocator()
        ax.xaxis.set_major_locator(locator)
        ax.xaxis.set_major_formatter(matplotlib.dates.ConciseDateFormatter(locator))
        leg = ax.legend(fontsize=8.5, frameon=False, loc="upper center", bbox_to_anchor=(0.5, -0.09),
                        ncol=4, handlelength=1.8)
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
.chip{display:inline-block;background:var(--score);color:#1E2B25;border-radius:999px;padding:.1rem .6rem;
font-weight:600;font-size:.9rem}
.quiet{color:var(--board-muted)}
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
.decision{background:var(--surface);border-left:3px solid var(--board);border-radius:.25rem;padding:.9rem 1rem;margin-top:1rem}
.decision h3{font:600 1.15rem/1.2 "Barlow Condensed","Arial Narrow",system-ui,sans-serif;margin:0 0 .4rem}
.decision ul{margin:.25rem 0 .5rem;padding-left:1.2rem}
.decision p{margin:0 0 .35rem}
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


def market_html(res):
    m = res["market"]
    items = [("Close", f"{m['close']:,.2f}", ""), ("On the day", pct(m["change"], True, 2), tone(m["change"])),
             ("200-day average", f"{m['sma200']:,.0f}", ""), ("50-day average", f"{m['sma50']:,.0f}", ""),
             ("5-day average", f"{m['sma5']:,.0f}", ""), ("RSI(2)", f"{m['rsi2']:.0f}", "")]
    cells = "".join(f"<div><dt>{esc(k)}</dt><dd class='{c}'>{v}</dd></div>" for k, v, c in items)
    return (f"<section aria-labelledby='mkt-h'><h2 id='mkt-h'>Nifty 50 at the latest close</h2>"
            f"<p class='meta'>{day(res['latest'])}</p><dl class='stats'>{cells}</dl></section>")


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


def page(res, bt_parts):
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
<p class="lede">Six rule-following agents and Claude trade Nifty, each with {inr(pa.CAPITAL)} of virtual money. Nothing here is real money.</p>
<p class="meta">{status}</p>
</header>
<main>
{board_html(res)}
{market_html(res)}
{why_html(res)}
{arena_chart_html(res)}
{trades_html(res)}
{claude_html(res)}
{calls_html(res)}
{backtest_html(*bt_parts)}
</main>
<footer>
<p>For learning only. Not investment advice. No real orders are placed.</p>
<p>Data: free daily index data from <a href="{DATA_URL}">indian-market-historical-data</a>, for personal, non-commercial use.</p>
<p>Page built on {day(built)} at {built:%H:%M} IST.</p>
</footer>
</div>
</body>
</html>
"""


def main():
    os.makedirs(SITE, exist_ok=True)
    res = pa.compute()
    bt_parts = backtest_summary()
    with open(os.path.join(SITE, "index.html"), "w", encoding="utf-8") as f:
        f.write(page(res, bt_parts))
    if res["started"]:
        log = res["values"].round(2)
        log.index.name = "Date"
        log.to_csv(os.path.join(SITE, "paper_arena_log.csv"))
    print(f"Built {SITE}/index.html")


if __name__ == "__main__":
    main()
