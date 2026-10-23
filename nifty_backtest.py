"""
nifty_backtest.py - learn by backtesting 5 simple strategies on Indian indices.

FOR LEARNING ONLY. Not investment advice. Past results do not predict future returns.

HOW TO RUN
  Google Colab (free, nothing to install): colab.research.google.com -> New notebook ->
      paste this whole file into one cell -> press Run.
  Your own computer:  pip install pandas numpy matplotlib pyarrow
                      python nifty_backtest.py

WHAT IT DOES
  Downloads daily closing prices for Nifty 50 and four other NSE indices, runs five
  strategies (plus a cash benchmark) over the dates you choose, charges trading costs,
  and prints the return per year, the average return per trading day, the worst fall
  (drawdown) and more. Then it runs four learning checks:
    1. in-sample vs out-of-sample: does it keep working on years you did not tune it on?
    2. execution timing: same-day close vs next-day close
    3. trading costs: 0% to 0.2% per side
    4. overfitting: does the trend filter only work with one "magic" average length?

WHAT TO TRY
  Change START / END / SPLIT to test other periods, DELAY and COST_PER_SIDE to see how
  fragile each strategy is, or add your own strategy function next to the others.

DATA
  Default: free daily index data from github.com/aswinv90/indian-market-historical-data
  (licensed for personal, non-commercial use). Or set DATA_SOURCE = "yfinance".
  Index prices exclude dividends (about 1-1.5% a year); an ETF such as NIFTYBEES gets them.
"""

# ============================ SETTINGS: change these ============================
START = "2010-01-01"      # first day of the backtest
END = None                # last day, e.g. "2024-12-31"; None = latest data available
SPLIT = "2018-01-01"      # in-sample before this date, out-of-sample after; None = no split
CAPITAL = 100_000         # starting money in rupees
COST_PER_SIDE = 0.001     # 0.10% per buy and per sell: charges + slippage (conservative for ETFs)
CASH_RATE = 0.06          # yearly return on idle money (liquid fund); RBI repo averaged ~6.2% since 2010
DELAY = 1                 # 1 = act at the NEXT day's close after a signal (you check after market hours)
                          # 0 = act at the same day's close (you check ~3:20 pm and trade before 3:30 pm)
DATA_SOURCE = "github"    # "github", "yfinance" (pip install yfinance) or "csv"
CSV_FOLDER = "data"       # for "csv": files like data/NIFTY_50.csv with Date and Close columns
SAVE_CHART = "nifty_backtest.png"
SAVE_TABLE = "nifty_backtest_results.csv"
# =================================================================================

import io
import urllib.request

import matplotlib
import matplotlib.pyplot as plt
import matplotlib.ticker
import numpy as np
import pandas as pd

INDICES = {  # display name: (file name in the GitHub dataset, Yahoo Finance ticker)
    "NIFTY 50": ("NIFTY_50", "^NSEI"),
    "NIFTY BANK": ("NIFTY_BANK", "^NSEBANK"),
    "NIFTY IT": ("NIFTY_IT", "^CNXIT"),
    "NIFTY PHARMA": ("NIFTY_PHARMA", "^CNXPHARMA"),
    "NIFTY MIDCAP 50": ("NIFTY_MIDCAP_50", "^NSEMDCP50"),
}
GITHUB_URL = ("https://raw.githubusercontent.com/aswinv90/indian-market-historical-data/"
              "main/data/INDICES/{}.parquet")
DATA_FROM = "2008-01-01"  # extra history before START so 200-day averages are ready
TRADING_DAYS = 250
CASH_DAILY = (1 + CASH_RATE) ** (1 / TRADING_DAYS) - 1


# ----------------------------------- data ---------------------------------------
def load_close(name):
    file, ticker = INDICES[name]
    if DATA_SOURCE == "github":
        with urllib.request.urlopen(GITHUB_URL.format(file), timeout=60) as resp:
            df = pd.read_parquet(io.BytesIO(resp.read()))
    elif DATA_SOURCE == "yfinance":
        import yfinance as yf
        df = yf.Ticker(ticker).history(start=DATA_FROM, auto_adjust=True)
    else:
        df = pd.read_csv(f"{CSV_FOLDER}/{file}.csv", parse_dates=["Date"], index_col="Date")
    idx = pd.DatetimeIndex(pd.to_datetime(df.index))
    if idx.tz is not None:
        idx = idx.tz_localize(None)
    s = pd.Series(df["Close"].astype(float).values, index=idx.normalize())
    s = s[~s.index.duplicated(keep="last")].sort_index()
    s = s[s > 0].loc[DATA_FROM:]
    if END:
        s = s.loc[:END]
    if s.empty:
        raise ValueError("no data returned")
    moves = (s / s.shift(1) - 1).abs()
    for day, move in moves[moves > 0.20].items():
        print(f"  ! data check: {name} moved {move:.0%} on {day.date()} - make sure that is real")
    return s


def load_all():
    print(f"Loading data from {DATA_SOURCE} ...")
    closes = {}
    for name in INDICES:
        try:
            closes[name] = load_close(name)
        except Exception as err:  # keep going if one index fails
            print(f"  ! could not load {name}: {err}")
    if "NIFTY 50" not in closes:
        raise SystemExit("Nifty 50 data is required - check your internet connection or DATA_SOURCE.")
    calendar = closes["NIFTY 50"].index
    return pd.DataFrame({k: v.reindex(calendar).ffill(limit=5) for k, v in closes.items()})


# -------------------------------- indicators ------------------------------------
def sma(s, n):
    return s.rolling(n, min_periods=n).mean()


def rsi(s, n):
    change = s.diff()
    up = change.clip(lower=0).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    down = (-change.clip(upper=0)).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    return 100 - 100 / (1 + up / down)


# -------------------------------- strategies ------------------------------------
# Each returns the position you WANT after seeing a day's close: 1 = hold, 0 = cash.

def sig_cash(c):
    """Benchmark: never invest, keep everything in a liquid fund earning CASH_RATE."""
    return pd.Series(0.0, index=c.index)


def sig_buy_hold(c):
    """Benchmark: buy once, never sell."""
    return pd.Series(1.0, index=c.index)


def sig_trend(c, n=200):
    """Trend-following: hold Nifty while it closes above its n-day average, else sit in cash."""
    return (c > sma(c, n)).astype(float)


def sig_golden_cross(c, fast=50, slow=200):
    """Trend-following: hold while the 50-day average is above the 200-day average."""
    return (sma(c, fast) > sma(c, slow)).astype(float)


def sig_rsi2(c, entry=10):
    """Mean reversion: in an uptrend (above 200-day avg), buy a sharp 1-2 day dip (RSI(2) below 10).
    Sell when the price closes back above its 5-day average. Trades are usually a few days long."""
    avg200, avg5, r2 = sma(c, 200), sma(c, 5), rsi(c, 2)
    pos, out = 0.0, []
    for price, a200, a5, r in zip(c.values, avg200.values, avg5.values, r2.values):
        if np.isnan(a200) or np.isnan(r):
            out.append(0.0)
            continue
        if pos == 0 and price > a200 and r < entry:
            pos = 1.0
        elif pos == 1 and price > a5:
            pos = 0.0
        out.append(pos)
    return pd.Series(out, index=c.index)


def weights_rotation(closes, lookback=126):
    """Momentum rotation: on the last trading day of each month, hold the ONE index with the best
    6-month return - but only if that return beats cash; otherwise hold cash for the month."""
    momentum = closes / closes.shift(lookback) - 1
    hurdle = (1 + CASH_RATE) ** (lookback / TRADING_DAYS) - 1
    idx = closes.index
    month_ends = set(pd.Series(idx, index=idx).groupby(idx.to_period("M")).max())
    rows, pick = [], None
    for day in idx:
        if day in month_ends:
            m = momentum.loc[day].dropna()
            pick = m.idxmax() if len(m) and m.max() > hurdle else None
        rows.append({col: float(col == pick) for col in closes.columns})
    return pd.DataFrame(rows, index=idx)


# --------------------------------- engine ---------------------------------------
def backtest(R, W, delay, start, end, cost=None):
    """R: daily returns of each index. W: wanted weights decided at each close.
    The position is changed at the close 'delay' days later and earns returns from the next day."""
    cost = COST_PER_SIDE if cost is None else cost
    H = W.shift(1 + delay).fillna(0.0).loc[start:end]       # what you actually hold each day
    Rw = R[W.columns].loc[start:end].fillna(0.0)
    turnover = H.diff().abs().sum(axis=1)
    turnover.iloc[0] = H.iloc[0].abs().sum()                  # initial buy, if invested on day 1
    r = (H * Rw).sum(axis=1) + (1 - H.sum(axis=1)) * CASH_DAILY - turnover * cost
    return r, H


def trade_list(H, R):
    held = H.idxmax(axis=1).where(H.sum(axis=1) > 0, "CASH")
    segment = (held != held.shift()).cumsum()
    trades = []
    for days in held.groupby(segment).groups.values():
        asset = held.loc[days[0]]
        if asset != "CASH":
            trades.append((1 + R.loc[days, asset].fillna(0)).prod() * (1 - COST_PER_SIDE) ** 2 - 1)
    return trades


def years_below_peak(equity):
    under = equity < equity.cummax()
    if not under.any():
        return 0.0
    spell = (~under).cumsum()[under]
    longest = max((g.index[-1] - g.index[0]).days for _, g in spell.groupby(spell))
    return longest / 365.25


def stats(r, H=None, trades=None):
    eq = (1 + r).cumprod()
    years = (r.index[-1] - r.index[0]).days / 365.25
    out = {
        "Return per year": eq.iloc[-1] ** (1 / years) - 1,
        "Avg per trading day": eq.iloc[-1] ** (1 / len(r)) - 1,
        "Worst fall (max drawdown)": (eq / eq.cummax() - 1).min(),
        "Longest wait for new high (yrs)": years_below_peak(eq),
        "Sharpe vs cash": ((r.mean() - CASH_DAILY) / r.std() * np.sqrt(TRADING_DAYS)
                           if r.std() > 1e-12 else np.nan),
        "Best day": r.max(),
        "Worst day": r.min(),
        "Final value (Rs)": CAPITAL * eq.iloc[-1],
    }
    if H is not None:
        out["Time invested"] = float((H.sum(axis=1) > 0).mean())
    if trades is not None:
        out["Trades"] = len(trades)
        out["Win rate"] = float(np.mean([t > 0 for t in trades])) if trades else np.nan
    return out


# -------------------------------- reporting -------------------------------------
PCT_ROWS = {"Return per year", "Worst fall (max drawdown)", "Best day", "Worst day",
            "Time invested", "Win rate"}


def show(table):
    shown = table.copy().astype(object)
    for row in shown.index:
        for col in shown.columns:
            v = table.loc[row, col]
            if pd.isna(v):
                shown.loc[row, col] = "-"
            elif row in PCT_ROWS:
                shown.loc[row, col] = f"{v:.1%}"
            elif row == "Avg per trading day":
                shown.loc[row, col] = f"{v:.3%}"
            elif row == "Final value (Rs)":
                shown.loc[row, col] = rupees(v)
            elif row == "Trades":
                shown.loc[row, col] = f"{int(v)}"
            else:
                shown.loc[row, col] = f"{v:.2f}"
    print(shown.to_string())


def pct(df):
    return df.apply(lambda col: col.map(lambda v: f"{v:.1%}"))


def rupees(x):
    if x >= 1e7:
        return f"Rs {x / 1e7:,.2f} crore"
    if x >= 1e5:
        return f"Rs {x / 1e5:,.2f} lakh"
    return f"Rs {x:,.0f}"


def make_strategies(closes):
    nifty = closes["NIFTY 50"]
    return {
        "Cash only": sig_cash(nifty).to_frame("NIFTY 50"),
        "Buy & hold": sig_buy_hold(nifty).to_frame("NIFTY 50"),
        "200-day trend": sig_trend(nifty).to_frame("NIFTY 50"),
        "Golden cross": sig_golden_cross(nifty).to_frame("NIFTY 50"),
        "RSI(2) dip-buy": sig_rsi2(nifty).to_frame("NIFTY 50"),
        "Momentum rotation": weights_rotation(closes),
    }


def main():
    closes = load_all()
    R = closes / closes.shift(1) - 1
    nifty = closes["NIFTY 50"]
    start, end = START, END or closes.index[-1]

    strategies = make_strategies(closes)

    returns, table = {}, {}
    for name, W in strategies.items():
        r, H = backtest(R, W, DELAY, start, end)
        returns[name] = r
        table[name] = stats(r, H, trade_list(H, R))
    table = pd.DataFrame(table)

    first, last = returns["Buy & hold"].index[[0, -1]]
    print(f"\nBACKTEST {first.date()} to {last.date()} | cost {COST_PER_SIDE:.2%} per side | "
          f"cash earns {CASH_RATE:.0%}/yr | act {'next day' if DELAY else 'same day'} at close\n")
    show(table)
    table.to_csv(SAVE_TABLE)

    if SPLIT:
        print(f"\nDOES IT HOLD UP? in-sample (before {SPLIT}) vs out-of-sample (from {SPLIT})")
        split = {}
        for name, r in returns.items():
            a, b = stats(r[r.index < SPLIT]), stats(r[r.index >= SPLIT])
            split[name] = {"Return/yr  IN": a["Return per year"], "Return/yr  OUT": b["Return per year"],
                           "Max fall  IN": a["Worst fall (max drawdown)"],
                           "Max fall  OUT": b["Worst fall (max drawdown)"]}
        print(pct(pd.DataFrame(split).T).to_string())

    print("\nEXECUTION TIMING: return per year if you act at the same close vs the next day's close")
    timing = {name: {f"DELAY={d}": stats(backtest(R, W, d, start, end)[0])["Return per year"]
                     for d in (0, 1)} for name, W in strategies.items()}
    print(pct(pd.DataFrame(timing).T).to_string())

    print("\nCOST CHECK: return per year at different trading costs per side")
    costs = {name: {f"{c:.2%}": stats(backtest(R, W, DELAY, start, end, cost=c)[0])["Return per year"]
                    for c in (0.0, 0.0005, 0.001, 0.002)} for name, W in strategies.items()}
    print(pct(pd.DataFrame(costs).T).to_string())

    if SPLIT:
        print("\nOVERFITTING CHECK: trend filter with different average lengths")
        sweep = {}
        for n in (50, 100, 150, 200, 250):
            r, _ = backtest(R, sig_trend(nifty, n).to_frame("NIFTY 50"), DELAY, start, end)
            a, b = stats(r[r.index < SPLIT]), stats(r[r.index >= SPLIT])
            sweep[f"{n}-day"] = {"Return/yr  IN": a["Return per year"], "Return/yr  OUT": b["Return per year"],
                                 "Max fall  OUT": b["Worst fall (max drawdown)"]}
        print(pct(pd.DataFrame(sweep).T).to_string())

    best = table.loc["Return per year"].idxmax()
    nifty_days = (nifty / nifty.shift(1) - 1).loc[first:last]
    print(f"\nREALITY CHECK: Rs {CAPITAL:,} growing at a steady daily rate for one year ({TRADING_DAYS} trading days)")
    for p in (0.0005, 0.001, 0.01, 0.05, 0.06):
        print(f"  {p:6.2%} a day  ->  {rupees(CAPITAL * (1 + p) ** TRADING_DAYS)}")
    print(f"  Nifty 50 rose more than 5% in a single day on {(nifty_days > 0.05).sum()} of "
          f"{len(nifty_days)} trading days in this period.")
    print(f"  Best strategy here ({best}) averaged {table.loc['Avg per trading day', best]:.3%} per trading day.")

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(11, 8), sharex=True,
                                   gridspec_kw={"height_ratios": [2, 1]})
    for name, r in returns.items():
        eq = CAPITAL * (1 + r).cumprod()
        style = dict(color="grey", ls="--", lw=1) if name == "Cash only" else dict(lw=1.4)
        ax1.plot(eq.index, eq, label=f"{name} ({table.loc['Return per year', name]:.1%}/yr)", **style)
        ax2.plot(eq.index, (eq / eq.cummax() - 1) * 100, **{**style, "lw": 1})
    ax1.set_yscale("log")
    ax1.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: f"Rs {v / 1e5:g} lakh"))
    ax1.yaxis.set_minor_formatter(matplotlib.ticker.NullFormatter())
    lo = min((CAPITAL * (1 + r).cumprod()).min() for r in returns.values()) * 0.92
    hi = max((CAPITAL * (1 + r).cumprod()).max() for r in returns.values()) * 1.08
    ax1.set_ylim(lo, hi)
    ax1.set_yticks([v * 1e5 for v in (0.5, 0.75, 1, 1.5, 2, 3, 4, 5, 6, 8, 10, 15, 20, 30, 50)
                    if lo <= v * 1e5 <= hi])
    ax1.set_ylabel(f"Value of Rs {CAPITAL:,} (log scale)")
    ax1.set_title(f"Nifty strategies {first.date()} to {last.date()}, after costs - for learning only")
    ax1.legend(loc="upper left", fontsize=9)
    ax2.set_ylabel("Fall from peak (%)")
    for ax in (ax1, ax2):
        ax.grid(alpha=0.3)
        if SPLIT:
            ax.axvline(pd.Timestamp(SPLIT), color="grey", ls="--", lw=1)
    ax1.text(pd.Timestamp(SPLIT) if SPLIT else first, ax1.get_ylim()[0] * 1.05,
             "  out-of-sample ->" if SPLIT else "", color="grey", fontsize=9)
    fig.tight_layout()
    fig.savefig(SAVE_CHART, dpi=140)
    print(f"\nSaved {SAVE_CHART} and {SAVE_TABLE}")
    if matplotlib.get_backend().lower() != "agg":   # opens a window locally / shows inline in Colab
        plt.show()


if __name__ == "__main__":
    main()
