"""
paper_arena.py - a paper-trading arena. Each strategy is an "agent" with its own virtual
Rs 1 lakh. Run it every evening after about 8 pm IST to see what each agent did today,
why, and what it will do at tomorrow's close.

FOR LEARNING ONLY. No real orders are placed. Not investment advice.

HOW TO RUN (same as nifty_backtest.py)
  Google Colab: paste this file into a cell and run it. Your computer:
      pip install pandas numpy matplotlib pyarrow
      python paper_arena.py

HOW IT WORKS
  * START is the first day of paper trading. Keep it fixed once you begin.
  * Every agent starts with CAPITAL in cash. Each one reads its rule after a day's close
    and trades at the NEXT trading day's close, like the backtester with DELAY = 1.
  * Nothing needs saving between runs: the arena replays every day since START from the
    price data, so missing a day is fine and Colab works without extra files.
  * Add yourself (and Claude, if you like) as agents in MANUAL_AGENTS to see whether
    judgment beats the rules.
"""

# ================================ SETTINGS ================================
START = "2026-10-23"      # first day of paper trading; keep this fixed once you begin
CAPITAL = 100_000         # virtual rupees for each agent
COST_PER_SIDE = 0.001     # 0.10% per buy or sell
CASH_RATE = 0.06          # yearly return on idle cash (liquid fund)
DATA_SOURCE = "github"    # "github", "yfinance" (pip install yfinance) or "csv"
CSV_FOLDER = "data"       # for "csv": files like data/NIFTY_50.csv with Date and Close columns

# Your own decisions as extra agents. Each evening you decide, add a line
#     "YYYY-MM-DD": share of money in Nifty 50   (0 = all cash, 0.5 = half, 1 = all in)
# using that evening's date. It is filled at the next trading day's close.
MANUAL_AGENTS = {
    "Me": {
        # "2026-10-23": 1.0,
    },
}
# Claude's decisions live in decisions/claude.json. claude_agent.py adds one each evening
# when the ANTHROPIC_API_KEY secret is set; without it, Claude keeps its last position.
CLAUDE_FILE = "decisions/claude.json"
SAVE_CHART = "paper_arena.png"
SAVE_LOG = "paper_arena_log.csv"
# ==========================================================================

import io
import json
import os
import urllib.request

import matplotlib
import matplotlib.pyplot as plt
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
DATA_FROM = (pd.Timestamp(START) - pd.DateOffset(years=3)).strftime("%Y-%m-%d")
TRADING_DAYS = 250
CASH_DAILY = (1 + CASH_RATE) ** (1 / TRADING_DAYS) - 1
LOOKBACK = 126  # about 6 months of trading days, for the rotation agent
HURDLE = (1 + CASH_RATE) ** (LOOKBACK / TRADING_DAYS) - 1


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
    if s.empty:
        raise ValueError("no data returned")
    if DATA_SOURCE == "github":          # the free dataset sometimes misses a day: top up from Yahoo
        try:
            import market_data
            s = market_data.extend_with_yahoo(s, ticker)
        except ImportError:
            pass
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


# --------------------------------- agents ---------------------------------------
# Each agent gives the position it WANTS after seeing a day's close (share of money per index).

def sig_cash(c):
    return pd.Series(0.0, index=c.index)


def sig_buy_hold(c):
    return pd.Series(1.0, index=c.index)


def sig_trend(c, n=200):
    return (c > sma(c, n)).astype(float)


def sig_golden_cross(c, fast=50, slow=200):
    return (sma(c, fast) > sma(c, slow)).astype(float)


def sig_rsi2(c, entry=10):
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


def month_end_days(idx):
    """Last trading day of each month. The newest day counts only if no weekday is left in its month."""
    ends = set()
    for i, day in enumerate(idx):
        if i + 1 < len(idx):
            if idx[i + 1].month != day.month:
                ends.add(day)
        elif (day + pd.offsets.BDay(1)).month != day.month:
            ends.add(day)
    return ends


def weights_rotation(closes):
    momentum = closes / closes.shift(LOOKBACK) - 1
    ends = month_end_days(closes.index)
    rows, pick = [], None
    for day in closes.index:
        if day in ends:
            m = momentum.loc[day].dropna()
            pick = m.idxmax() if len(m) and m.max() > HURDLE else None
        rows.append({col: float(col == pick) for col in closes.columns})
    return pd.DataFrame(rows, index=closes.index)


def sig_manual(decisions, idx):
    """Your calls: each decision applies from the latest close on or before its date."""
    w = pd.Series(np.nan, index=idx)
    for day, share in sorted(decisions.items()):
        share = float(share)
        if not 0 <= share <= 1:
            raise SystemExit(f"MANUAL_AGENTS: {day} must be between 0 and 1, got {share}")
        seen = idx[idx <= pd.Timestamp(day)]
        if len(seen):
            w.loc[seen[-1]] = share
    return w.ffill().fillna(0.0)


# --------------------------------- engine ---------------------------------------
def equity_since(W, R, s0):
    """Agent value from the close of s0 (all cash, first trades at that close) to the latest close."""
    after = R.index[R.index > s0]
    first = pd.Series([float(CAPITAL)], index=[s0])
    if len(after) == 0:
        return first
    H = W.shift(2).fillna(0.0).loc[after[0]:]          # held during each day
    Rw = R[W.columns].loc[after[0]:].fillna(0.0)
    turnover = H.diff().abs().sum(axis=1)
    turnover.iloc[0] = H.iloc[0].abs().sum()             # first trades, made at the close of s0
    r = (H * Rw).sum(axis=1) + (1 - H.sum(axis=1)) * CASH_DAILY - turnover * COST_PER_SIDE
    return pd.concat([first, CAPITAL * (1 + r).cumprod()])


def label(row):
    row = row[row > 1e-9]
    if row.empty:
        return "Cash"
    if len(row) == 1 and row.iloc[0] > 1 - 1e-9:
        return row.index[0]
    return " + ".join(f"{v:.0%} {k}" for k, v in row.items())


def rupees(x):
    if x >= 1e7:
        return f"Rs {x / 1e7:,.2f} crore"
    if x >= 1e5:
        return f"Rs {x / 1e5:,.2f} lakh"
    return f"Rs {x:,.0f}"


def reasons(closes, latest, manual):
    n = closes["NIFTY 50"]
    c, a200, a50, a5, r2 = (n.iloc[-1], sma(n, 200).iloc[-1], sma(n, 50).iloc[-1],
                            sma(n, 5).iloc[-1], rsi(n, 2).iloc[-1])
    mom = (closes / closes.shift(LOOKBACK) - 1).iloc[-1].dropna().sort_values(ascending=False)
    decides = ("decided at today's close" if latest in month_end_days(closes.index)
               else f"next decision on the last trading day of {latest:%B}")
    up = c > a200
    why = {
        "Cash only": "Never buys. Earns the liquid-fund rate. This is the bar every agent must beat.",
        "Buy & hold": "Bought at the first close and never sells.",
        "200-day trend": (f"Nifty {c:,.0f} is {'ABOVE' if up else 'BELOW'} its 200-day average {a200:,.0f}, "
                          f"so it wants {'Nifty' if up else 'cash'}."),
        "Golden cross": (f"50-day average {a50:,.0f} is {'ABOVE' if a50 > a200 else 'BELOW'} the 200-day "
                         f"average {a200:,.0f}, so it wants {'Nifty' if a50 > a200 else 'cash'}."),
        "RSI(2) dip-buy": (f"RSI(2) is {r2:.0f}. It buys when RSI(2) is below 10 while Nifty is above its "
                           f"200-day average ({'yes' if up else 'no'} today) and sells when Nifty closes "
                           f"above its 5-day average {a5:,.0f}."),
        "Momentum rotation": ("6-month returns: " + ", ".join(f"{k} {v:+.1%}" for k, v in mom.items())
                              + f". The best one must beat cash ({HURDLE:.1%}) to be bought; {decides}."),
    }
    for name, decisions in manual.items():
        if decisions:
            day = max(decisions)
            why[name] = f"Latest call ({day}): {float(decisions[day]):.0%} in Nifty 50."
    return why


def action_text(before, after, past=False):
    """Plain words for a change in holdings, e.g. 'Buy NIFTY 50' or 'Sold to cash'."""
    b, a = label(before), label(after)
    if b == "Cash":
        return ("Bought " if past else "Buy ") + a
    if a == "Cash":
        return "Sold to cash" if past else "Sell to cash"
    return ("Switched to " if past else "Switch to ") + a


def load_claude_log():
    """Claude's saved decisions, oldest first (empty if the file doesn't exist yet)."""
    if not os.path.exists(CLAUDE_FILE):
        return []
    with open(CLAUDE_FILE, encoding="utf-8") as f:
        return sorted(json.load(f), key=lambda d: d["date"])


def build_agents(closes):
    nifty, idx = closes["NIFTY 50"], closes.index
    agents = {
        "Cash only": sig_cash(nifty).to_frame("NIFTY 50"),
        "Buy & hold": sig_buy_hold(nifty).to_frame("NIFTY 50"),
        "200-day trend": sig_trend(nifty).to_frame("NIFTY 50"),
        "Golden cross": sig_golden_cross(nifty).to_frame("NIFTY 50"),
        "RSI(2) dip-buy": sig_rsi2(nifty).to_frame("NIFTY 50"),
        "Momentum rotation": weights_rotation(closes),
    }
    manual = {k: dict(v) for k, v in MANUAL_AGENTS.items() if v}
    claude = {d["date"]: d["position"] for d in load_claude_log()}
    if claude:
        manual.setdefault("Claude", {}).update(claude)
    for name, decisions in manual.items():
        agents[name] = sig_manual(decisions, idx).to_frame("NIFTY 50")
    return agents, manual


def compute(closes=None):
    """Everything the console report and the web page show, as plain Python data."""
    closes = load_all() if closes is None else closes
    R = closes / closes.shift(1) - 1
    nifty, idx = closes["NIFTY 50"], closes.index
    latest = idx[-1]
    agents, manual = build_agents(closes)
    res = {
        "latest": latest,
        "agents": agents,
        "manual": manual,
        "why": reasons(closes, latest, manual),
        "market": {"close": nifty.iloc[-1], "change": nifty.iloc[-1] / nifty.iloc[-2] - 1,
                   "sma200": sma(nifty, 200).iloc[-1], "sma50": sma(nifty, 50).iloc[-1],
                   "sma5": sma(nifty, 5).iloc[-1], "rsi2": rsi(nifty, 2).iloc[-1]},
        "started": False,
        "claude_log": list(reversed(load_claude_log())),   # newest first
    }
    if res["claude_log"]:
        d = res["claude_log"][0]
        text = f"Latest decision ({d['date']}): {d['position']:.0%} in Nifty 50. {d.get('summary', '')}".strip()
        if d.get("go_to_cash_if"):
            text += f" Goes to cash if {d['go_to_cash_if'].rstrip('.')}."
        if d.get("go_fully_in_if"):
            text += f" Goes fully in if {d['go_fully_in_if'].rstrip('.')}."
        res["why"]["Claude"] = text
    started = idx[idx >= pd.Timestamp(START)]
    if len(started) == 0:  # paper trading has not begun yet
        res["plan"] = {name: label(W.iloc[-1]) for name, W in agents.items()}
        return res

    s0 = started[0]
    rows, values, trades, positions = {}, {}, [], {}
    for name, W in agents.items():
        eq = equity_since(W, R, s0)
        values[name] = eq
        P = W.shift(1).fillna(0.0).loc[s0:]                # position after each close
        prev = P.shift(1)
        prev.iloc[0] = 0.0                                  # all cash before the start
        changed = (P - prev).abs().sum(axis=1) > 1e-9
        positions[name] = P
        for day in P.index[changed.values]:
            trades.append({"date": day, "agent": name, "what": action_text(prev.loc[day], P.loc[day], past=True),
                           "nifty": float(nifty.loc[day])})
        now, plan = P.iloc[-1], W.iloc[-1]
        rows[name] = {
            "holding": label(now),
            "value": float(eq.iloc[-1]),
            "since_start": float(eq.iloc[-1] / CAPITAL - 1),
            "worst_fall": float((eq / eq.cummax() - 1).min()),
            "trades": int(changed.sum()),
            "today": action_text(prev.iloc[-1], now, past=True) if changed.iloc[-1] else None,
            "next": action_text(now, plan) if (plan - now).abs().sum() > 1e-9 else None,
        }
    board = pd.DataFrame(rows).T
    board["value"] = board["value"].astype(float)
    res.update(started=True, s0=s0, days=len(idx[idx >= s0]),
               board=board.sort_values("value", ascending=False),
               values=pd.DataFrame(values),
               positions=positions,
               trades=sorted(trades, key=lambda t: (t["date"], t["agent"]), reverse=True))
    return res


def main():
    res = compute()
    m, latest = res["market"], res["latest"]
    print(f"\nNifty 50 closed at {m['close']:,.2f} on {latest.date()} ({m['change']:+.2%} on the day)")

    if not res["started"]:
        print(f"\nPAPER ARENA starts on {START}. Each agent gets {rupees(CAPITAL)} of virtual cash and will "
              f"take these positions at the first close:\n")
        for name, plan in res["plan"].items():
            print(f"  {name:<18} -> {plan:<14} {res['why'][name]}")
        print("\nRun this again each evening after about 8 pm IST once paper trading starts.")
        return

    b = res["board"]
    shown = pd.DataFrame({
        "Holding now": b["holding"],
        "Value": b["value"].map(rupees),
        "Since start": b["since_start"].map(lambda v: f"{v:+.2%}"),
        "Worst fall": b["worst_fall"].map(lambda v: f"{v:.1%}"),
        "Trades": b["trades"],
        "Traded today": b["today"].fillna("-"),
        "At next close": b["next"].fillna("Hold"),
    })
    print(f"\nPAPER ARENA | started {res['s0'].date()} | day {res['days']} | each agent began with "
          f"{rupees(CAPITAL)}\n")
    print(shown.to_string())
    print("\nWHY EACH AGENT IS DOING WHAT IT DOES")
    for name in b.index:
        print(f"  {name}: {res['why'][name]}")

    log = res["values"].round(2)
    log.index.name = "Date"
    log.to_csv(SAVE_LOG)
    if len(log) >= 2:
        fig, ax = plt.subplots(figsize=(10, 5))
        for name in log.columns:
            style = dict(color="grey", ls="--", lw=1) if name == "Cash only" else dict(lw=1.6)
            ax.plot(log.index, log[name], label=name, **style)
        ax.set_title(f"Paper arena since {res['s0'].date()} - virtual money, for learning only")
        ax.set_ylabel("Value (Rs)")
        ax.grid(alpha=0.3)
        ax.legend(fontsize=9)
        fig.autofmt_xdate()
        fig.tight_layout()
        fig.savefig(SAVE_CHART, dpi=130)
        if matplotlib.get_backend().lower() != "agg":
            plt.show()
    print(f"\nSaved {SAVE_LOG}" + (f" and {SAVE_CHART}" if len(log) >= 2 else ""))
    print("Journal tonight: which agents traded, why, and would you have done the same? "
          "Add your own call to MANUAL_AGENTS.")


if __name__ == "__main__":
    main()
