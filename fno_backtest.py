"""
fno_backtest.py - tests common Nifty futures and options (F&O) strategies on daily data,
after Indian trading costs, so you can see how they would have done before risking money.

IMPORTANT: free data has no historical option prices. Option premiums here are MODELLED with
the Black-Scholes formula, using India VIX as the volatility plus a simple skew. Real prices
differ (bid-ask spreads, skew, expiry-day spikes), and intraday stops are approximated from each
day's high and low. Treat the results as a rough guide, not proof.

Run:  python fno_backtest.py
FOR LEARNING ONLY. Not investment advice. No real orders are placed.
"""

import io
import math
import sys
import urllib.request

import numpy as np
import pandas as pd

# ------------------------------------ settings ------------------------------------
START = "2019-02-11"      # Nifty weekly options began in February 2019
END = None                # None = latest available day
SPLIT = "2023-01-01"      # results before and after this date are also shown separately
CAPITAL = 100_000
CASH_RATE = 0.06          # interest on capital kept as collateral
DIV_YIELD = 0.012         # Nifty dividend yield, used for the futures carry
LEVERAGE = 3              # futures and option-selling exposure = LEVERAGE x capital
PREMIUM_PCT = 0.03        # option buying: premium spent per trade, as a share of capital
FUT_STOP = 0.005          # intraday futures stop-loss, 0.5% against the entry
STRADDLE_STOP = 0.30      # intraday straddle stop-loss, premium up 30%
OTM = 0.02                # strangle and condor: sold strikes about 2% away from Nifty
WING = 0.04               # condor: protective strikes about 4% away
STRIKE_STEP = 50
LOT = 65                  # Nifty lot size, used for per-order brokerage
BROKERAGE = 20            # rupees per order per lot
COST_MULT = 1.0           # 0 = no costs, 2 = double costs
SKEW = 3.0                # simple skew: out-of-the-money puts priced richer, calls cheaper
ATM_RATIO = 0.88          # at-the-money volatility as a share of India VIX. VIX includes the
                          # pricier far-away options, so it usually sits above at-the-money levels
TARGET_PER_DAY = 5_000    # used for "capital needed to average this much a day"
DAY_SHARE = 0.62          # share of a day's price movement that happens during market hours
                          # (measured on Nifty 2019-2026); the rest happens overnight, so an
                          # intraday seller only earns about this share of a day's time decay

DATA_URL = ("https://raw.githubusercontent.com/aswinv90/indian-market-historical-data/"
            "main/data/INDICES/{}.parquet")
DAYS_PER_YEAR = 252
CASH_DAILY = (1 + CASH_RATE) ** (1 / DAYS_PER_YEAR) - 1

# Securities transaction tax: (from date, futures sale, option premium sale, option exercise)
STT = [("2000-01-01", 0.0001, 0.0005, 0.00125),
       ("2023-04-01", 0.000125, 0.000625, 0.00125),
       ("2024-10-01", 0.0002, 0.001, 0.00125),
       ("2026-04-01", 0.0005, 0.0015, 0.0015)]


# -------------------------------------- data --------------------------------------
YAHOO = {"NIFTY_50": "^NSEI", "INDIA_VIX": "^INDIAVIX"}


def load(name):
    with urllib.request.urlopen(DATA_URL.format(name), timeout=60) as resp:
        df = pd.read_parquet(io.BytesIO(resp.read()))
    df.index = pd.to_datetime(df.index).tz_localize(None).normalize()
    df = df[["Open", "High", "Low", "Close"]].astype(float).sort_index()
    try:                       # if the free dataset missed a day, add Yahoo's newer closed sessions
        import market_data as md
        fresh = md.yahoo(YAHOO[name], "1mo", timeout=15)
        newer = fresh[fresh.index > df.index[-1]]
        if len(newer):
            df = pd.concat([df, newer])
    except Exception:
        pass
    return df


def load_data():
    print("Loading Nifty 50 and India VIX ...", file=sys.stderr)
    nifty, vix = load("NIFTY_50"), load("INDIA_VIX")
    nifty = nifty[~nifty.index.duplicated()].dropna(subset=["Close"])
    prev = nifty["Close"].shift(1)
    nifty["Open"] = nifty["Open"].where(nifty["Open"] > 0, prev).fillna(nifty["Close"])
    nifty["High"] = nifty[["High", "Open", "Close"]].max(axis=1)
    nifty["Low"] = nifty[["Low", "Open", "Close"]].min(axis=1)
    vix = vix[~vix.index.duplicated()].reindex(nifty.index).ffill()
    vix["Open"] = vix["Open"].where(vix["Open"] > 0, vix["Close"])
    df = nifty.join(vix[["Open", "Close"]].rename(columns={"Open": "VixOpen", "Close": "Vix"}))
    df["SMA20"] = df["Close"].rolling(20).mean()
    df["SMA200"] = df["Close"].rolling(200).mean()
    return df.dropna(subset=["Vix", "SMA200"]) if END is None else df.loc[:END].dropna(subset=["Vix", "SMA200"])


# --------------------------------- expiry calendar --------------------------------
def expiries(dates, extra_weeks=16):
    """Weekly Nifty expiries: Thursday until August 2025, Tuesday from September 2025,
    moved to the previous trading day when the exchange is shut. Future weeks assume no holiday."""
    trading = pd.DatetimeIndex(dates)
    mondays = pd.date_range(trading[0] - pd.Timedelta(days=trading[0].weekday()),
                            trading[-1] + pd.Timedelta(weeks=extra_weeks), freq="W-MON")
    out = []
    for monday in mondays:
        scheduled = monday + pd.Timedelta(days=1 if monday >= pd.Timestamp("2025-09-01") else 3)
        if scheduled > trading[-1]:
            out.append(scheduled)
            continue
        week = trading[(trading >= monday) & (trading <= scheduled)]
        if len(week):
            out.append(week[-1])
    return pd.DatetimeIndex(out)


class Calendar:
    def __init__(self, dates):
        self.dates = pd.DatetimeIndex(dates)
        self.exp = expiries(self.dates)
        self.monthly = set(pd.Series(self.exp).groupby(self.exp.to_period("M")).max())

    def sessions(self, day, expiry):
        """Trading sessions after `day` up to and including `expiry`."""
        last = self.dates[-1]
        if expiry <= last:
            return int(self.dates.searchsorted(expiry) - self.dates.searchsorted(day))
        inside = len(self.dates) - 1 - int(self.dates.searchsorted(day))
        return inside + int(np.busday_count((last + pd.Timedelta(days=1)).date(),
                                            (expiry + pd.Timedelta(days=1)).date()))

    def next_expiry(self, day, include_today):
        pos = self.exp.searchsorted(day, side="left" if include_today else "right")
        return self.exp[pos]

    def monthly_after(self, day, min_sessions):
        """The nearest monthly expiry with at least `min_sessions` sessions to go after `day`."""
        for expiry in sorted(e for e in self.monthly if e > day):
            if self.sessions(day, expiry) >= min_sessions:
                return expiry
        return None


# ---------------------------------- option prices ---------------------------------
def norm_cdf(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def bs(spot, strike, years, vol, call):
    if years <= 0:
        return max(spot - strike, 0.0) if call else max(strike - spot, 0.0)
    sd = vol * math.sqrt(years)
    d1 = (math.log(spot / strike) + (CASH_RATE - DIV_YIELD + 0.5 * vol * vol) * years) / sd
    d2 = d1 - sd
    if call:
        return spot * math.exp(-DIV_YIELD * years) * norm_cdf(d1) - strike * math.exp(-CASH_RATE * years) * norm_cdf(d2)
    return strike * math.exp(-CASH_RATE * years) * norm_cdf(-d2) - spot * math.exp(-DIV_YIELD * years) * norm_cdf(-d1)


def price(spot, strike, sessions, vix, call):
    vol = max(0.03, vix / 100 * ATM_RATIO * (1 + SKEW * math.log(spot / strike)))
    return bs(spot, strike, sessions / DAYS_PER_YEAR, vol, call)


def strike_near(x):
    return round(x / STRIKE_STEP) * STRIKE_STEP


def strike_up(x):
    return math.ceil(x / STRIKE_STEP) * STRIKE_STEP


def strike_down(x):
    return math.floor(x / STRIKE_STEP) * STRIKE_STEP


# -------------------------------------- costs -------------------------------------
def stt(day):
    rates = STT[0][1:]
    for start, *r in STT:
        if day >= pd.Timestamp(start):
            rates = r
    return rates


def option_cost(day, premium, units, buy, stop=False):
    turnover = premium * units
    brokerage = BROKERAGE * units / LOT
    exchange = turnover * (0.0005 if day < pd.Timestamp("2024-10-01") else 0.00035)
    cost = brokerage + exchange + 0.18 * (brokerage + exchange) + turnover * 1e-6
    cost += turnover * (0.00003 if buy else stt(day)[1])
    cost += units * max(0.05, (0.02 if stop else 0.003) * premium)   # bid-ask and slippage
    return cost * COST_MULT


def exercise_cost(day, intrinsic, units):
    """STT the buyer pays when an option expires in the money."""
    return intrinsic * units * stt(day)[2] * COST_MULT


def futures_cost(day, price_, units, buy, stop=False):
    turnover = abs(units) * price_
    brokerage = min(BROKERAGE * abs(units) / LOT, 0.0003 * turnover)
    exchange = turnover * 0.00002
    cost = brokerage + exchange + 0.18 * (brokerage + exchange) + turnover * 1e-6
    cost += turnover * (0.00002 if buy else stt(day)[0])
    cost += turnover * (0.0005 if stop else 0.00005)
    return cost * COST_MULT


# ------------------------------------ strategies ----------------------------------
class ModelPrices:
    """Option prices from the Black-Scholes model and India VIX. The paper arena swaps in
    NSE's real daily prices where it has them."""

    def option(self, day, strike, call, expiry, sessions, spot, vix, when="close"):
        return price(spot, strike, sessions, vix, call)

    def expiry_after(self, day, cal, include_today):
        return cal.next_expiry(day, include_today)

    def is_expiry(self, day, cal):
        return day in cal.exp

    def monthly_after(self, day, cal, min_sessions):
        return cal.monthly_after(day, min_sessions)


class Book:
    """One strategy's money, trades and holdings."""

    def __init__(self, name):
        self.name, self.equity, self.curve, self.dead = name, CAPITAL, {}, False
        self.trades, self.labels, self.pnls = [], {}, []

    def interest(self):
        self.equity *= 1 + CASH_DAILY

    def note(self, day, text):
        self.trades.append((day, text))

    def mark(self, day, open_value=0.0, holding="Cash"):
        value = self.equity + open_value
        if value <= 0:
            self.dead, self.equity, value, holding = True, 0.0, 0.0, "Wiped out"
        self.curve[day] = value
        self.labels[day] = holding


def money(x):
    return f"{'+' if x >= 0 else '-'}Rs {abs(x):,.0f}"


def short_date(d):
    return f"{d.day} {d:%b}"


def futures_trend(df, cal, lev=LEVERAGE, start=START):
    """Positional futures: long when Nifty closed above its 200-day average, short when below.
    Trades at the next open; rolls at each monthly expiry."""
    book, units, pos = Book("Futures trend (long/short)"), 0.0, 0
    rows = list(df.itertuples())
    for i in range(1, len(rows)):
        prev, r = rows[i - 1], rows[i]
        if r.Index < pd.Timestamp(start) or book.dead:
            continue
        book.interest()
        target = 1 if prev.Close > prev.SMA200 else -1
        if target != pos:
            book.equity += units * (r.Open - prev.Close)
            if units:
                book.equity -= futures_cost(r.Index, r.Open, units, buy=units < 0)
            units = target * lev * book.equity / r.Open
            book.equity -= futures_cost(r.Index, r.Open, units, buy=units > 0)
            book.equity += units * (r.Close - r.Open)
            book.note(r.Index, f"{'Bought' if target > 0 else 'Sold'} futures at the open, {r.Open:,.0f}"
                               + (" (reversed)" if pos else ""))
            pos = target
        else:
            book.equity += units * (r.Close - prev.Close)
        book.equity -= units * prev.Close * (CASH_RATE - DIV_YIELD) / DAYS_PER_YEAR
        if units and r.Index in cal.monthly:
            book.equity -= futures_cost(r.Index, r.Close, units, buy=units < 0)
            book.equity -= futures_cost(r.Index, r.Close, units, buy=units > 0)
        book.mark(r.Index, holding=f"{'Long' if pos > 0 else 'Short'} futures ({lev:g}x)")
    return book


def intraday_futures(df, cal, lev=LEVERAGE, start=START):
    """Every day: at the open, buy futures if Nifty closed above its 20-day average yesterday,
    otherwise sell. Stop-loss 0.5% against the entry, else exit at the close. Nothing overnight."""
    book = Book("Intraday futures")
    rows = list(df.itertuples())
    for i in range(1, len(rows)):
        prev, r = rows[i - 1], rows[i]
        if r.Index < pd.Timestamp(start) or book.dead:
            continue
        book.interest()
        side = 1 if prev.Close > prev.SMA20 else -1
        units = side * lev * book.equity / r.Open
        before = book.equity
        book.equity -= futures_cost(r.Index, r.Open, units, buy=side > 0)
        stop = r.Open * (1 - side * FUT_STOP)
        hit = r.Low <= stop if side > 0 else r.High >= stop
        exit_ = stop if hit else r.Close
        book.equity += units * (exit_ - r.Open)
        book.equity -= futures_cost(r.Index, exit_, units, buy=side < 0, stop=hit)
        book.note(r.Index, f"{'Bought' if side > 0 else 'Sold'} at the open {r.Open:,.0f}, "
                           f"{'stopped out at' if hit else 'closed at'} {exit_:,.0f}: {money(book.equity - before)}")
        book.mark(r.Index, holding="Nothing overnight")
    return book


def intraday_straddle(df, cal, lev=LEVERAGE, start=START, prices=None):
    """Every day: at the open, sell the at-the-money call and put of the nearest weekly expiry.
    Buy back if the pair's price rises 30% (checked against the day's high and low), else at the close."""
    prices = prices or ModelPrices()
    book = Book("Intraday short straddle")
    for r in df.loc[start:].itertuples():
        if book.dead:
            break
        book.interest()
        day = r.Index
        expiry = prices.expiry_after(day, cal, include_today=True)
        left = cal.sessions(day, expiry)                 # whole sessions after today
        strike = strike_near(r.Open)
        units = lev * book.equity / r.Open

        def model(spot, sessions, vix):
            return price(spot, strike, sessions, vix, True) + price(spot, strike, sessions, vix, False)

        def real(when, sessions, spot, vix):
            return sum(prices.option(day, strike, call, expiry, sessions, spot, vix, when) for call in (True, False))

        before = book.equity
        entry = real("open", left + DAY_SHARE, r.Open, r.VixOpen)
        book.equity -= 2 * option_cost(day, entry / 2, units, buy=False)
        worst_vix = max(r.VixOpen, r.Vix)
        worst = max(model(r.High, left + DAY_SHARE, worst_vix), model(r.Low, left + DAY_SHARE, worst_vix))
        hit = worst >= model(r.Open, left + DAY_SHARE, r.VixOpen) * (1 + STRADDLE_STOP)
        if hit:
            exit_ = entry * (1 + STRADDLE_STOP)
        elif left == 0:
            exit_ = abs(r.Close - strike)                # expires: worth what it is in the money
        else:
            exit_ = real("close", left, r.Close, r.Vix)
        book.equity += units * (entry - exit_)
        if left > 0 or hit:
            book.equity -= 2 * option_cost(day, exit_ / 2, units, buy=True, stop=hit)
        book.note(day, f"Sold the {strike:,} straddle at {entry:,.1f}, "
                       f"{'stopped out at' if hit else 'bought back at' if left else 'expired at'} "
                       f"{exit_:,.1f}: {money(book.equity - before)}")
        book.mark(day, holding="Nothing overnight")
    return book


def weekly_options(df, cal, kind, lev=LEVERAGE, premium_pct=PREMIUM_PCT, start=START, prices=None):
    """Opened at each expiry day's close and held to the next weekly expiry.
    kind: 'strangle' (sell ~2% OTM call and put), 'condor' (same plus ~4% OTM protection),
    'buy' (buy the at-the-money call if Nifty is above its 20-day average, else the put)."""
    prices = prices or ModelPrices()
    names = {"strangle": "Weekly short strangle", "condor": "Weekly iron condor", "buy": "Weekly option buying"}
    book, legs, expiry, opened_at = Book(names[kind]), [], None, 0.0
    for r in df.loc[start:].itertuples():
        if book.dead:
            break
        book.interest()
        day = r.Index
        if legs and day >= expiry:                       # settle at expiry
            for strike, call, qty in legs:
                intrinsic = max(r.Close - strike, 0) if call else max(strike - r.Close, 0)
                book.equity += qty * intrinsic
                if qty > 0 and intrinsic > 0:
                    book.equity -= exercise_cost(day, intrinsic, qty)
            book.note(day, f"Expired with Nifty at {r.Close:,.0f}: {money(book.equity - opened_at)} on the week")
            legs = []
        if not legs and prices.is_expiry(day, cal):      # open the next position at the close
            expiry = prices.expiry_after(day, cal, include_today=False)
            left = cal.sessions(day, expiry)
            s = r.Close
            if kind == "buy":
                call = s > r.SMA20
                strike = strike_near(s)
                prem = prices.option(day, strike, call, expiry, left, s, r.Vix)
                legs = [(strike, call, premium_pct * book.equity / prem)]
            else:
                qty = lev * book.equity / s
                legs = [(strike_up(s * (1 + OTM)), True, -qty), (strike_down(s * (1 - OTM)), False, -qty)]
                if kind == "condor":
                    legs += [(strike_up(s * (1 + WING)), True, qty), (strike_down(s * (1 - WING)), False, qty)]
            opened_at = book.equity
            parts = []
            for strike, call, q in legs:
                prem = prices.option(day, strike, call, expiry, left, s, r.Vix)
                book.equity -= q * prem
                book.equity -= option_cost(day, prem, abs(q), buy=q > 0)
                parts.append(f"{'bought' if q > 0 else 'sold'} {strike:,} {'CE' if call else 'PE'} at {prem:,.1f}")
            text = ", ".join(parts) + f" (expiry {short_date(expiry)})"
            book.note(day, text[0].upper() + text[1:])
        open_value, holding = 0.0, "Cash"
        if legs:
            left = cal.sessions(day, expiry)
            open_value = sum(q * prices.option(day, strike, call, expiry, left, r.Close, r.Vix)
                             for strike, call, q in legs)
            holding = (" + ".join(f"{'Long' if q > 0 else 'Short'} {strike:,} {'CE' if call else 'PE'}"
                                  for strike, call, q in legs) + f", expiry {short_date(expiry)}")
        book.mark(day, open_value, holding)
    return book


def vix_rank(vix, n):
    """Where each day's India VIX close ranks among the previous n-1 closes, from 0 (lowest) to 100."""
    return vix.rolling(n, min_periods=n).apply(lambda w: (w[:-1] < w[-1]).mean() * 100, raw=True)


def low_vix_straddle(df, cal, start=START, prices=None, lot=LOT, gain=1.5, loss=0.5, min_left=20, exit_left=5,
                     entries=None, name="Low-VIX long straddle"):
    """When India VIX is in the bottom quarter of both its 60- and 120-session ranges, buy one lot of the
    at-the-money call and put of the nearest monthly expiry with at least `min_left` sessions to go.
    Decided at a close and filled at the next close. Sold at the next close after a close where the pair is
    worth at least `gain` or at most `loss` times its cost, or once `exit_left` sessions remain.
    `entries` swaps the VIX signal for chosen days (the random-entry control)."""
    prices = prices or ModelPrices()
    book = Book(name)
    if entries is None:
        wanted = (vix_rank(df["Vix"], 60) < 25) & (vix_rank(df["Vix"], 120) < 25)
    else:
        wanted = pd.Series(df.index.isin(entries), index=df.index)
    order, legs, opened = None, None, 0.0
    for r in df.loc[start:].itertuples():
        if book.dead:
            break
        book.interest()
        day = r.Index
        if order == "buy" and legs is None:                    # fill yesterday's decision at today's close
            expiry = prices.monthly_after(day, cal, min_left)
            if expiry is not None:
                strike, left = strike_near(r.Close), cal.sessions(day, expiry)
                call = prices.option(day, strike, True, expiry, left, r.Close, r.Vix)
                put = prices.option(day, strike, False, expiry, left, r.Close, r.Vix)
                fees = option_cost(day, call, lot, buy=True) + option_cost(day, put, lot, buy=True)
                if lot * (call + put) + fees <= book.equity:
                    opened = book.equity
                    book.equity -= lot * (call + put) + fees
                    legs = (strike, expiry, call + put)
                    book.note(day, f"Bought the {strike:,} straddle at {call + put:,.1f} (expiry {short_date(expiry)})")
        elif order == "sell" and legs is not None:
            strike, expiry, paid = legs
            left = cal.sessions(day, expiry)
            call = prices.option(day, strike, True, expiry, left, r.Close, r.Vix)
            put = prices.option(day, strike, False, expiry, left, r.Close, r.Vix)
            book.equity += lot * (call + put) - option_cost(day, call, lot, buy=False) - option_cost(day, put, lot, buy=False)
            book.pnls.append(book.equity - opened)
            book.note(day, f"Sold the {strike:,} straddle at {call + put:,.1f}: {money(book.equity - opened)}")
            legs = None
        order = None
        open_value, holding = 0.0, "Cash"
        if legs is not None:
            strike, expiry, paid = legs
            left = cal.sessions(day, expiry)
            value = (prices.option(day, strike, True, expiry, left, r.Close, r.Vix)
                     + prices.option(day, strike, False, expiry, left, r.Close, r.Vix))
            open_value = lot * value
            holding = f"Long {strike:,} straddle, expiry {short_date(expiry)}"
            if value >= gain * paid or value <= loss * paid or left <= exit_left + 1:
                order = "sell"
        elif bool(wanted.get(day, False)):
            order = "buy"
        book.mark(day, open_value, holding)
    return book


def random_control(df, cal, start, runs=100, seed=7, **kw):
    """Average profit per trade when the same straddle opens on random days instead of low-VIX days."""
    rng = np.random.default_rng(seed)
    days = df.loc[start:].index
    averages = []
    for _ in range(runs):
        picks = days[rng.random(len(days)) < 0.05]
        book = low_vix_straddle(df, cal, start, entries=set(picks), **kw)
        if book.pnls:
            averages.append(np.mean(book.pnls))
    return float(np.mean(averages)), float(np.percentile(averages, 95))


def benchmarks(df):
    d = df.loc[START:]
    nifty = CAPITAL * d["Close"] / d["Open"].iloc[0]
    cash = pd.Series(CAPITAL * (1 + CASH_DAILY) ** np.arange(1, len(d) + 1), index=d.index)
    return {"Buy & hold Nifty (no F&O)": nifty, "Cash only": cash}


def run_all(df, cal, lev=LEVERAGE, premium_pct=PREMIUM_PCT, start=START, prices=None):
    books = [futures_trend(df, cal, lev, start), intraday_futures(df, cal, lev, start),
             intraday_straddle(df, cal, lev, start, prices),
             weekly_options(df, cal, "strangle", lev, start=start, prices=prices),
             weekly_options(df, cal, "condor", lev, start=start, prices=prices),
             weekly_options(df, cal, "buy", lev, premium_pct, start=start, prices=prices),
             low_vix_straddle(df, cal, start, prices)]
    curves = {b.name: pd.Series(b.curve) for b in books}
    return curves, {b.name: b for b in books}


# -------------------------------------- report ------------------------------------
def stats(curve):
    curve = curve[curve.index >= curve.index[0]]
    years = (curve.index[-1] - curve.index[0]).days / 365.25
    start = CAPITAL
    end = curve.iloc[-1]
    cagr = (end / start) ** (1 / years) - 1 if end > 0 else -1.0
    daily = pd.concat([pd.Series([end * 0 + curve.iloc[0] / start - 1]), curve.pct_change().iloc[1:]])
    daily = daily.replace([np.inf, -np.inf], np.nan).dropna()
    drawdown = (curve / np.maximum(curve.cummax(), start) - 1).min()
    mean = daily.mean()
    need = TARGET_PER_DAY / mean if mean > 0 and cagr > CASH_RATE else None
    return dict(cagr=cagr, dd=drawdown, end=end, win=(daily > 0).mean(), worst=daily.min(), need=need)


def rupees(x):
    if x is None:
        return "never"
    if x >= 1e7:
        return f"Rs {x / 1e7:,.1f} cr"
    return f"Rs {x / 1e5:,.1f} L"


def main():
    df = load_data()
    cal = Calendar(df.index)
    curves, books = run_all(df, cal)
    curves.update(benchmarks(df))
    first, last = df.loc[START:].index[0], df.index[-1]
    print(f"\nNIFTY F&O BACKTEST  {first.date()} -> {last.date()}  "
          f"(exposure {LEVERAGE}x capital, option buying {PREMIUM_PCT:.0%} of capital a week, after costs)")
    print("Option prices are MODELLED from India VIX; real prices differ.\n")
    print(f"{'Strategy':30s} {'Return/yr':>9s} {'Worst fall':>10s} {'Rs 1L ->':>10s} {'Up days':>8s} "
          f"{'Worst day':>9s} {'Capital for Rs 5k/day':>22s}")
    for name, curve in curves.items():
        s = stats(curve)
        dead = " (wiped out)" if name in books and books[name].dead else ""
        print(f"{name:30s} {s['cagr']:9.1%} {s['dd']:10.1%} {s['end']:10,.0f} {s['win']:8.0%} "
              f"{s['worst']:9.1%} {rupees(s['need']):>22s}{dead}")

    print(f"\nBefore vs after {SPLIT} (return/yr):")
    for name, curve in curves.items():
        a, b = curve.loc[:SPLIT], curve.loc[SPLIT:]
        ra = (a.iloc[-1] / CAPITAL) ** (365.25 / max((a.index[-1] - a.index[0]).days, 1)) - 1
        rb = (b.iloc[-1] / a.iloc[-1]) ** (365.25 / max((b.index[-1] - b.index[0]).days, 1)) - 1 if a.iloc[-1] > 0 else -1
        print(f"  {name:30s} {ra:7.1%} -> {rb:7.1%}")

    print("\nLeverage check (return/yr, worst fall):")
    for lev in (1, 3, 5):
        c, b = run_all(df, cal, lev=lev, premium_pct=PREMIUM_PCT * lev / 3)
        line = "  ".join(f"{n.split(' (')[0][:18]:18s} {stats(v)['cagr']:6.1%}/{stats(v)['dd']:6.1%}"
                         + ("!" if b[n].dead else "") for n, v in c.items())
        print(f"  {lev}x: {line}")

    print("\nCost check (return/yr at 0x, 1x, 2x costs):")
    global COST_MULT
    saved = COST_MULT
    results = {}
    for mult in (0.0, 1.0, 2.0):
        COST_MULT = mult
        c, _ = run_all(df, cal)
        for n, v in c.items():
            results.setdefault(n, []).append(stats(v)["cagr"])
    COST_MULT = saved
    for n, r in results.items():
        print(f"  {n:30s} " + "  ".join(f"{x:7.1%}" for x in r))

    print("\nOption-price check (return/yr with at-the-money volatility at 80%, 88%, 100% of VIX):")
    global ATM_RATIO
    saved = ATM_RATIO
    results = {}
    for ratio in (0.80, 0.88, 1.00):
        ATM_RATIO = ratio
        c, _ = run_all(df, cal)
        for n, v in c.items():
            if "futures" not in n.lower():
                results.setdefault(n, []).append(stats(v)["cagr"])
    ATM_RATIO = saved
    for n, r in results.items():
        print(f"  {n:30s} " + "  ".join(f"{x:7.1%}" for x in r))

    straddle_report(df, cal)
    pd.DataFrame(curves).to_csv("fno_backtest_values.csv")
    return curves, books


def straddle_report(df, cal, start="2009-07-01"):
    """The low-VIX straddle from 2009, against the same straddle bought on random days."""
    global ATM_RATIO
    print(f"\nLOW-VIX LONG STRADDLE, monthly options, {start} on (one lot of {LOT}; option prices modelled):")
    saved = ATM_RATIO
    for ratio in (0.80, 0.88, 1.00):
        ATM_RATIO = ratio
        book = low_vix_straddle(df, cal, start)
        pnl = np.array(book.pnls)
        s = stats(pd.Series(book.curve))
        rand, rand95 = random_control(df, cal, start, runs=60)
        verdict = ("PASSES" if len(pnl) >= 20 and pnl.mean() > rand95 else
                   "beats the random average, but not convincingly" if len(pnl) and pnl.mean() > rand else "FAILS")
        print(f"  at-the-money volatility {ratio:.0%} of VIX: {len(pnl)} trades, {np.mean(pnl > 0) if len(pnl) else 0:.0%} "
              f"winners, average {money(pnl.mean() if len(pnl) else 0)} a trade, {s['cagr']:+.1%} a year, worst fall "
              f"{s['dd']:.1%}. Random days: average {money(rand)} a trade (95th percentile {money(rand95)}). {verdict}")
    ATM_RATIO = saved


if __name__ == "__main__":
    main()
