"""
logbook.py - the arena's permanent record.

Each run adds the newest days to these files and never rewrites old rows, so past results
can't silently change:

  logs/daily.csv          one row per agent per day: holding, value, return since start, trade
  logs/trades.csv         every trade, with Nifty 50's close that day
  logs/starts.json        when each newer agent starts (written once, the first time it's seen)
  decisions/snapshots/    the data snapshot behind each Claude decision
  logs/journal.md         your own notes (you edit this one)

Each group of agents is logged once its prices for a day are final: the Nifty agents when the
day's close is in, the F&O agents once NSE's option prices are saved, and the gold and
multi-asset agents once every ETF price is in. So rows for different groups can arrive on
different nights. If a later replay disagrees with saved rows, for example because a data
source corrected an old price, the page shows a warning. The saved log stays the official record.

FOR LEARNING ONLY. No real orders are placed.
"""

import csv
import os

import numpy as np
import pandas as pd

import paper_arena as pa
import starts

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


# ------------------------------ the agents' results -------------------------------
def nifty_block(res):
    """The original Nifty agents (and Claude) from paper_arena."""
    if not res["started"]:
        return None
    values = res["values"]
    labels = {a: pd.Series({d: pa.label(res["positions"][a].loc[d]) for d in values.index}) for a in values.columns}
    return {"values": values, "labels": labels, "trades": [dict(t) for t in res["trades"]], "final": res["latest"]}


def extra_block(res):
    """The F&O or the gold and multi-asset agents."""
    if not res or not res.get("started"):
        return None
    return {"values": res["values"], "labels": res["labels"], "trades": [dict(t) for t in res["trades"]],
            "final": res["final_until"]}


def fno_results():
    """The F&O agents' results, or None if they can't be computed tonight."""
    try:
        import fno_arena
        return fno_arena.compute()
    except Exception as exc:  # keep logging the other agents even if the F&O part fails
        print(f"  ! F&O agents skipped: {exc}")
        return None


def asset_results():
    """The gold and multi-asset agents' results, or None if they can't be computed tonight."""
    try:
        import asset_arena
        return asset_arena.compute()
    except Exception as exc:  # keep logging the other agents even if this part fails
        print(f"  ! Gold and multi-asset agents skipped: {exc}")
        return None


def register_new_agents():
    """Give every newer agent seen for the first time its start date (the next weekday)."""
    names = []
    for module, attr in (("fno_arena", "RULES"), ("asset_arena", "AGENTS")):
        try:
            names += list(getattr(__import__(module), attr))
        except Exception as exc:
            print(f"  ! {module} not loaded: {exc}")
    return starts.register(names)


def merged(res, fres=None, ares=None):
    """Every group of agents, each with its own last final day."""
    blocks = [b for b in (nifty_block(res), extra_block(fres), extra_block(ares)) if b]
    return blocks or None


# --------------------------------- writing the log --------------------------------
def update(view, closes):
    """Add each agent's final days after its last saved one. Returns (daily rows added, trades added)."""
    if not view:
        return 0, 0
    nifty = closes["NIFTY 50"]
    saved = read(DAILY, DAILY_COLS)
    last = {a: pd.Timestamp(d) for a, d in saved.groupby("agent")["date"].max().items()} if len(saved) else {}
    rows, trade_rows = [], []
    for block in view:
        traded = {}
        for t in block["trades"]:
            traded.setdefault((t["date"], t["agent"]), []).append(t["what"])
        for agent in block["values"].columns:
            since = last.get(agent)
            labels = block["labels"][agent]
            for day in block["values"].index:
                if day > block["final"] or (since is not None and day <= since):
                    continue
                if labels.get(day, "") == "Not started yet":
                    continue
                value = float(block["values"].at[day, agent])
                close = nifty.get(day, np.nan)
                rows.append({
                    "date": day.date().isoformat(),
                    "agent": agent,
                    "holding": labels.get(day, ""),
                    "value": f"{value:.2f}",
                    "since_start": f"{value / pa.CAPITAL - 1:.6f}",
                    "trade": "; ".join(traded.get((day, agent), [])),
                    "nifty_close": "" if np.isnan(close) else f"{close:.2f}",
                })
        for t in block["trades"]:
            since = last.get(t["agent"])
            if (since is None or t["date"] > since) and t["date"] <= block["final"]:
                close = nifty.get(t["date"], t.get("nifty", np.nan))
                trade_rows.append({"date": t["date"].date().isoformat(), "agent": t["agent"], "trade": t["what"],
                                   "nifty_close": "" if close is None or np.isnan(close) else f"{close:.2f}"})
    rows.sort(key=lambda r: (r["date"], r["agent"]))
    trade_rows.sort(key=lambda r: (r["date"], r["agent"]))
    append(DAILY, DAILY_COLS, rows)
    append(TRADES, TRADE_COLS, trade_rows)
    return len(rows), len(trade_rows)


def drift(view, tolerance=1.0):
    """Saved rows whose value differs from tonight's replay by more than `tolerance` rupees."""
    if not view or not os.path.exists(DAILY):
        return None
    diffs = []
    for row in read(DAILY, DAILY_COLS).itertuples(index=False):
        day = pd.Timestamp(row.date)
        for block in view:
            values = block["values"]
            if row.agent in values.columns and day in values.index:
                gap = abs(float(values.at[day, row.agent]) - float(row.value))
                if gap > tolerance:
                    diffs.append((gap, day, row.agent))
                break
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


# ------------------------------- Claude's snapshots -------------------------------
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
    added_agents = register_new_agents()
    if added_agents:
        print(f"New agents start on {starts.load()[added_agents[0]]}: {', '.join(added_agents)}")
    closes = pa.load_all()
    res = pa.compute(closes)
    view = merged(res, fno_results(), asset_results())
    added, trades = update(view, closes)
    snap = ensure_snapshot(closes, res) if res["started"] else False
    print(f"Logged {added} daily rows and {trades} trades." + (" Saved a decision snapshot." if snap else ""))
    found = drift(view)
    if found:
        rows = f"{found['rows']} {'row' if found['rows'] == 1 else 'rows'}"
        print(f"  ! Replay differs from the saved log on {rows} (largest Rs {found['largest']:,.0f}).")


if __name__ == "__main__":
    main()
