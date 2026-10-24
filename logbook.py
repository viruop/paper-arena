"""
logbook.py - the arena's permanent record.

Each run adds the newest days to these files and never rewrites old rows, so past results
can't silently change:

  logs/daily.csv          one row per agent per day: holding, value, return since start, trade
  logs/trades.csv         every trade, with Nifty 50's close that day
  decisions/snapshots/    the data snapshot behind each Claude decision
  logs/journal.md         your own notes (you edit this one)

If a later replay of the arena disagrees with the saved rows, for example because the data
source corrected an old price, the page shows a warning. The saved log stays the official record.

FOR LEARNING ONLY. No real orders are placed.
"""

import csv
import os

import pandas as pd

import paper_arena as pa

LOG_DIR = "logs"
DAILY = os.path.join(LOG_DIR, "daily.csv")
TRADES = os.path.join(LOG_DIR, "trades.csv")
SNAPSHOT_DIR = os.path.join("decisions", "snapshots")
DAILY_COLS = ["date", "agent", "holding", "value", "since_start", "trade", "nifty_close"]
TRADE_COLS = ["date", "agent", "trade", "nifty_close"]


def read(path, cols):
    if not os.path.exists(path):
        return pd.DataFrame(columns=cols)
    return pd.read_csv(path, dtype=str, keep_default_na=False)


def append(path, cols, rows):
    if not rows:
        return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    new_file = not os.path.exists(path)
    with open(path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=cols, lineterminator="\n")
        if new_file:
            writer.writeheader()
        writer.writerows(rows)


def update(res, closes):
    """Add every day after the last saved one. Returns (daily rows added, trades added)."""
    if not res["started"]:
        return 0, 0
    nifty = closes["NIFTY 50"]
    saved = read(DAILY, DAILY_COLS)
    last = pd.Timestamp(saved["date"].max()) if len(saved) else None
    traded = {(t["date"], t["agent"]): t["what"] for t in res["trades"]}
    rows = []
    for day in res["values"].index:
        if last is not None and day <= last:
            continue
        for agent in res["values"].columns:
            value = float(res["values"].at[day, agent])
            rows.append({
                "date": day.date().isoformat(),
                "agent": agent,
                "holding": pa.label(res["positions"][agent].loc[day]),
                "value": f"{value:.2f}",
                "since_start": f"{value / pa.CAPITAL - 1:.6f}",
                "trade": traded.get((day, agent), ""),
                "nifty_close": f"{nifty.loc[day]:.2f}",
            })
    append(DAILY, DAILY_COLS, rows)
    trade_rows = [{"date": t["date"].date().isoformat(), "agent": t["agent"], "trade": t["what"],
                   "nifty_close": f"{t['nifty']:.2f}"}
                  for t in sorted(res["trades"], key=lambda t: (t["date"], t["agent"]))
                  if last is None or t["date"] > last]
    append(TRADES, TRADE_COLS, trade_rows)
    return len(rows), len(trade_rows)


def drift(res, tolerance=1.0):
    """Saved rows whose value differs from tonight's replay by more than `tolerance` rupees."""
    if not res.get("started") or not os.path.exists(DAILY):
        return None
    diffs = []
    for row in read(DAILY, DAILY_COLS).itertuples(index=False):
        day = pd.Timestamp(row.date)
        if row.agent in res["values"].columns and day in res["values"].index:
            gap = abs(float(res["values"].at[day, row.agent]) - float(row.value))
            if gap > tolerance:
                diffs.append((gap, day, row.agent))
    if not diffs:
        return None
    gap, day, agent = max(diffs)
    return {"rows": len(diffs), "largest": gap, "date": day, "agent": agent}


def summary():
    """First and last saved day and the number of saved trades, for the page."""
    saved = read(DAILY, DAILY_COLS)
    if not len(saved):
        return None
    return {"first": pd.Timestamp(saved["date"].min()), "last": pd.Timestamp(saved["date"].max()),
            "days": saved["date"].nunique(), "trades": len(read(TRADES, TRADE_COLS))}


def snapshot_path(date):
    return os.path.join(SNAPSHOT_DIR, f"{date}.txt")


def save_snapshot(date, text, header):
    """Save what a decision was based on. Never overwrites an existing snapshot."""
    path = snapshot_path(date)
    if os.path.exists(path):
        return False
    os.makedirs(SNAPSHOT_DIR, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(header.rstrip() + "\n\n" + text.rstrip() + "\n")
    return True


def ensure_snapshot(closes, res):
    """A decision pasted in from chat has no snapshot yet. Record the data as of its close,
    but only while that close is still the newest in the data, so nothing later leaks in."""
    import claude_agent as ca
    import market_context as mc
    log = ca.load_log()
    latest = res["latest"].date().isoformat()
    if not any(d["date"] == latest for d in log) or os.path.exists(snapshot_path(latest)):
        return False
    earlier = [d for d in log if d["date"] != latest]
    text = ca.snapshot(closes, res, earlier, mc.context())
    return save_snapshot(latest, text, f"Data as of the close of {latest}, recorded by the nightly run "
                                       "after this decision was saved. News searches aren't included.")


def main():
    closes = pa.load_all()
    res = pa.compute(closes)
    added, trades = update(res, closes)
    snap = ensure_snapshot(closes, res)
    print(f"Logged {added} daily rows and {trades} trades." + (" Saved a decision snapshot." if snap else ""))
    found = drift(res)
    if found:
        rows = f"{found['rows']} {'row' if found['rows'] == 1 else 'rows'}"
        print(f"  ! Replay differs from the saved log on {rows} (largest Rs {found['largest']:,.0f}).")


if __name__ == "__main__":
    main()
