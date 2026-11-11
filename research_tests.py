"""
research_tests.py - two ideas from other people's trading write-ups, tested before anything is built on them.

Neither is an agent. Each rule was written down here before its result was looked at, each is compared
with doing something simpler, and nothing is tuned afterwards.

1. 52-week-high breakout, on today's Nifty 50 stocks, daily, from 2010.
   Rule: when a stock closes at its highest close of the last 252 sessions, buy it at the next close;
   sell at the close after it closes below its 50-day average. Up to 10 stocks, a tenth of the account
   each, 0.10% a buy or sell, idle cash at 6%. When there are more signals than free places, the stock
   with the larger 252-session gain goes first.
   Compared with: holding all the same stocks in equal parts, the Nifty 50 index, and the same exit
   and places filled with random stocks that are above their 50-day average ("is it the new high that
   matters, or just being in a rising stock?").
   Known flaw: the list is today's Nifty 50, which are the past's winners. That flatters the rule and
   the equal-parts benchmark alike, so only the difference between them means much.

2. Opening-range breakout on Nifty, intraday.
   Rule: the first hour's high and low are the range. The first later hourly bar that trades above the
   high is bought there (below the low: sold there); the stop is the other side of the range; out at
   the close. One trade a day. A bar that breaks both sides counts as a loss of the whole range.
   Compared with: simply buying at 10:15 and selling at the close every day (the market's own drift),
   the same breakouts taken the other way, and long and short breakouts apart.
   Costs: 0.03% a side (futures) and 0.065% a side (NIFTYBEES for the day at a small size).
   Also run on the saved 5-minute prices with a 15-minute range, where there are only a few weeks.

Prices: the free daily stock files the arena already uses for breadth; Yahoo's hourly Nifty bars for
two years (saved to data/research/NSEI_60m.csv the first time); the saved 5-minute bars.

Run:  python research_tests.py
FOR LEARNING ONLY. Not investment advice. No real orders are placed.
"""

import json
import math
import os
import sys
import urllib.request

import numpy as np
import pandas as pd

START = "2010-01-01"
SPLIT = "2018-01-01"          # the result is also shown before and after this date
CAPITAL = 100_000
COST = 0.001                  # a buy or a sell of a stock
CASH_RATE = 0.06
SLOTS = 10
HIGH_DAYS, EXIT_DAYS = 252, 50
BAD_MOVE = -0.30              # a one-day fall beyond this is a demerger or a bad print: ignored for everyone
HOURLY = os.path.join("data", "research", "NSEI_60m.csv")
FIVE_MIN = os.path.join("data", "market", "intraday", "NSEI_5m.csv")
ORB_COSTS = (("futures, 0.03% a side", 0.0003), ("NIFTYBEES for the day, 0.065% a side", 0.00065))
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
                         "Chrome/126.0 Safari/537.36"}


# ------------------------------ 1. 52-week-high breakout ---------------------------
def stock_closes():
    import market_context as mc
    closes = {}
    for sym in mc.nifty50_symbols():
        try:
            closes[sym] = mc.stock_close(sym)
        except Exception as exc:
            print(f"  ! {sym}: no prices ({exc})", file=sys.stderr)
    return pd.DataFrame(closes).sort_index()


def clean_returns(closes):
    """Daily returns, with demergers and bad prints (BAD_MOVE) set to zero. Returns (returns, what was ignored)."""
    r = closes.pct_change(fill_method=None)
    bad = r < BAD_MOVE
    ignored = [(d.date(), s, float(r.at[d, s])) for d, s in bad.stack()[bad.stack()].index]
    return r.mask(bad, 0.0), ignored


def breakout(closes, r, start=START, end=None, cost=COST, delay=1, rng=None, entries=None):
    """The breakout rule (or, with rng and entries, the random control that buys as many stocks each day
    as the rule did). Returns (value by day, finished trades as (days held, return), stocks bought by day)."""
    C, R = closes.to_numpy(float), r.to_numpy(float)
    high = ((closes == closes.rolling(HIGH_DAYS, min_periods=HIGH_DAYS).max()) & closes.notna()).to_numpy()
    below = (closes < closes.rolling(EXIT_DAYS, min_periods=EXIT_DAYS).mean()).to_numpy()
    seasoned = (closes.rolling(HIGH_DAYS, min_periods=HIGH_DAYS).count() >= HIGH_DAYS).to_numpy()
    gain = (closes / closes.shift(HIGH_DAYS) - 1).to_numpy(float)
    index = closes.index
    first = index.searchsorted(pd.Timestamp(start))
    stop = len(index) if end is None else index.searchsorted(pd.Timestamp(end), side="right")
    cash_daily = (1 + CASH_RATE) ** (1 / 252) - 1
    cash, held, opened, value, trades, bought = float(CAPITAL), {}, {}, {}, [], {}
    for i in range(first, stop):
        d = index[i]
        cash *= 1 + cash_daily
        for k in held:
            if R[i, k] == R[i, k]:
                held[k] *= 1 + R[i, k]
        sig = i - delay                                       # yesterday's close decides today's trades
        for k in [k for k in held if below[sig, k]]:
            cash += held[k] * (1 - cost)
            trades.append(((d - opened[k][0]).days, held[k] * (1 - cost) / opened[k][1] - 1))
            del held[k], opened[k]
        free = SLOTS - len(held)
        if entries is None:
            wanted = [k for k in np.flatnonzero(high[sig]) if k not in held and C[i, k] == C[i, k]]
            wanted.sort(key=lambda k: -gain[sig, k])
        else:
            pool = [k for k in np.flatnonzero(seasoned[sig] & ~below[sig]) if k not in held and C[i, k] == C[i, k]]
            wanted = list(rng.permutation(pool))[:entries.get(d, 0)]
        n = 0
        for k in wanted[:max(free, 0)]:
            size = min((cash + sum(held.values())) / SLOTS, cash)
            if size <= 0:
                break
            cash -= size
            held[k] = size * (1 - cost)
            opened[k] = (d, size)
            n += 1
        if n:
            bought[d] = n
        value[d] = cash + sum(held.values())
    return pd.Series(value), trades, bought


def describe(curve, capital=CAPITAL):
    years = (curve.index[-1] - curve.index[0]).days / 365.25
    return {"cagr": (curve.iloc[-1] / capital) ** (1 / years) - 1,
            "dd": float((curve / np.maximum(curve.cummax(), capital) - 1).min()), "end": float(curve.iloc[-1])}


def split_cagr(curve):
    a, b = curve.loc[:SPLIT], curve.loc[SPLIT:]
    grow = lambda s, base: (s.iloc[-1] / base) ** (365.25 / max((s.index[-1] - s.index[0]).days, 1)) - 1
    return grow(a, CAPITAL), grow(b, a.iloc[-1])


def breakout_report(runs=200, seed=7):
    print("\n1. 52-WEEK-HIGH BREAKOUT on today's Nifty 50 stocks")
    closes = stock_closes()
    r, ignored = clean_returns(closes)
    since = [x for x in ignored if str(x[0]) >= START]
    print(f"   {closes.shape[1]} stocks, prices to {closes.index[-1].date()}. Ignored as demergers or bad prints since "
          f"{START[:4]}: " + (", ".join(f"{s} {d} ({m:+.0%})" for d, s, m in since) or "none"))
    curve, trades, bought = breakout(closes, r)
    days = curve.index
    equal = CAPITAL * (1 + r.loc[days].mean(axis=1).fillna(0)).cumprod()
    rows = [("52-week-high breakout", curve), ("All the same stocks, equal parts", equal)]
    try:
        import nifty_backtest as bt
        nifty = bt.load_all()["NIFTY 50"].reindex(days).ffill()
        rows.append(("Nifty 50 index (no dividends)", CAPITAL * nifty / nifty.iloc[0]))
    except Exception as exc:
        print(f"   (Nifty 50 index not loaded: {exc})")
    rows.append(("Cash at 6%", pd.Series(CAPITAL * (1 + CASH_RATE) ** (np.arange(len(days)) / 252), index=days)))
    print(f"   {days[0].date()} to {days[-1].date()}, after 0.10% a side:")
    print(f"   {'':34s} {'a year':>7s} {'worst fall':>10s} {'before ' + SPLIT[:4]:>12s} {'from ' + SPLIT[:4]:>10s}")
    for name, c in rows:
        s, (a, b) = describe(c), split_cagr(c)
        print(f"   {name:34s} {s['cagr']:+7.1%} {s['dd']:10.1%} {a:+12.1%} {b:+10.1%}")
    held = np.array([t[0] for t in trades])
    gains = np.array([t[1] for t in trades])
    years = (days[-1] - days[0]).days / 365.25
    print(f"   {len(trades)} finished trades ({len(trades) / years:.0f} a year), {np.mean(gains > 0):.0%} won, average "
          f"{gains.mean():+.1%} over {held.mean():.0f} days; the best 10 trades made "
          f"{np.sort(gains)[-10:].sum() / gains.sum():.0%} of the total")
    for label, kw in (("at 0.20% a side", {"cost": 0.002}), ("acting the same evening (not possible in practice)", {"delay": 0})):
        c, _, _ = breakout(closes, r, **kw)
        print(f"   {label}: {describe(c)['cagr']:+.1%} a year")
    rng = np.random.default_rng(seed)
    control = np.array([describe(breakout(closes, r, rng=rng, entries=bought)[0])["cagr"] for _ in range(runs)])
    mine = describe(curve)["cagr"]
    beat = float((control >= mine).mean())
    print(f"   Random rising stocks instead of new highs, {runs} runs: {np.median(control):+.1%} a year in the middle "
          f"(from {control.min():+.1%} to {control.max():+.1%}); {beat:.0%} of them did as well as the rule or better")
    edge = mine - describe(equal)["cagr"]
    verdict = ("NOT CONVINCING: random rising stocks do about as well, so the new high adds little" if beat > 0.10 else
               "the new high beats random rising stocks, but check the flaw above before trusting it")
    print(f"   Against holding all the same stocks: {edge:+.1%} a year. Verdict: {verdict}.")
    return {"curve": curve, "equal": equal, "control": control, "trades": trades}


# ------------------------------ 2. opening-range breakout --------------------------
def hourly_bars():
    """Two years of hourly Nifty bars: the saved copy, or Yahoo's (saved for next time)."""
    if os.path.exists(HOURLY):
        df = pd.read_csv(HOURLY, index_col=0)
        df.index = pd.to_datetime(df.index, utc=True)
        return df
    url = "https://query1.finance.yahoo.com/v8/finance/chart/%5ENSEI?range=2y&interval=60m&includePrePost=false"
    with urllib.request.urlopen(urllib.request.Request(url, headers=HEADERS), timeout=60) as resp:
        res = json.load(resp)["chart"]["result"][0]
    q = res["indicators"]["quote"][0]
    idx = pd.to_datetime(res["timestamp"], unit="s", utc=True)
    df = pd.DataFrame({c: pd.to_numeric(pd.Series(q[c.lower()]), errors="coerce").values
                       for c in ("Open", "High", "Low", "Close")}, index=idx).dropna()
    df = df[~df.index.duplicated(keep="last")].sort_index()
    os.makedirs(os.path.dirname(HOURLY), exist_ok=True)
    df.round(5).to_csv(HOURLY, index_label="time")
    return df


def orb_day(bars, range_bars, last=None):
    """One session's trade, before costs: (direction +1/-1, return) or None if the range never broke.
    bars: that day's bars in order. range_bars: how many of the first bars make the range.
    last: stop trading after this many bars (for a 3:10 pm exit); None = to the close."""
    if last is not None:
        bars = bars.iloc[:last]
    if len(bars) <= range_bars:
        return None
    top, bottom = bars["High"].iloc[:range_bars].max(), bars["Low"].iloc[:range_bars].min()
    rest = bars.iloc[range_bars:]
    for i, (_, b) in enumerate(rest.iterrows()):
        up, down = b["High"] > top, b["Low"] < bottom
        if not up and not down:
            continue
        if up and down:                                   # can't tell which came first: a full-range loss
            return 0, -(top - bottom) / top
        sign = 1 if up else -1
        entry = max(top, b["Open"]) if up else min(bottom, b["Open"])
        stop = bottom if up else top
        for _, later in rest.iloc[i + 1:].iterrows():
            if (later["Low"] <= stop) if up else (later["High"] >= stop):
                out = min(stop, later["Open"]) if up else max(stop, later["Open"])
                return sign, sign * (out / entry - 1)
        return sign, sign * (rest["Close"].iloc[-1] / entry - 1)
    return None


def line(name, x):
    x = np.asarray(x, dtype=float)
    if len(x) < 2:
        return f"   {name:44s} too few trades"
    t = x.mean() / (x.std(ddof=1) / math.sqrt(len(x))) if x.std(ddof=1) > 0 else 0.0
    return (f"   {name:44s} {len(x):4d} trades, {np.mean(x > 0):4.0%} won, {x.mean() * 1e4:+6.1f} hundredths of a percent "
            f"each (t {t:+.1f}), {x.sum():+7.1%} in all")


def orb_report(bars, range_bars, title, last=None, drift_from=None):
    local = bars.tz_convert("Asia/Kolkata")
    sessions = [g for _, g in local.groupby(local.index.date) if len(g) > range_bars + 1]
    trades, drift = [], []
    for g in sessions:
        res = orb_day(g, range_bars, last)
        if res:
            trades.append(res)
        day = g.iloc[:last] if last else g
        drift.append(day["Close"].iloc[-1] / day["Open"].iloc[drift_from if drift_from is not None else range_bars] - 1)
    gross, side = np.array([t[1] for t in trades]), np.array([t[0] for t in trades])
    print(f"\n   {title}: {len(sessions)} sessions, {local.index[0].date()} to {local.index[-1].date()}; "
          f"{int((side == 0).sum())} days broke both sides in one bar and count as a loss of the whole range")
    for label, c in ORB_COSTS:
        print(f"   after {label}")
        print(line("  breakout", gross - 2 * c))
        print(line("  long breakouts only", gross[side > 0] - 2 * c))
        print(line("  short breakouts only", gross[side < 0] - 2 * c))
        print(line("  the same breakouts taken the other way", -gross - 2 * c))
        print(line("  just buy after the range, sell at the close", np.array(drift) - 2 * c))
        half = len(gross) // 2
        print(line("  breakout, first half of the period", gross[:half] - 2 * c))
        print(line("  breakout, second half", gross[half:] - 2 * c))
    return gross, side, np.array(drift)


def orb_all():
    print("\n2. OPENING-RANGE BREAKOUT on Nifty")
    out = {}
    try:
        gross, side, drift = orb_report(hourly_bars(), 1, "Hourly bars, range = the first hour")
        out["hourly"] = (gross, side, drift)
        net = gross - 2 * ORB_COSTS[0][1]
        t = net.mean() / (net.std(ddof=1) / math.sqrt(len(net)))
        print("\n   Verdict on the hourly test: " + (
            "NOT CONVINCING: after costs the average trade isn't clearly above zero" if t < 2 else
            "above zero after futures costs in this sample; check both halves and the NIFTYBEES line before trusting it") + ".")
    except Exception as exc:
        print(f"   Hourly bars not available: {exc}")
    try:
        five = pd.read_csv(FIVE_MIN, index_col=0)
        five.index = pd.to_datetime(five.index, utc=True)
        out["five"] = orb_report(five, 3, "5-minute bars, range = the first 15 minutes, out by 3:10 pm", last=71)
        print("   Too few sessions to conclude anything from the 5-minute test: it is a cross-check only.")
    except Exception as exc:
        print(f"   5-minute bars not available: {exc}")
    return out


def main():
    print("Two ideas tested, with rules written down before the results. Neither is an agent or advice.")
    breakout_report()
    orb_all()


if __name__ == "__main__":
    main()
