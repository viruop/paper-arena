"""
data_health.py - checks the saved prices every night, so a result is never trusted on data that is stale,
gappy or wrong without it being said (added 16 Nov 2026, after an outside review asked for it).

What it checks, without changing any file:
  fresh     the last saved day is the last session that has closed: for Indian prices the NSE calendar
            (weekdays without the NSE holidays in data/events/calendar.csv), for the others weekdays,
            each after its own closing time. Sources known to run late get the grace written in FILES.
  complete  no NSE session missing from an Indian daily series in its last WINDOW sessions, and an NSE
            option file for every session since the first one (a missing file means the F&O agents
            used estimated prices that night). A day counts as a session when two Indian sources have it.
  clean     dates unique and in order; prices above zero; each day's high at or above its low; no close
            in the last WINDOW sessions moving more than the series' BIG move from the one before. A big
            move is a warning to check it elsewhere: market_data.drop_spikes already removes a bad price
            that jumps and comes straight back.
  agree     Nifty 50 from Yahoo (NIFTY50.csv) and from the index dataset (indices/NIFTY_50.csv) within
            0.05% of each other on their last 20 common days.
  version   rows, first and last day, and the first 12 characters of each file's SHA-256, so a result can
            be tied to the exact data it was built from.

A failed check never stops the run or the page: the risk engine already refuses an order on a stale price,
and the arenas don't add a day they have no price for. Failures are printed in the run's log (as a GitHub
warning) and shown on the page under "Data checks".

--log-run adds one line per GitHub run to logs/runs.csv: when it started, how late it started against its
schedule (GitHub's scheduled runs often start late), what started it, the commit and the Python, pandas and
numpy versions, the last Nifty close saved, and how many checks failed. Only ever added to.

Run:  python data_health.py             print the checks
      python data_health.py --log-run   also add this run's line to logs/runs.csv (the nightly run does this)
FOR LEARNING ONLY. Nothing here places an order.
"""

import csv
import datetime as dt
import hashlib
import os
import platform
import sys

import numpy as np
import pandas as pd

MARKET = os.path.join("data", "market")
FNO = os.path.join("data", "fno")
RUNS = os.path.join("logs", "runs.csv")
RUN_COLS = ["started", "logged", "trigger", "scheduled", "late_min", "run_id", "commit", "python", "pandas",
            "numpy", "last_close", "failed", "warnings"]
WINDOW = 60                   # recent sessions checked for gaps and big moves
AGREE = 0.0005                # the two Nifty 50 sources may differ by 0.05%
NSE = ("Asia/Kolkata", "16:00")
FNO_AFTER = "22:00"           # NSE's option file counts as due from this time (IST), as in fno_prices.LOG_AFTER

# file in data/market: (name, calendar, time zone and time after which the day's bar is final,
#                       grace in sessions, biggest daily move before a warning, used by agents)
# Used by agents: a stale or broken file changes a paper result, so it fails; the rest only warn.
FILES = {
    "NIFTY50.csv": ("Nifty 50 (Yahoo)", "NSE", NSE, 0, 0.06, True),
    "NIFTYBEES.csv": ("NIFTYBEES", "NSE", NSE, 0, 0.06, True),
    "GOLDBEES.csv": ("GOLDBEES", "NSE", NSE, 0, 0.08, True),
    "SILVERBEES.csv": ("SILVERBEES", "NSE", NSE, 0, 0.12, True),
    "GOLD.csv": ("COMEX gold", "weekdays", ("America/New_York", "17:30"), 1, 0.08, True),
    "SILVER.csv": ("COMEX silver", "weekdays", ("America/New_York", "17:30"), 1, 0.12, True),
    "SP500.csv": ("S&P 500", "weekdays", ("America/New_York", "16:30"), 1, 0.06, True),
    "BRENT.csv": ("Brent crude", "weekdays", ("America/New_York", "17:30"), 1, 0.10, False),
    "USDINR.csv": ("Dollar-rupee", "weekdays", ("Europe/London", "23:59"), 1, 0.03, False),
    os.path.join("indices", "NIFTY_50.csv"): ("Nifty 50 (index dataset)", "NSE", NSE, 0, 0.06, False),
    os.path.join("indices", "NIFTY_BANK.csv"): ("Nifty Bank", "NSE", NSE, 0, 0.07, False),
    os.path.join("indices", "NIFTY_IT.csv"): ("Nifty IT", "NSE", NSE, 0, 0.08, False),
    os.path.join("indices", "NIFTY_PHARMA.csv"): ("Nifty Pharma", "NSE", NSE, 0, 0.07, False),
    os.path.join("indices", "NIFTY_MIDCAP_50.csv"): ("Nifty Midcap 50", "NSE", NSE, 0, 0.08, False),
    "breadth.csv": ("Nifty 50 breadth", "NSE", NSE, 2, None, False),      # the stock dataset runs a day or two late
    "fii_dii.csv": ("FII/DII flows", "NSE", NSE, 1, None, False),         # the dataset publishes a day late
    "NZDCAD_fed.csv": ("NZD/CAD (Federal Reserve)", "weekdays", ("America/New_York", "17:30"), 10, None, False),
}
SOURCES = ("NIFTY50.csv", os.path.join("indices", "NIFTY_50.csv"), "NIFTYBEES.csv", "GOLDBEES.csv")
AGREE_PAIR = ("NIFTY50.csv", os.path.join("indices", "NIFTY_50.csv"))


# ------------------------------------ calendars ------------------------------------
def nse_calendar():
    """(holidays, special sessions) from the event calendar, as sets of ISO dates; empty if unreadable."""
    try:
        import events
        cal = events.calendar(None)
        nse = cal[cal["market"].astype(str).str.upper().str.contains("NSE")]
        kind = nse["kind"].astype(str)
        return frozenset(nse.loc[kind == "holiday", "date"].astype(str)), frozenset(nse.loc[kind == "session", "date"].astype(str))
    except Exception:
        return frozenset(), frozenset()


def is_session(d, calendar, holidays=frozenset(), special=frozenset()):
    iso = d.date().isoformat()
    if calendar == "NSE":
        return iso in special or (d.weekday() < 5 and iso not in holidays)
    return d.weekday() < 5


def last_closed(now, calendar, zone, holidays=frozenset(), special=frozenset()):
    """The last day whose session has closed, by the exchange's own clock."""
    tz, cutoff = zone
    local = now.tz_convert(tz)
    d = local.tz_localize(None).normalize()
    if local.strftime("%H:%M") < cutoff:
        d -= pd.Timedelta(days=1)
    while not is_session(d, calendar, holidays, special):
        d -= pd.Timedelta(days=1)
    return d


def sessions_after(last, until, calendar, holidays=frozenset(), special=frozenset()):
    """Sessions after `last`, up to and including `until`."""
    days = pd.date_range(last + pd.Timedelta(days=1), until, freq="D") if until > last else []
    return [d for d in days if is_session(d, calendar, holidays, special)]


# ------------------------------------ the checks ------------------------------------
def version(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()[:12]


def read(path):
    df = pd.read_csv(path)
    df.index = pd.to_datetime(df.iloc[:, 0], errors="coerce", format="ISO8601")
    return df.iloc[:, 1:]


def check_file(rel, spec, now, holidays, special, sessions):
    name, calendar, zone, grace, big, agents = spec
    path = os.path.join(MARKET, rel)
    out = {"file": os.path.join(MARKET, rel), "name": name, "agents": agents, "rows": 0, "first": None,
           "last": None, "version": "", "problems": [], "warnings": []}
    bad = out["problems"] if agents else out["warnings"]
    if not os.path.exists(path):
        bad.append("file missing")
        return out
    out["version"] = version(path)
    try:
        df = read(path)
    except Exception as exc:
        out["problems"].append(f"can't be read ({exc.__class__.__name__})")
        return out
    out["rows"] = len(df)
    if df.index.isna().any():
        out["problems"].append(f"{int(df.index.isna().sum())} rows without a readable date")
        df = df[df.index.notna()]
    if not len(df):
        bad.append("no rows")
        return out
    out["first"], out["last"] = df.index.min(), df.index.max()
    if df.index.duplicated().any():
        out["problems"].append(f"{int(df.index.duplicated().sum())} dates saved twice")
    if not df.index.is_monotonic_increasing:
        out["problems"].append("dates out of order")
    df = df[~df.index.duplicated(keep="last")].sort_index()

    due = last_closed(now, calendar, zone, holidays, special)
    behind = sessions_after(out["last"], due, calendar, holidays, special)
    if len(behind) > grace:
        bad.append(f"{len(behind)} session{'s' if len(behind) != 1 else ''} behind: last day "
                   f"{out['last']:%d %b}, {due:%d %b} has closed")

    prices = df[[c for c in ("Open", "High", "Low", "Close") if c in df.columns]].tail(WINDOW)
    if len(prices.columns):
        nums = prices.apply(pd.to_numeric, errors="coerce")
        if nums.isna().any().any() or (nums <= 0).any().any():
            bad.append("a missing, zero or negative price in the last sessions")
        if {"High", "Low"} <= set(nums.columns):
            wrong = nums[nums["High"] < nums["Low"] * (1 - 1e-9)]
            if len(wrong):
                out["warnings"].append(f"high below low on {wrong.index[-1]:%d %b}")
        if big and "Close" in nums.columns:
            moves = nums["Close"].pct_change().dropna()
            for d, m in moves[moves.abs() > big].items():
                out["warnings"].append(f"close moved {m:+.1%} on {d:%d %b}: check it elsewhere".replace("-", "\u2212", 1)
                                       if m < 0 else f"close moved {m:+.1%} on {d:%d %b}: check it elsewhere")
    if calendar == "NSE" and sessions is not None:
        start = sessions[-WINDOW:][0] if len(sessions) else out["last"]
        missing = [d for d in sessions if start <= d <= out["last"] and d not in df.index]
        if missing:
            out["warnings"].append(f"{len(missing)} session{'s' if len(missing) != 1 else ''} missing "
                                   f"(latest {missing[-1]:%d %b})")
    return out


def check_fno(now, holidays, special, sessions):
    """The NSE option files: one per session since the first, each readable with prices."""
    out = {"file": FNO, "name": "NSE option prices (F&O)", "agents": True, "rows": 0, "first": None,
           "last": None, "version": "", "problems": [], "warnings": []}
    if not os.path.isdir(FNO):
        out["warnings"].append("no option files yet")
        return out
    files = sorted(f for f in os.listdir(FNO) if f.endswith(".csv"))
    days = []
    digest = hashlib.sha256()
    for f in files:
        path = os.path.join(FNO, f)
        with open(path, "rb") as fh:
            body = fh.read()
        digest.update(f.encode() + body)
        try:
            d = pd.Timestamp(f[:-4])
            df = pd.read_csv(path)
        except Exception:
            out["problems"].append(f"{f} can't be read")
            continue
        if not len(df) or "close" not in df.columns or (pd.to_numeric(df["close"], errors="coerce") < 0).any():
            out["problems"].append(f"{f} has no usable prices")
        days.append(d)
        out["rows"] += len(df)
    if not days:
        out["warnings"].append("no option files yet")
        return out
    out["version"] = digest.hexdigest()[:12]
    out["first"], out["last"] = min(days), max(days)
    due = last_closed(now, "NSE", ("Asia/Kolkata", FNO_AFTER), holidays, special)
    known = set(sessions or ())
    expected = [d for d in pd.date_range(out["first"], due, freq="D")
                if is_session(d, "NSE", holidays, special) and (d in known or d > max(known, default=d))]
    missing = [d for d in expected if d not in set(days)]
    if missing:
        out["problems"].append(f"{len(missing)} session{'s' if len(missing) != 1 else ''} without NSE's file "
                               f"(latest {missing[-1]:%d %b}): the F&O agents used estimated prices then")
    return out


def check_agree():
    """Nifty 50 from two sources, on their last 20 common days."""
    try:
        a, b = (read(os.path.join(MARKET, f))["Close"] for f in AGREE_PAIR)
    except Exception:
        return None
    a, b = a[~a.index.duplicated(keep="last")], b[~b.index.duplicated(keep="last")]
    both = pd.concat([a, b], axis=1, join="inner").dropna().tail(20)
    if not len(both):
        return "the two Nifty 50 sources have no day in common"
    gap = (both.iloc[:, 0] / both.iloc[:, 1] - 1).abs()
    if gap.max() > AGREE:
        d = gap.idxmax()
        return f"the two Nifty 50 sources differ by {gap.max():.2%} on {d:%d %b}"
    return None


def nse_sessions():
    """Days at least two Indian sources have: what NSE really traded, holidays included."""
    seen = []
    for rel in SOURCES:
        try:
            df = read(os.path.join(MARKET, rel))
            seen.append(pd.Series(1, index=df.index[df.index.notna()].unique()))
        except Exception:
            continue
    if not seen:
        return []
    count = pd.concat(seen, axis=1, sort=True).fillna(0).sum(axis=1)
    return sorted(count[count >= 2].index)


def check(now=None):
    """Every check, for the page and the run's log."""
    now = pd.Timestamp(now or pd.Timestamp.now(tz="UTC"))
    now = now.tz_localize("UTC") if now.tzinfo is None else now.tz_convert("UTC")
    holidays, special = nse_calendar()
    sessions = nse_sessions()
    files = [check_file(rel, spec, now, holidays, special, sessions) for rel, spec in FILES.items()]
    files.append(check_fno(now, holidays, special, sessions))
    disagree = check_agree()
    if disagree:
        files[0]["warnings"].append(disagree)
    failed = sum(bool(f["problems"]) for f in files)
    warned = sum(bool(f["warnings"]) and not f["problems"] for f in files)
    nifty = next((f["last"] for f in files if f["name"] == "Nifty 50 (Yahoo)"), None)
    return {"checked": now, "files": files, "failed": failed, "warnings": warned, "last_close": nifty,
            "versions": versions()}


def versions():
    return {"python": platform.python_version(), "pandas": pd.__version__, "numpy": np.__version__}


# ------------------------------------ the run log ------------------------------------
def scheduled_time(cron, started):
    """The UTC time a GitHub schedule ("M H * * days") was due, on the day the run started or the day before."""
    try:
        minute, hour = (int(x) for x in cron.split()[:2])
    except (AttributeError, ValueError):
        return None
    due = started.normalize() + pd.Timedelta(hours=hour, minutes=minute)
    return due - pd.Timedelta(days=1) if due > started else due


def utc(text):
    """A UTC time from text, or None when there is none."""
    if not text:
        return None
    try:
        t = pd.Timestamp(text)
    except (TypeError, ValueError):
        return None
    if pd.isna(t):
        return None
    return t.tz_localize("UTC") if t.tzinfo is None else t.tz_convert("UTC")


def stamp(t):
    return t.strftime("%Y-%m-%dT%H:%M:%SZ") if t is not None else ""


def run_row(result, env=None, now=None):
    env = os.environ if env is None else env
    now = utc(now) if now is not None else pd.Timestamp.now(tz="UTC")
    started = utc(env.get("RUN_STARTED")) or now
    due = scheduled_time(env.get("RUN_SCHEDULE", ""), started) if env.get("RUN_SCHEDULE") else None
    v = result["versions"]
    return {"started": stamp(started), "logged": stamp(now), "trigger": env.get("GITHUB_EVENT_NAME", "local"),
            "scheduled": stamp(due), "late_min": "" if due is None else str(int((started - due).total_seconds() // 60)),
            "run_id": env.get("GITHUB_RUN_ID", ""), "commit": env.get("GITHUB_SHA", "")[:7],
            "python": v["python"], "pandas": v["pandas"], "numpy": v["numpy"],
            "last_close": "" if result["last_close"] is None else f"{result['last_close']:%Y-%m-%d}",
            "failed": str(result["failed"]), "warnings": str(result["warnings"])}


def log_run(result, path=None, env=None, now=None):
    """Add this run's line to logs/runs.csv. Only ever added to."""
    path = path or RUNS
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    new = not os.path.exists(path) or os.path.getsize(path) == 0
    row = run_row(result, env, now)
    with open(path, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=RUN_COLS)
        if new:
            w.writeheader()
        w.writerow(row)
    return row


def runs(path=None, last=10):
    path = path or RUNS
    if not os.path.exists(path):
        return []
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))[-last:][::-1]


def summary(now=None, runs_path=None):
    """For the page: every file's checks and the last runs, newest first."""
    out = check(now)
    out["runs"] = runs(runs_path)
    return out


# ------------------------------------ command line ------------------------------------
def describe(result):
    lines = [f"Data checks, {result['checked'].tz_convert('Asia/Kolkata'):%d %b %Y %H:%M} IST: "
             f"{result['failed']} failed, {result['warnings']} with warnings, {len(result['files'])} checked"]
    for f in result["files"]:
        state = "FAIL" if f["problems"] else "warn" if f["warnings"] else "ok"
        last = f"{f['last']:%Y-%m-%d}" if f["last"] is not None else "-"
        lines.append(f"  {state:4}  {f['name']:28} last {last}  rows {f['rows']:>6}  version {f['version'] or '-'}")
        lines += [f"        ! {p}" for p in f["problems"]] + [f"        - {w}" for w in f["warnings"]]
    return "\n".join(lines)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    result = check()
    print(describe(result))
    for f in result["files"]:
        for p in f["problems"]:
            print(f"::warning title=Data check failed::{f['name']}: {p}")
    if "--log-run" in argv:
        row = log_run(result)
        late = f", {row['late_min']} min after its schedule" if row["late_min"] else ""
        print(f"Run logged in {RUNS}: started {row['started']}{late} ({row['trigger']})")


if __name__ == "__main__":
    main()
