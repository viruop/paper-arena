"""
asset_arena.py - the gold and multi-asset agents.

Six agents built from the Trade Like Berlin research report. Each manages Rs 1 lakh of virtual
money from the start date that logs/starts.json gives it (the first trading day after it was
added), using instruments an Indian resident can legally trade:

  Gold breakout                       GOLDBEES or cash
  Nifty-gold switch                   NIFTYBEES or GOLDBEES
  Gold/silver reversion               GOLDBEES or SILVERBEES
  Gold/silver trend                   GOLDBEES or SILVERBEES
  Gold breakdown short (control)      short gold through MCX Gold Petal futures, or cash
  3-day rule + US filter (control)    NIFTYBEES or cash

The two controls trade the YouTube channel's own rules (see berlin.py); the research
expected them to lose.
Timing matches the other agents: a rule reads a day's close and trades at the next trading
day's close. Signals that use US markets (COMEX gold and silver, the S&P 500) only see US
sessions that ended before India's close that day. Channel rules use closing prices only.

FOR LEARNING ONLY. Not investment advice. No real orders are placed.
"""

import numpy as np
import pandas as pd

import market_data as md
import paper_arena as pa
import starts

ETF_COST = 0.0005     # per buy or sell of an ETF: exchange and SEBI fees, stamp duty, DP charge, spread
FUT_COST = 0.0005     # per buy or sell of Gold Petal futures: brokerage, CTT, exchange fees, spread
CAPITAL = pa.CAPITAL
CASH_RATE = pa.CASH_RATE
CASH_DAILY = pa.CASH_DAILY
ASSETS = ["GOLDBEES", "NIFTYBEES", "SILVERBEES", "GOLD FUT"]
COSTS = pd.Series({"GOLDBEES": ETF_COST, "NIFTYBEES": ETF_COST, "SILVERBEES": ETF_COST, "GOLD FUT": FUT_COST})
SHOWN = {"GOLDBEES": "GOLDBEES", "NIFTYBEES": "NIFTYBEES", "SILVERBEES": "SILVERBEES",
         "GOLD FUT": "Short gold (Gold Petal)"}

AGENTS = {
    "Gold breakout": (
        "Buy GOLDBEES when it closes above its highest close of the previous 55 sessions; sell to cash "
        "when it closes below its lowest close of the previous 20."),
    "Nifty-gold switch": (
        "Always hold NIFTYBEES or GOLDBEES: switch to whichever wins a 20-session breakout of the "
        "NIFTYBEES/GOLDBEES price ratio."),
    "Gold/silver reversion": (
        "Hold GOLDBEES; switch to SILVERBEES when the gold/silver price ratio is 2 standard deviations "
        "above its 100-session average, and back to GOLDBEES when it returns to that average."),
    "Gold/silver trend": (
        "Hold GOLDBEES after the gold/silver price ratio breaks above its 20-session high, SILVERBEES "
        "after it breaks below its 20-session low."),
    "Gold breakdown short (control)": (
        "The YouTube channel's gold trade with a stop added: short gold (MCX Gold Petal, about 1x) when "
        "COMEX gold closes below its lowest low of the previous 55 sessions; buy back after a 10% fall "
        "or a close above the highest close of the previous 20."),
    "3-day rule + US filter (control)": (
        "The channel's overnight rule: buy NIFTYBEES when Nifty closes above the previous 3 days' high "
        "and its 10-day average while the S&P 500 is up over 3 sessions; sell when Nifty closes below "
        "the previous 3 days' low."),
}


# ------------------------------------- data --------------------------------------
class Market:
    """Every series the agents need, on India's trading calendar."""

    INDIA = ("GOLDBEES", "NIFTYBEES", "SILVERBEES")

    def __init__(self, nav_fallback=False, raw=None):
        self.raw = raw or {n: md.load(n, nav_fallback=nav_fallback) for n in md.SERIES}
        self.sources = {n: df.attrs.get("source", "none") for n, df in self.raw.items()}
        days = set()
        for n in self.INDIA + ("NIFTY50",):
            days |= set(self.raw[n].index)
        idx = pd.DatetimeIndex(sorted(days))
        self.idx = idx[idx.dayofweek < 5]
        self.close = pd.DataFrame({n: self.raw[n]["Close"].astype(float).reindex(self.idx).ffill(limit=5)
                                   for n in self.INDIA}, index=self.idx)
        self.nifty = self.raw["NIFTY50"].reindex(self.idx)
        lasts = [self.raw[n].index[-1] if len(self.raw[n]) else None for n in self.INDIA + ("NIFTY50",)]
        self.final = None if None in lasts else min(lasts)   # the last day every Indian price is in

    def returns(self):
        R = self.close.pct_change(fill_method=None)
        R["GOLD FUT"] = R["GOLDBEES"]           # Gold Petal follows domestic gold, which GOLDBEES tracks
        return R.reindex(columns=ASSETS)

    def us(self, s):
        """A US-dated series as known before India's close: the last US session on or before the
        previous calendar day (or NaN if that is more than a week old)."""
        s = s.dropna()
        if s.empty:
            return pd.Series(np.nan, index=self.idx)
        target = self.idx - pd.Timedelta(days=1)
        pos = s.index.searchsorted(target, side="right") - 1
        vals = np.where(pos >= 0, s.values[np.clip(pos, 0, None)], np.nan)
        age = (target - s.index[np.clip(pos, 0, None)]).days
        vals = np.where((pos >= 0) & (age <= 7), vals, np.nan)
        return pd.Series(vals.astype(float), index=self.idx)


# ----------------------------------- strategies ----------------------------------
def frame(idx, **cols):
    W = pd.DataFrame(0.0, index=idx, columns=ASSETS)
    for asset, values in cols.items():
        W[asset] = np.asarray(values, dtype=float)
    return W


def one_hot(idx, holding):
    return frame(idx, **{a: [h == a for h in holding] for a in ASSETS if a != "GOLD FUT"})


def gold_breakout(m, entry=55, exit_=20, trend=None):
    c = m.close["GOLDBEES"]
    hi = c.shift(1).rolling(entry, min_periods=entry).max().values
    lo = c.shift(1).rolling(exit_, min_periods=exit_).min().values
    ma = c.rolling(trend, min_periods=trend).mean().values if trend else np.full(len(c), -np.inf)
    pos, out = 0.0, []
    for p, h, l, a in zip(c.values, hi, lo, ma):
        if not (np.isnan(p) or np.isnan(h) or np.isnan(l) or np.isnan(a)):
            if pos == 0 and p > h and p > a:
                pos = 1.0
            elif pos == 1 and p < l:
                pos = 0.0
        out.append(pos)
    return frame(m.idx, GOLDBEES=out)


def channel_switch(series, n, up, down, default=None):
    """Hold `up` after the series breaks above its previous-n high, `down` after it breaks below its low."""
    hi = series.shift(1).rolling(n, min_periods=n).max().values
    lo = series.shift(1).rolling(n, min_periods=n).min().values
    hold, out = default, []
    for v, h, l in zip(series.values, hi, lo):
        if not (np.isnan(v) or np.isnan(h) or np.isnan(l)):
            if v > h:
                hold = up
            elif v < l:
                hold = down
        out.append(hold)
    return out


def nifty_gold_switch(m, n=20):
    ratio = m.close["NIFTYBEES"] / m.close["GOLDBEES"]
    return one_hot(m.idx, channel_switch(ratio, n, "NIFTYBEES", "GOLDBEES"))


def gold_silver_ratio(m):
    return np.log(m.close["GOLDBEES"] / m.close["SILVERBEES"])


def gold_silver_reversion(m, window=100, z_in=2.0, z_out=0.0, ratio=None):
    g = gold_silver_ratio(m) if ratio is None else ratio
    base = g.shift(1).rolling(window, min_periods=window)
    z = ((g - base.mean()) / base.std()).values
    hold, out = None, []
    for gv, zv in zip(g.values, z):
        if not np.isnan(gv):
            hold = hold or "GOLDBEES"
            if not np.isnan(zv):
                if hold == "GOLDBEES" and zv >= z_in:
                    hold = "SILVERBEES"
                elif hold == "SILVERBEES" and zv <= z_out:
                    hold = "GOLDBEES"
        out.append(hold)
    return one_hot(m.idx, out)


def gold_silver_trend(m, n=20, ratio=None):
    g = gold_silver_ratio(m) if ratio is None else ratio
    holding = channel_switch(g, n, "GOLDBEES", "SILVERBEES")
    holding = [h or ("GOLDBEES" if not np.isnan(v) else None) for h, v in zip(holding, g.values)]
    return one_hot(m.idx, holding)


def gold_signal(m, entry, stop, signal):
    """Close, previous-`entry` low and previous-`stop` high close of the gold series, on India's dates.
    signal="GOLD" uses COMEX gold (no trades until its data is in); "GOLDBEES" uses domestic gold."""
    if signal == "GOLD":
        g = m.raw["GOLD"]
        if g.empty:
            nothing = pd.Series(np.nan, index=m.idx)
            return nothing, nothing, nothing
        low = g["Low"].where(g["Low"] > 0, g["Close"])
        return (m.us(g["Close"]), m.us(low.shift(1).rolling(entry, min_periods=entry).min()),
                m.us(g["Close"].shift(1).rolling(stop, min_periods=stop).max()))
    c = m.close["GOLDBEES"]
    return (c, c.shift(1).rolling(entry, min_periods=entry).min(), c.shift(1).rolling(stop, min_periods=stop).max())


def silver_breakdown_recent(m, n=20, within=5):
    s = m.raw["SILVER"]
    if s.empty:
        return pd.Series(np.nan, index=m.idx)
    low = s["Low"].where(s["Low"] > 0, s["Close"])
    broke = (s["Close"] < low.shift(1).rolling(n, min_periods=n).min()).astype(float)
    return m.us(broke.rolling(within, min_periods=1).max())


def gold_breakdown_short(m, entry=55, stop=20, target=0.10, silver_filter=False, signal="GOLD"):
    close, low_prior, stop_level = gold_signal(m, entry, stop, signal)
    silver = silver_breakdown_recent(m) if silver_filter else pd.Series(1.0, index=m.idx)
    pos, ref, out, events = 0.0, None, [], []
    for day, c, lo, hi, sf in zip(m.idx, close.values, low_prior.values, stop_level.values, silver.values):
        if not (np.isnan(c) or np.isnan(lo) or np.isnan(hi)):
            if pos == 0 and c < lo and sf > 0:
                pos, ref = -1.0, c
                events.append((day, "short", c))
            elif pos == -1 and (c <= ref * (1 - target) or c > hi):
                events.append((day, "target" if c <= ref * (1 - target) else "stop", c / ref - 1))
                pos, ref = 0.0, None
        out.append(pos)
    W = frame(m.idx, **{"GOLD FUT": out})
    W.attrs["ref"] = ref                        # the close that triggered the open short, if any
    W.attrs["events"] = events                  # (decision day, "short"/"target"/"stop", price or gold's move)
    return W


def three_day_rule(m, us_filter=True, sma_filter=True):
    n = m.nifty
    hi3 = n["High"].shift(1).rolling(3, min_periods=3).max().values
    lo3 = n["Low"].shift(1).rolling(3, min_periods=3).min().values
    ma10 = n["Close"].rolling(10, min_periods=10).mean().values
    sp = m.raw["SP500"]["Close"]
    us_up = m.us((sp > sp.shift(3)).astype(float).where(sp.shift(3).notna())).values
    pos, out = 0.0, []
    for c, h, l, a, u in zip(n["Close"].values, hi3, lo3, ma10, us_up):
        if not (np.isnan(c) or np.isnan(h) or np.isnan(l)):
            if pos == 0 and c > h and (not sma_filter or c > a) and (not us_filter or u == 1):
                pos = 1.0
            elif pos == 1 and c < l:
                pos = 0.0
        out.append(pos)
    return frame(m.idx, NIFTYBEES=out)


def strategies(m):
    return {
        "Gold breakout": gold_breakout(m),
        "Nifty-gold switch": nifty_gold_switch(m),
        "Gold/silver reversion": gold_silver_reversion(m),
        "Gold/silver trend": gold_silver_trend(m),
        "Gold breakdown short (control)": gold_breakdown_short(m),
        "3-day rule + US filter (control)": three_day_rule(m),
    }


# ------------------------------------- engine ------------------------------------
def roll_days(idx):
    """Gold Petal expires on the last day of each month: roll 5 sessions before the month's last session."""
    s = pd.Series(0.0, index=idx)
    for _, days in pd.Series(idx, index=idx).groupby(idx.to_period("M")):
        if len(days) > 5:
            s.loc[days.index[-6]] = 1.0
    return s


def run(W, R, s0, cost_mult=1.0, lag=1):
    """Value from the close of s0 (all cash). W is the share of money each rule wants in each asset
    after a day's close; lag=1 fills at the next close (the arena's rule), lag=0 at the same close."""
    W = W.reindex(columns=ASSETS, fill_value=0.0).fillna(0.0)
    idx = R.index
    after = idx[idx > s0]
    first = pd.Series([float(CAPITAL)], index=[s0])
    if len(after) == 0:
        return first
    H = W.shift(1 + lag).fillna(0.0).loc[after[0]:]
    Rw = R.reindex(columns=ASSETS).loc[after[0]:].fillna(0.0)
    traded = H.diff().abs()
    traded.iloc[0] = H.iloc[0].abs()
    cost = traded.mul(COSTS, axis=1).sum(axis=1)
    cost += H["GOLD FUT"].abs() * roll_days(idx).loc[after[0]:] * 2 * FUT_COST
    r = (H * Rw).sum(axis=1) + (1 - H.sum(axis=1)) * CASH_DAILY - cost * cost_mult
    return pd.concat([first, CAPITAL * (1 + r).cumprod()])


def label(row):
    parts = []
    for asset, v in row.items():
        if abs(v) > 1e-9:
            share = "" if abs(abs(v) - 1) < 1e-9 else f"{abs(v):.0%} "
            parts.append(share + SHOWN[asset])
    return " + ".join(parts) or "Cash"


def action_text(before, after, past=True):
    b, a = label(before), label(after)
    if a == SHOWN["GOLD FUT"]:
        return "Sold gold short (Gold Petal)" if past else "Sell gold short (Gold Petal)"
    if b == SHOWN["GOLD FUT"] and a == "Cash":
        return "Bought back the gold short" if past else "Buy back the gold short"
    if b == "Cash":
        return ("Bought " if past else "Buy ") + a
    if a == "Cash":
        return "Sold to cash" if past else "Sell to cash"
    return ("Switched to " if past else "Switch to ") + a


def status(m, day, Ws=None):
    """One line per agent on where its signal stands at `day`'s close."""
    Ws = Ws or strategies(m)
    held = {name: W.loc[:day].iloc[-1] for name, W in Ws.items()}
    c = m.close.loc[:day]
    out = {}
    g = c["GOLDBEES"].dropna()
    if len(g) > 55:
        out["Gold breakout"] = (f"GOLDBEES {g.iloc[-1]:,.2f}. " + (
            f"Holding; sells below {g.iloc[-21:-1].min():,.2f} (20-session low)."
            if held["Gold breakout"]["GOLDBEES"] > 0 else
            f"In cash; buys above {g.iloc[-56:-1].max():,.2f} (55-session high)."))
    r = (c["NIFTYBEES"] / c["GOLDBEES"]).dropna()
    if len(r) > 20:
        out["Nifty-gold switch"] = (f"Holding {label(held['Nifty-gold switch'])}. NIFTYBEES/GOLDBEES ratio "
                                    f"{r.iloc[-1]:.3f}: switches to Nifty above {r.iloc[-21:-1].max():.3f}, to gold "
                                    f"below {r.iloc[-21:-1].min():.3f}.")
    gs = np.log(c["GOLDBEES"] / c["SILVERBEES"]).dropna()
    if len(gs) > 100:
        base = gs.iloc[-101:-1]
        z = (gs.iloc[-1] - base.mean()) / base.std()
        out["Gold/silver reversion"] = (f"Holding {label(held['Gold/silver reversion'])}. The gold/silver ratio is "
                                        f"{z:+.2f} standard deviations from its average (silver from +2.00, "
                                        f"back to gold at 0).")
        out["Gold/silver trend"] = (f"Holding {label(held['Gold/silver trend'])}. The ratio is " + (
            "at a 20-session high" if gs.iloc[-1] > gs.iloc[-21:-1].max() else
            "at a 20-session low" if gs.iloc[-1] < gs.iloc[-21:-1].min() else "inside its 20-session range") + ".")
    close, low55, hi20 = gold_signal(m, 55, 20, "GOLD")
    name = "Gold breakdown short (control)"
    if day in close.index and not np.isnan(close.loc[day]):
        ref = Ws[name].attrs.get("ref")
        out[name] = f"COMEX gold {close.loc[day]:,.1f} (last US close). " + (
            f"Short since a close at {ref:,.1f}; buys back at or below {ref * 0.9:,.1f} (the 10% target) or "
            f"above {hi20.loc[day]:,.1f} (the stop)." if held[name]["GOLD FUT"] < 0 and ref else
            f"In cash; shorts below {low55.loc[day]:,.1f} (55-session low).")
    elif m.raw["GOLD"].empty:
        out[name] = "Waiting for COMEX gold prices."
    n = m.nifty.loc[:day].dropna(subset=["Close"])
    if len(n) > 10:
        sp = m.raw["SP500"]["Close"]
        up = m.us((sp > sp.shift(3)).astype(float).where(sp.shift(3).notna())).get(day, np.nan)
        name = "3-day rule + US filter (control)"
        out[name] = f"Nifty {n['Close'].iloc[-1]:,.0f}. " + (
            f"Holding; sells below {n['Low'].iloc[-4:-1].min():,.0f} (the previous 3 days' low)."
            if held[name]["NIFTYBEES"] > 0 else
            f"In cash; buys above {n['High'].iloc[-4:-1].max():,.0f} if that close is above the 10-day average "
            f"{n['Close'].iloc[-10:].mean():,.0f} and the S&P 500 is up over 3 sessions "
            f"({'yes' if up == 1 else 'no' if up == 0 else 'no data'} today).")
    return out


BERLIN = ("Gold breakdown short (control)", "3-day rule + US filter (control)")


def claim_check(m, Ws, name, since, R=None, live=True):
    """How the channel's claim held up for a Berlin agent from `since`: one plain sentence."""
    W = Ws[name]
    if name == "Gold breakdown short (control)":
        ev = [e for e in W.attrs.get("events", []) if e[0] >= since]
        shorts = sum(1 for e in ev if e[1] == "short")
        target = sum(1 for e in ev if e[1] == "target")
        stops = [e[2] for e in ev if e[1] == "stop"]
        open_ = W["GOLD FUT"].iloc[-1] < 0
        if not shorts and not target and not stops:
            return "The short it opened on its first day is still open." if open_ and live else "No short has closed yet."
        text = (f"{shorts} {'short' if shorts == 1 else 'shorts'} opened; gold fell the full 10% after "
                f"{target}, and {len(stops)} hit the stop")
        if stops:
            text += f" (gold up {np.mean(stops):+.1%} on average by then)"
        return text + (". One short is open." if open_ and live else ".")
    if name == "3-day rule + US filter (control)":
        R = m.returns().loc[:m.final] if R is None else R
        rate, n = first_day_hits(W, R.loc[since:], "NIFTYBEES")
        if not n:
            return "No entries yet."
        return f"The first full day was a gain after {round(rate * n)} of {n} entries ({rate:.0%})."
    return ""


def ready(m):
    """The first day each rule has all its inputs, so backtests don't count months spent waiting for data."""
    out = {}
    gold = m.close["GOLDBEES"].dropna()
    both = m.close[["GOLDBEES", "SILVERBEES"]].dropna()
    pair = m.close[["NIFTYBEES", "GOLDBEES"]].dropna()
    if len(gold):
        out["Gold breakout"] = gold.index[0]
    if len(pair):
        out["Nifty-gold switch"] = pair.index[0]
    if len(both):
        out["Gold/silver reversion"] = out["Gold/silver trend"] = both.index[0]
    low55 = gold_signal(m, 55, 20, "GOLD")[1].dropna()
    if len(low55) and len(gold):
        out["Gold breakdown short (control)"] = max(low55.index[0], gold.index[0])
    sp = m.raw["SP500"]["Close"]
    us_up = m.us((sp > sp.shift(3)).astype(float).where(sp.shift(3).notna())).dropna()
    nifty = m.nifty["Close"].dropna()
    nb = m.close["NIFTYBEES"].dropna()
    if len(us_up) and len(nifty) and len(nb):
        out["3-day rule + US filter (control)"] = max(us_up.index[0], nifty.index[min(10, len(nifty) - 1)], nb.index[0])
    return out


# --------------------------------- paper trading ---------------------------------
def compute(m=None):
    """Paper-trading results for the page and the logs."""
    m = m or Market()
    if m.final is None:
        raise RuntimeError("no prices for the gold and multi-asset agents")
    latest = m.final
    R = m.returns().loc[:latest]
    Ws = strategies(m)
    idx = m.idx[(m.idx >= pd.Timestamp(pa.START)) & (m.idx <= latest)]
    nifty_close = m.nifty["Close"]
    values, labels, trades, rows, plans = {}, {}, [], [], {}
    for name, rule in AGENTS.items():
        planned = starts.start_of(name)
        W = Ws[name].loc[:latest]
        live = m.idx[(m.idx >= planned) & (m.idx <= latest)] if planned is not None else []
        if len(live) == 0:
            values[name] = pd.Series(float(CAPITAL), index=idx)
            labels[name] = pd.Series("Not started yet", index=idx, dtype=object)
            rows.append({"agent": name, "value": float(CAPITAL), "since_start": 0.0, "worst_fall": 0.0,
                         "holding": "Not started yet", "trades": 0, "today": None, "next": None, "rule": rule,
                         "start": planned})
            continue
        s0 = live[0]
        eq = run(W, R, s0)
        P = W.shift(1).fillna(0.0).loc[s0:]
        prev = P.shift(1)
        prev.iloc[0] = 0.0
        changed = (P - prev).abs().sum(axis=1) > 1e-9
        for day in P.index[changed.values]:
            trades.append({"date": day, "agent": name, "what": action_text(prev.loc[day], P.loc[day]),
                           "nifty": float(nifty_close.get(day, np.nan))})
        lab = P.apply(label, axis=1)
        values[name] = eq.reindex(idx).where(idx >= s0, float(CAPITAL)).ffill()
        labels[name] = lab.reindex(idx).where(idx >= s0, "Not started yet")
        now, wanted = P.iloc[-1], W.iloc[-1]
        rows.append({"agent": name, "value": float(eq.iloc[-1]), "since_start": float(eq.iloc[-1] / CAPITAL - 1),
                     "worst_fall": float((eq / eq.cummax() - 1).min()), "holding": label(now),
                     "trades": int(changed.sum()),
                     "today": action_text(prev.iloc[-1], now) if changed.iloc[-1] else None,
                     "next": action_text(now, wanted, past=False) if (wanted - now).abs().sum() > 1e-9 else None,
                     "rule": rule, "start": s0})
    checks = {r["agent"]: claim_check(m, Ws, r["agent"], r["start"], R) for r in rows
              if r["agent"] in BERLIN and r["start"] is not None and r["holding"] != "Not started yet"}
    board = pd.DataFrame(rows).set_index("agent").sort_values("value", ascending=False)
    return dict(started=any(len(v) and (lab != "Not started yet").any() for v, lab in zip(values.values(), labels.values())),
                latest=latest, values=pd.DataFrame(values, index=idx), labels=labels,
                trades=sorted(trades, key=lambda t: (t["date"], t["agent"]), reverse=True), board=board,
                final_until=latest, sources=m.sources, why=status(m, latest, Ws), market=m, checks=checks,
                first_start=min((r["start"] for r in rows if r["start"] is not None), default=None))


# ------------------------------------ backtests -----------------------------------
def stats(eq, W=None, lag=1):
    eq = eq.dropna()
    years = max((eq.index[-1] - eq.index[0]).days / 365.25, 1e-9)
    cagr = (eq.iloc[-1] / eq.iloc[0]) ** (1 / years) - 1
    dd = float((eq / eq.cummax() - 1).min())
    out = {"cagr": cagr, "dd": dd, "ratio": cagr / abs(dd) if dd < 0 else np.inf, "end": float(eq.iloc[-1]),
           "years": years}
    if W is not None:
        P = W.reindex(columns=ASSETS, fill_value=0.0).fillna(0.0).shift(lag).loc[eq.index[0]:eq.index[-1]]
        out["trades_yr"] = float(((P.diff().abs().sum(axis=1)) > 1e-9).sum() / years)
        out["invested"] = float((P.abs().sum(axis=1) > 1e-9).mean())
    return out


def first_valid(W, R, cols):
    """First day from which a rule and its assets have data."""
    need = R[cols].notna().all(axis=1)
    return need[need].index[0]


BENCHMARKS = {
    "Hold GOLDBEES": {"GOLDBEES": 1.0},
    "Hold NIFTYBEES": {"NIFTYBEES": 1.0},
    "50/50 Nifty + gold": {"NIFTYBEES": 0.5, "GOLDBEES": 0.5},
    "50/50 gold + silver": {"GOLDBEES": 0.5, "SILVERBEES": 0.5},
}
NEEDS = {
    "Gold breakout": ["GOLDBEES"], "Nifty-gold switch": ["NIFTYBEES", "GOLDBEES"],
    "Gold/silver reversion": ["GOLDBEES", "SILVERBEES"], "Gold/silver trend": ["GOLDBEES", "SILVERBEES"],
    "Gold breakdown short (control)": ["GOLDBEES"], "3-day rule + US filter (control)": ["NIFTYBEES"],
}
COMPARE = {
    "Gold breakout": ["Hold GOLDBEES"], "Nifty-gold switch": ["50/50 Nifty + gold"],
    "Gold/silver reversion": ["Hold GOLDBEES", "50/50 gold + silver"],
    "Gold/silver trend": ["Hold GOLDBEES", "50/50 gold + silver"],
    "Gold breakdown short (control)": ["Cash"], "3-day rule + US filter (control)": ["Cash"],
}


def benchmark(m, R, name, s0, end):
    if name == "Cash":
        idx = R.loc[s0:end].index
        return pd.Series(CAPITAL * (1 + CASH_DAILY) ** np.arange(len(idx)), index=idx)
    W = frame(m.idx, **{a: np.full(len(m.idx), w) for a, w in BENCHMARKS[name].items()})
    return run(W, R.loc[:end], s0).loc[:end]


def first_day_hits(W, R, asset, lag=1):
    """Share of entries whose first full day in the position was a gain."""
    P = W[asset].shift(lag).fillna(0.0)
    entries = P.index[(P.abs() > 0) & (P.shift(1).fillna(0.0).abs() == 0)]
    entries = [d for d in entries if len(R) and d >= R.index[0]]
    hits = []
    for day in entries:
        nxt = R.index[R.index > day]
        if len(nxt) and not np.isnan(R.at[nxt[0], asset]):
            hits.append(np.sign(P.loc[day]) * R.at[nxt[0], asset] > 0)
    return (float(np.mean(hits)) if hits else np.nan), len(hits)


def passes(name, halves):
    """The report's pass bar, judged on each half: dict half -> (agent stats, {benchmark: stats})."""
    ok = []
    for agent, bench in halves.values():
        if name == "3-day rule + US filter (control)" and not agent.get("hit", 0) >= 0.60:
            ok.append(False)
        if name == "Gold breakout":
            ok.append(agent["ratio"] > bench["Hold GOLDBEES"]["ratio"])
        elif name == "Nifty-gold switch":
            b = bench["50/50 Nifty + gold"]
            ok.append(agent["cagr"] > b["cagr"] and agent["dd"] > b["dd"])
        elif name.startswith("Gold/silver"):
            ok.append(all(agent["ratio"] > b["ratio"] for b in bench.values()))
        else:
            ok.append(agent["cagr"] > CASH_RATE)
    return all(ok)


def evaluate(m, name, W, cost_mult=1.0, lag=1, R=None, s0=None):
    """Full-period and half-by-half results for one rule against its benchmarks."""
    R = m.returns().loc[:m.final] if R is None else R
    s0 = max(first_valid(W, R, NEEDS[name]), W.index[0], s0 or W.index[0])
    end = R.index[-1]
    eq = run(W, R, s0, cost_mult, lag)
    mid = s0 + (end - s0) / 2
    asset = NEEDS[name][0] if not name == "Gold breakdown short (control)" else "GOLD FUT"
    halves = {}
    for label_, a, b in (("first half", s0, mid), ("second half", mid, end)):
        part = eq.loc[a:b]
        bench = {bn: stats(benchmark(m, R, bn, part.index[0], part.index[-1])) for bn in COMPARE[name]}
        st = stats(part, W, lag)
        st["hit"], st["entries"] = first_day_hits(W.loc[:b], R.loc[a:b], asset, lag)
        halves[label_] = (st, bench)
    bench_full = {bn: stats(benchmark(m, R, bn, s0, end)) for bn in COMPARE[name]}
    full = stats(eq, W, lag)
    full["hit"], full["entries"] = first_day_hits(W, R.loc[s0:], asset, lag)
    return {"eq": eq, "stats": full, "bench": bench_full, "halves": halves,
            "pass": passes(name, halves), "start": s0, "end": end, "mid": mid}


def backtest_rows(m=None):
    """Summary for the page: each agent's backtest after costs, its benchmark and the pass bar
    (judged in both halves at double costs, the report's strictest version)."""
    m = m or Market()
    if m.final is None:
        return None
    R = m.returns().loc[:m.final]
    starts_at = ready(m)
    rows = []
    for name, W in strategies(m).items():
        if name not in starts_at:
            continue
        try:
            base = evaluate(m, name, W, R=R, s0=starts_at[name])
            strict = evaluate(m, name, W, cost_mult=2.0, R=R, s0=starts_at[name])
        except (IndexError, ValueError):
            continue
        bench_name = COMPARE[name][0]
        check = claim_check(m, {name: W}, name, base["start"], R, live=False) if name in BERLIN else ""
        rows.append({"agent": name, "check": check, "cagr": base["stats"]["cagr"], "dd": base["stats"]["dd"],
                     "bench": bench_name, "bench_cagr": base["bench"][bench_name]["cagr"],
                     "bench_dd": base["bench"][bench_name]["dd"], "trades_yr": base["stats"]["trades_yr"],
                     "pass": bool(base["pass"] and strict["pass"]), "start": base["start"], "end": base["end"]})
    return rows, m.sources


if __name__ == "__main__":
    res = compute()
    print(res["board"][["value", "since_start", "holding", "start"]].to_string())
