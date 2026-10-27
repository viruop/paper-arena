"""
fno_arena.py - the paper arena's F&O agents.

Seven futures and options strategies from fno_backtest.py trade Nifty with virtual money, each
from the start date logs/starts.json gives it (the first trading day after it was added).
Option trades use NSE's real opening and closing prices saved by fno_prices.py, and
estimated prices only for days or contracts NSE's file doesn't cover. Futures trades use the
Nifty 50 index itself. Intraday stop-losses are judged from the day's high and low.

FOR LEARNING ONLY. Not investment advice. No real orders are placed.
"""

import pandas as pd

import fno_backtest as fb
import fno_prices as fp
import paper_arena as pa
import starts

RULES = {
    "Futures trend (long/short)": "Long Nifty futures when Nifty is above its 200-day average, short when "
                                  "below. Exposure 3x capital.",
    "Intraday futures": "Each morning, buy futures if Nifty closed above its 20-day average, else sell. "
                        "Exposure 3x capital, 0.5% stop-loss, out by the close.",
    "Intraday short straddle": "Each morning, sell the at-the-money call and put. Buy back at the close, "
                               "or earlier if they rise 30%. Exposure 3x capital.",
    "Weekly short strangle": "At each expiry, sell a call and a put about 2% away from Nifty and hold to "
                             "the next expiry. Exposure 3x capital.",
    "Weekly iron condor": "Like the strangle, plus protection bought about 4% away to cap the loss.",
    "Weekly option buying": "At each expiry, buy the at-the-money call in an uptrend or the put in a "
                            "downtrend, spending 3% of capital.",
    "Low-VIX long straddle": "When India VIX is in the bottom quarter of its last 60 and 120 sessions, buy one "
                             "lot of the at-the-money call and put (monthly expiry with at least 20 sessions "
                             "left). Sell at 1.5x or 0.5x the cost, or with 5 sessions left.",
}


def first_start():
    """The earliest planned start among the F&O agents, or None if none has one yet."""
    days = [d for d in (starts.start_of(n) for n in RULES) if d is not None]
    return min(days) if days else None


class RealPrices(fb.ModelPrices):
    """NSE's saved daily prices, falling back to the model where a price is missing."""

    def __init__(self):
        self.tables, self.real, self.estimated = {}, 0, 0

    def table(self, day):
        if day not in self.tables:
            df = fp.load(day)
            self.tables[day] = None if df is None else df.set_index(["expiry", "strike", "type"]).sort_index()
        return self.tables[day]

    def option(self, day, strike, call, expiry, sessions, spot, vix, when="close"):
        table = self.table(day)
        key = (pd.Timestamp(expiry), float(strike), "CE" if call else "PE")
        if table is not None and key in table.index:
            value = table.loc[key, when]
            if isinstance(value, pd.Series):
                value = value.iloc[0]
            if pd.notna(value) and value > 0:
                self.real += 1
                return float(value)
        self.estimated += 1
        return super().option(day, strike, call, expiry, sessions, spot, vix, when)

    def expiry_after(self, day, cal, include_today):
        table = self.table(day)
        if table is not None and len(table):
            for expiry in sorted(table.index.get_level_values(0).unique()):
                if expiry > day or (include_today and expiry == day):
                    return expiry
        return super().expiry_after(day, cal, include_today)

    def is_expiry(self, day, cal):
        table = self.table(day)
        if table is not None and len(table):
            return table.index.get_level_values(0).min() == day
        return super().is_expiry(day, cal)

    def monthly_after(self, day, cal, min_sessions):
        table = self.table(day)
        if table is not None and len(table):
            listed = pd.Series(sorted(table.index.get_level_values(0).unique()))
            for expiry in listed.groupby(listed.dt.to_period("M")).max():
                if expiry > day and cal.sessions(day, expiry) >= min_sessions:
                    return expiry
        return super().monthly_after(day, cal, min_sessions)


def compute(df=None):
    df = fb.load_data() if df is None else df
    cal = fb.Calendar(df.index)
    prices = RealPrices()
    latest = df.index[-1]
    idx = df.loc[pa.START:].index
    planned = {name: starts.start_of(name) for name in RULES}
    first_day = {}
    for name, day in planned.items():
        live = df.index[df.index >= day] if day is not None else []
        first_day[name] = live[0] if len(live) else None
    books = {}
    for s0 in sorted({d for d in first_day.values() if d is not None}):
        run = fb.run_all(df, cal, start=s0, prices=prices)[1]
        books.update({n: run[n] for n, d in first_day.items() if d == s0})
    start = min((d for d in first_day.values() if d is not None), default=first_start())
    values, labels, trades, rows = {}, {}, [], []
    for name, rule in RULES.items():
        book = books.get(name)
        curve = pd.Series(book.curve, dtype=float) if book else pd.Series(dtype=float)
        values[name] = curve.reindex(idx).fillna(pa.CAPITAL)
        labels[name] = pd.Series(book.labels if book else {}, dtype=object).reindex(idx).fillna("Not started yet")
        notes = book.trades if book else []
        trades += [{"date": d, "agent": name, "what": text, "nifty": float(df.at[d, "Close"])} for d, text in notes]
        v = values[name]
        rows.append({"agent": name, "value": v.iloc[-1], "since_start": v.iloc[-1] / pa.CAPITAL - 1,
                     "worst_fall": (v / v.cummax() - 1).min(), "holding": labels[name].iloc[-1],
                     "trades": len(notes), "today": next((t for d, t in reversed(notes) if d == latest), None),
                     "rule": rule, "wiped": bool(book and book.dead), "start": planned[name]})
    days = [d for d in idx if start is not None and d >= start]
    return dict(started=bool(books), latest=latest, start=start, values=pd.DataFrame(values), labels=labels,
                trades=sorted(trades, key=lambda t: (t["date"], t["agent"]), reverse=True),
                board=pd.DataFrame(rows).set_index("agent").sort_values("value", ascending=False),
                final_until=fp.final_until(df.index, start) if books else latest, days=len(days),
                real_days=sum(fp.load(d) is not None for d in days), estimated_prices=prices.estimated,
                real_prices=prices.real)


def backtest_rows(df=None):
    """Backtest summary for the page: return a year at three option-price estimates, and worst fall."""
    df = fb.load_data() if df is None else df
    cal = fb.Calendar(df.index)
    saved, runs = fb.ATM_RATIO, {}
    try:
        for ratio in (0.80, 0.88, 1.00):
            fb.ATM_RATIO = ratio
            runs[ratio] = fb.run_all(df, cal)[0]
    finally:
        fb.ATM_RATIO = saved
    rows = []
    for name in RULES:
        mid = fb.stats(runs[0.88][name])
        values = [fb.stats(runs[r][name])["cagr"] for r in runs]
        rows.append({"agent": name, "low": min(values), "high": max(values), "mid": mid["cagr"],
                     "worst_fall": mid["dd"], "fixed": "futures" in name.lower()})
    bench = fb.benchmarks(df)["Buy & hold Nifty (no F&O)"]
    s = fb.stats(bench)
    rows.append({"agent": "Buy & hold Nifty (no F&O)", "low": s["cagr"], "high": s["cagr"], "mid": s["cagr"],
                 "worst_fall": s["dd"], "fixed": True})
    first = df.loc[fb.START:].index[0]
    return rows, first, df.index[-1]


if __name__ == "__main__":
    res = compute()
    print(res["board"][["value", "since_start", "holding"]].to_string())
