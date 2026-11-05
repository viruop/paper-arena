"""
events.py - market events: what's scheduled, what happened, and how markets moved around it.

Two files in data/events/, both only ever added to. A later row with the same id replaces an
earlier one, for example a moved date or a corrected number; nothing is edited or deleted.

  calendar.csv  scheduled events: central bank decisions, big data releases, elections, the
                Budget, exchange holidays and special sessions (such as Diwali's Muhurat trading).
                Columns: id, date, time_ist, end_ist, country, kind, market, event, importance,
                status, source, added_at, added_by
  log.csv       what happened, scheduled or not (an election result abroad, a war, an oil shock),
                with the time it first became public.
                Columns: id, known_at, country, kind, headline, detail, calendar_id, source,
                added_at, added_by

Claude adds rows each night with the market-events skill. This file reads them for the page and
for the Claude agent, which only ever sees rows that had been added when it decided. How markets
moved is measured from the saved daily prices in data/market/: from the last close before the
event became public to the first close after it (and three closes after it, for Nifty), for
Nifty 50, COMEX gold, Brent crude, the rupee and the S&P 500. Other news on the same day is mixed
in, so one move proves little; many events of the same kind show a pattern.

The exchange holidays and special sessions also tell the Claude agent when the next session
opens (claude_agent.status), so a decision is never made after the session it's filled in.

Run:  python events.py                  what's coming up and what happened recently
      python events.py --check          check both files; exits with 1 if something is wrong
      python events.py --check --base DIR   also check that rows were only added to DIR's copies
FOR LEARNING ONLY. Not investment advice.
"""

import datetime as dt
import os
import re
import sys

import pandas as pd

FOLDER = os.path.join("data", "events")
CALENDAR = os.path.join(FOLDER, "calendar.csv")
LOG = os.path.join(FOLDER, "log.csv")
CAL_COLS = ["id", "date", "time_ist", "end_ist", "country", "kind", "market", "event", "importance", "status",
            "source", "added_at", "added_by"]
LOG_COLS = ["id", "known_at", "country", "kind", "headline", "detail", "calendar_id", "source", "added_at",
            "added_by"]
KINDS = ("central_bank", "data", "election", "budget", "policy", "geopolitics", "oil", "earnings", "holiday",
         "session", "other")
IST = "Asia/Kolkata"
NSE_OPEN = "09:00"            # NSE's pre-open starts at 9:00; regular trading runs 9:15 to 15:30
MARKET_FOLDER = os.path.join("data", "market")

# Saved daily prices for the reactions: name: (file in data/market, time zone, local closing time).
# Yahoo dates a bar by its exchange's local day; the closing times are close enough to decide
# whether a bar ended before or after an event.
MARKETS = {
    "Nifty 50": ("NIFTY50", "Asia/Kolkata", "15:30"),
    "Gold": ("GOLD", "America/New_York", "17:00"),
    "Brent": ("BRENT", "America/New_York", "17:00"),
    "USD/INR": ("USDINR", "Europe/London", "23:00"),
    "S&P 500": ("SP500", "America/New_York", "16:00"),
}
NIFTY3 = "Nifty 50, 3 closes"


# ----------------------------------- reading ------------------------------------
def _read(path, cols):
    if not os.path.exists(path):
        return pd.DataFrame(columns=cols)
    df = pd.read_csv(path, dtype=str, keep_default_na=False)
    for c in cols:
        if c not in df.columns:
            df[c] = ""
    return df[cols].apply(lambda s: s.str.strip())


def utc(text):
    """A UTC timestamp from an ISO date and time (NaT if it can't be read)."""
    t = pd.to_datetime(text, utc=True, errors="coerce")
    return t


def as_utc(when):
    if when is None:
        return None
    t = pd.Timestamp(when)
    return t.tz_localize("UTC") if t.tzinfo is None else t.tz_convert("UTC")


def newest(df, as_of=None):
    """The last row for each id, among the rows that had been added by as_of."""
    if not len(df):
        return df
    if as_of is not None:
        df = df[pd.to_datetime(df["added_at"], utc=True, errors="coerce") <= as_utc(as_of)]
    return df.drop_duplicates("id", keep="last")


def start_of(date, time_ist):
    """A calendar row's start in UTC: its date at time_ist, or the start of that day in India."""
    return pd.Timestamp(f"{date} {time_ist or '00:00'}").tz_localize(IST).tz_convert("UTC")


def calendar(as_of=None, path=CALENDAR):
    """Scheduled events as known at as_of (all of them if None), without cancelled ones."""
    df = newest(_read(path, CAL_COLS), as_of)
    df = df[df["status"].str.lower() != "cancelled"].copy()
    starts = []
    for d, t in zip(df["date"], df["time_ist"]):
        try:
            starts.append(start_of(d, t) if re.fullmatch(r"\d{4}-\d{2}-\d{2}", d) else pd.NaT)
        except ValueError:          # an unreadable date or time; --check reports it
            starts.append(pd.NaT)
    df["at"] = pd.to_datetime(pd.Series(starts, index=df.index, dtype="object"), utc=True)
    return df.dropna(subset=["at"]).sort_values("at")


def log(as_of=None, path=LOG):
    """What happened, as known at as_of: events that had become public and been logged by then."""
    df = newest(_read(path, LOG_COLS), as_of).copy()
    df["at"] = utc(df["known_at"])
    df = df.dropna(subset=["at"])
    if as_of is not None:
        df = df[df["at"] <= as_utc(as_of)]
    return df.sort_values("at")


def upcoming(as_of, days=7, path=CALENDAR):
    """Scheduled events from as_of to `days` later. Events without a time count for their whole day."""
    now = as_utc(as_of)
    df = calendar(now, path)
    today = now.tz_convert(IST).normalize().tz_convert("UTC")
    timed = df["time_ist"] != ""
    keep = ((timed & (df["at"] >= now)) | (~timed & (df["at"] >= today))) & (df["at"] <= now + pd.Timedelta(days=days))
    return df[keep]


def recent(as_of, days=7, path=LOG):
    """Events that became public in the `days` before as_of."""
    now = as_utc(as_of)
    df = log(now, path)
    return df[df["at"] >= now - pd.Timedelta(days=days)]


# ------------------------------- sessions (NSE) ---------------------------------
def next_open(day, path=CALENDAR):
    """When the next NSE session after `day` opens, in IST: a special session (such as Muhurat
    trading) if one comes first, otherwise the next weekday that isn't an exchange holiday, at
    9:00. Uses every holiday and session in the calendar. None if the calendar can't be read."""
    try:
        cal = calendar(None, path)
    except Exception:
        return None
    nse = cal[cal["market"].str.upper().str.contains("NSE")]
    holidays = set(nse.loc[nse["kind"] == "holiday", "date"])
    sessions = nse[nse["kind"] == "session"]
    d = pd.Timestamp(day).normalize() + pd.Timedelta(days=1)
    for _ in range(40):
        key = d.date().isoformat()
        starts = [t for t in sessions.loc[sessions["date"] == key, "time_ist"] if t]
        if starts:
            return pd.Timestamp(f"{key} {min(starts)}").tz_localize(IST).to_pydatetime()
        if d.weekday() < 5 and key not in holidays:
            return pd.Timestamp(f"{key} {NSE_OPEN}").tz_localize(IST).to_pydatetime()
        d += pd.Timedelta(days=1)
    return None


# ---------------------------------- reactions -----------------------------------
_PRICES = {}


def prices(name, folder=MARKET_FOLDER):
    """One market's saved daily closes, indexed by each bar's closing time in UTC."""
    key = (name, folder)
    if key not in _PRICES:
        file, tz, close = MARKETS[name]
        path = os.path.join(folder, f"{file}.csv")
        s = pd.Series(dtype=float, index=pd.DatetimeIndex([], tz="UTC"))
        if os.path.exists(path):
            df = pd.read_csv(path)
            if len(df) and {"Date", "Close"} <= set(df.columns):
                days = pd.to_datetime(df["Date"]).dt.strftime("%Y-%m-%d")
                when = pd.to_datetime(days + " " + close).dt.tz_localize(tz).dt.tz_convert("UTC")
                s = pd.Series(pd.to_numeric(df["Close"], errors="coerce").values, index=pd.DatetimeIndex(when))
                s = s[s > 0].sort_index()
                s = s[~s.index.duplicated(keep="last")]
        _PRICES[key] = s
    return _PRICES[key]


def reaction(known_at, as_of=None, folder=MARKET_FOLDER):
    """Each market's move from its last close before the event became public to its first close
    after, using only closes that had happened by as_of. Nifty also gets the move to its third close."""
    t = as_utc(known_at)
    limit = as_utc(as_of)
    out = {}
    for name in MARKETS:
        s = prices(name, folder)
        if limit is not None:
            s = s[s.index <= limit]
        before, after = s[s.index <= t], s[s.index > t]
        out[name] = after.iloc[0] / before.iloc[-1] - 1 if len(before) and len(after) else None
        if name == "Nifty 50":
            out[NIFTY3] = after.iloc[2] / before.iloc[-1] - 1 if len(before) and len(after) >= 3 else None
    return out


# ------------------------------------ text --------------------------------------
def ist_text(t, with_time=True):
    t = pd.Timestamp(t).tz_convert(IST)
    return t.strftime("%a %d %b %H:%M" if with_time else "%a %d %b")


def when_text(row):
    """A calendar row's day and time in IST, such as 'Sun 08 Nov 14:05-15:30'."""
    text = ist_text(row["at"], bool(row["time_ist"]))
    return text + (f"-{row['end_ist']}" if row["time_ist"] and row["end_ist"] else "")


def moves_text(r):
    parts = []
    for name in MARKETS:
        if r.get(name) is not None:
            extra = f" (3 closes {r[NIFTY3]:+.1%})" if name == "Nifty 50" and r.get(NIFTY3) is not None else ""
            parts.append(f"{name} {r[name]:+.1%}{extra}")
    return ", ".join(parts) if parts else "no close after it yet"


def describe(as_of=None, days=7, cal_path=CALENDAR, log_path=LOG, folder=MARKET_FOLDER):
    """Lines for the Claude agent's snapshot: what's scheduled in the next `days` and what happened
    in the last `days`, as known at as_of. Empty when there are no event files yet."""
    if not (os.path.exists(cal_path) or os.path.exists(log_path)):
        return []
    now = as_utc(as_of) if as_of is not None else pd.Timestamp.now(tz="UTC")
    lines = [f"Scheduled events in the next {days} days (IST, from data/events/calendar.csv):"]
    up = upcoming(now, days, cal_path)
    for _, r in up.iterrows():
        place = r["market"] if r["kind"] in ("holiday", "session") and r["market"] else r["country"]
        lines.append(f"  {when_text(r)}: {r['event']} ({place}, {r['kind'].replace('_', ' ')}"
                     + (f", {r['importance']} importance" if r["importance"] else "") + ")")
    if not len(up):
        lines.append("  None listed.")
    lines.append(f"What happened in the last {days} days (when it became public, IST; each market's move from its "
                 "last close before it to its first close after it):")
    rec = recent(now, days, log_path)
    for _, r in rec.iloc[::-1].iterrows():
        detail = f" {r['detail'].rstrip('.')}." if r["detail"] else ""
        lines.append(f"  {ist_text(r['at'])}: {r['headline'].rstrip('.')}.{detail} "
                     f"Moves: {moves_text(reaction(r['at'], now, folder))}.")
    if not len(rec):
        lines.append("  Nothing logged.")
    return lines


# ------------------------------------ check -------------------------------------
TIME = re.compile(r"(\d{2}):(\d{2})")


def _time_ok(t):
    m = TIME.fullmatch(t)
    return not t or bool(m and int(m.group(1)) < 24 and int(m.group(2)) < 60)


def check(cal_path=CALENDAR, log_path=LOG, base=None):
    """Problems in the two files, as a list of sentences (empty if both are fine)."""
    problems = []
    now = pd.Timestamp.now(tz="UTC")
    cal = _read(cal_path, CAL_COLS)
    for i, r in cal.iterrows():
        where = f"calendar.csv row {i + 2} ({r['id'] or 'no id'})"
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", r["id"]):
            problems.append(f"{where}: id must be lower-case letters, digits and dashes")
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", r["date"]) or pd.isna(pd.to_datetime(r["date"], errors="coerce")):
            problems.append(f"{where}: date must be YYYY-MM-DD")
        if not _time_ok(r["time_ist"]) or not _time_ok(r["end_ist"]):
            problems.append(f"{where}: times must be HH:MM in IST, or empty")
        if r["kind"] not in KINDS:
            problems.append(f"{where}: kind must be one of {', '.join(KINDS)}")
        if r["kind"] in ("holiday", "session") and not r["market"]:
            problems.append(f"{where}: a holiday or session needs its market, such as NSE")
        if r["kind"] == "session" and not r["time_ist"]:
            problems.append(f"{where}: a special session needs its start time")
        if r["importance"] not in ("", "high", "medium", "low"):
            problems.append(f"{where}: importance must be high, medium, low or empty")
        if r["status"] not in ("", "scheduled", "cancelled"):
            problems.append(f"{where}: status must be scheduled, cancelled or empty")
        if not r["event"]:
            problems.append(f"{where}: event is empty")
        if not r["source"].startswith("http"):
            problems.append(f"{where}: source must be a link")
        if pd.isna(utc(r["added_at"])) or utc(r["added_at"]) > now + pd.Timedelta(minutes=5):
            problems.append(f"{where}: added_at must be the UTC time the row was added, not in the future")
        if not r["added_by"]:
            problems.append(f"{where}: added_by is empty")
    ids = set(cal["id"])
    lg = _read(log_path, LOG_COLS)
    for i, r in lg.iterrows():
        where = f"log.csv row {i + 2} ({r['id'] or 'no id'})"
        known, added = utc(r["known_at"]), utc(r["added_at"])
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", r["id"]):
            problems.append(f"{where}: id must be lower-case letters, digits and dashes")
        if pd.isna(known):
            problems.append(f"{where}: known_at must be a UTC time such as 2026-11-04T03:23:00Z")
        if pd.isna(added) or added > now + pd.Timedelta(minutes=5):
            problems.append(f"{where}: added_at must be the UTC time the row was added, not in the future")
        elif not pd.isna(known) and known > added:
            problems.append(f"{where}: known_at is after added_at (an event can't be logged before it's public)")
        if r["kind"] not in KINDS:
            problems.append(f"{where}: kind must be one of {', '.join(KINDS)}")
        if not r["headline"]:
            problems.append(f"{where}: headline is empty")
        if r["calendar_id"] and r["calendar_id"] not in ids:
            problems.append(f"{where}: calendar_id {r['calendar_id']} isn't in calendar.csv")
        if not r["source"].startswith("http"):
            problems.append(f"{where}: source must be a link")
        if not r["added_by"]:
            problems.append(f"{where}: added_by is empty")
    if base:
        for path in (cal_path, log_path):
            old = os.path.join(base, os.path.basename(path))
            if not os.path.exists(old):
                continue
            with open(old, encoding="utf-8") as f:
                before = f.read().splitlines()
            after = open(path, encoding="utf-8").read().splitlines() if os.path.exists(path) else []
            if after[:len(before)] != before:
                problems.append(f"{os.path.basename(path)}: existing rows were changed or removed; only add rows")
    return problems


def main():
    if "--check" in sys.argv:
        base = sys.argv[sys.argv.index("--base") + 1] if "--base" in sys.argv else None
        problems = check(base=base)
        print("\n".join(problems) if problems else "Both event files look fine.")
        sys.exit(1 if problems else 0)
    now = pd.Timestamp.now(tz="UTC")
    print("\n".join(describe(now, 14) or ["No event files yet (data/events/)."]))


if __name__ == "__main__":
    main()
