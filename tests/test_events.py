"""events.py on made-up event files: the latest row for an event wins, what was known at a given moment, upcoming
events, the next session around holidays and the Muhurat session, each market's move around an event, the text a
decision sees, and the file checks (add-only included).
    python tests/test_events.py <repo copy> <scratch folder>    (or: python tests/run_tests.py events)
"""
import csv
import datetime as dt
import os
import shutil
import sys

import pandas as pd

REPO, TMP = os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2])
sys.path.insert(0, REPO)
os.chdir(TMP)                       # the made-up files go in the scratch folder
os.makedirs(os.path.join("data", "events"))
os.makedirs(os.path.join("data", "market"))
import events as ev  # noqa: E402

checks = 0


def ok(cond, what):
    global checks
    checks += 1
    assert cond, what


IST = dt.timezone(dt.timedelta(hours=5, minutes=30))


def write(path, cols, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(cols)
        for r in rows:
            w.writerow([r.get(c, "") for c in cols])


# one row is added "in the future": two days from whenever the test runs, so the check always flags it
future = (pd.Timestamp.now(tz="UTC") + pd.Timedelta(days=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
base = dict(country="IN", status="scheduled", source="https://x.example", added_by="claude", added_at="2026-11-01T00:00:00Z")
cal = [dict(base, id="muhurat", date="2026-11-08", time_ist="14:05", end_ist="15:30", kind="session", market="NSE", event="Muhurat"),
       dict(base, id="hol-10", date="2026-11-10", kind="holiday", market="NSE", event="Diwali holiday"),
       dict(base, id="mcx-only", date="2026-11-11", kind="holiday", market="MCX", event="MCX morning shut"),
       dict(base, id="jobs", date="2026-11-06", time_ist="19:00", country="US", kind="data", event="US jobs", importance="high"),
       dict(base, id="cpi", date="2026-11-12", time_ist="16:00", kind="data", event="India CPI", importance="high"),
       dict(base, id="rbi", date="2026-12-04", time_ist="10:00", kind="central_bank", event="RBI decision"),
       # a later row moves the CPI release, another cancels the RBI row, one is added later than everything asked about
       dict(base, id="cpi", date="2026-11-13", time_ist="16:00", kind="data", event="India CPI (moved)", added_at="2026-11-03T00:00:00Z"),
       dict(base, id="rbi", date="2026-12-04", time_ist="10:00", kind="central_bank", event="RBI decision", status="cancelled",
            added_at="2026-11-03T00:00:00Z"),
       dict(base, id="late", date="2026-11-09", time_ist="12:00", kind="other", event="Added late", added_at=future)]
write(ev.CALENDAR, ev.CAL_COLS, cal)
log = [dict(id="midterms", known_at="2026-11-04T03:23:00Z", country="US", kind="election", headline="Democrats win",
            source="https://x.example", added_at="2026-11-05T17:00:00Z", added_by="claude"),
       dict(id="fed", known_at="2026-10-28T18:00:00Z", country="US", kind="central_bank", headline="Fed holds",
            source="https://x.example", added_at="2026-10-29T00:00:00Z", added_by="claude"),
       dict(id="fed", known_at="2026-10-28T18:00:00Z", country="US", kind="central_bank", headline="Fed holds at 3.75-4%",
            source="https://x.example", added_at="2026-10-30T00:00:00Z", added_by="claude")]
write(ev.LOG, ev.LOG_COLS, log)

# ------------------------------------------------------------------ add-only reading and what was known when
c = ev.calendar(None)
ok(set(c["id"]) == {"muhurat", "hol-10", "mcx-only", "jobs", "cpi", "late"} and c.set_index("id").loc["cpi", "date"] == "2026-11-13",
   "the latest row for an event wins; a cancelled event drops out")
c2 = ev.calendar(pd.Timestamp("2026-11-02T00:00:00Z"))
ok(c2.set_index("id").loc["cpi", "date"] == "2026-11-12" and "rbi" in set(c2["id"]) and "late" not in set(c2["id"]),
   "as of 2 Nov: the CPI date and the RBI row as known then, nothing added later")
lg = ev.log(pd.Timestamp("2026-10-29T12:00:00Z"))
ok(list(lg["id"]) == ["fed"] and lg.iloc[0]["headline"] == "Fed holds", "the log as known on 29 Oct: the first version only")
ok(ev.log(None).set_index("id").loc["fed", "headline"] == "Fed holds at 3.75-4%", "the correction shows once it was added")

# ------------------------------------------------------------------ upcoming: timed events from now, all-day events for the whole day
up = ev.upcoming(pd.Timestamp("2026-11-06T14:00:00Z"), 7)          # 6 Nov 7:30 pm IST, after the jobs report
ok(list(up["id"]) == ["muhurat", "hol-10", "mcx-only", "cpi"], f"upcoming from 6 Nov 7:30 pm IST: {list(up['id'])}")
ok("hol-10" in set(ev.upcoming(pd.Timestamp("2026-11-10T12:00:00Z"), 1)["id"]), "an all-day holiday still shows on its own day")

# ------------------------------------------------------------------ the next session's open
nxt = lambda d: ev.next_open(pd.Timestamp(d))  # noqa: E731
ok(nxt("2026-11-06") == dt.datetime(2026, 11, 8, 14, 5, tzinfo=IST), "after Friday's close: Sunday's Muhurat session at 2:05 pm")
ok(nxt("2026-11-08") == dt.datetime(2026, 11, 9, 9, 0, tzinfo=IST), "after the Muhurat session: Monday 9:00")
ok(nxt("2026-11-09") == dt.datetime(2026, 11, 11, 9, 0, tzinfo=IST), "after Monday: Wednesday, past the NSE holiday (the MCX one doesn't count)")
ok(ev.next_open(pd.Timestamp("2026-11-09"), path="nowhere.csv") == dt.datetime(2026, 11, 10, 9, 0, tzinfo=IST),
   "without a calendar: the next weekday")

# ------------------------------------------------------------------ each market's move, from saved daily closes
pd.DataFrame({"Date": ["2026-11-02", "2026-11-03", "2026-11-04", "2026-11-05", "2026-11-06"],
              "Close": [100.0, 101.0, 102.0, 105.0, 104.0]}).to_csv(os.path.join("data", "market", "NIFTY50.csv"), index=False)
pd.DataFrame({"Date": ["2026-11-02", "2026-11-03", "2026-11-04"], "Close": [10.0, 10.0, 11.0]}).to_csv(
    os.path.join("data", "market", "SP500.csv"), index=False)
r = ev.reaction("2026-11-04T03:23:00Z")
ok(abs(r["Nifty 50"] - (102 / 101 - 1)) < 1e-12 and abs(r[ev.NIFTY3] - (104 / 101 - 1)) < 1e-12,
   "Nifty: from the last close before (3 Nov) to the first after (4 Nov), and to the third (6 Nov)")
ok(abs(r["S&P 500"] - 0.1) < 1e-12 and r["Brent"] is None, "S&P 500 by its own closing time; markets without saved prices stay blank")
r = ev.reaction("2026-11-04T03:23:00Z", as_of="2026-11-05T12:00:00Z")
ok(r[ev.NIFTY3] is None and abs(r["Nifty 50"] - (102 / 101 - 1)) < 1e-12, "as of 5 Nov: no third close yet, nothing later used")
r = ev.reaction("2026-11-04T10:30:00Z")        # 4 pm IST, after Nifty's close
ok(abs(r["Nifty 50"] - (105 / 102 - 1)) < 1e-12, "an event after the close is measured from that close to the next")

# ------------------------------------------------------------------ the text a decision sees
text = "\n".join(ev.describe(pd.Timestamp("2026-11-05T16:52:00Z")))
ok("Democrats win" not in text and "Muhurat" in text and "US jobs" in text,
   "a decision at 10:22 pm IST on 5 Nov doesn't see a log row added at 10:30 pm")
ok("Democrats win" in "\n".join(ev.describe(pd.Timestamp("2026-11-05T18:00:00Z"))), "a later snapshot does")
ok(ev.describe(None, cal_path="none.csv", log_path="none2.csv") == [], "no event files: no section at all")

# ------------------------------------------------------------------ checks
probs = ev.check()
ok(len(probs) == 1 and "(late)" in probs[0] and "not in the future" in probs[0], f"only the row added in the future fails: {probs}")
bad = os.path.join(TMP, "bad")
os.makedirs(bad)
write(os.path.join(bad, "calendar.csv"), ev.CAL_COLS,
      [dict(base, id="Bad ID", date="5 Nov", time_ist="25:00", kind="party", event="", source="none", market="")])
write(os.path.join(bad, "log.csv"), ev.LOG_COLS, [dict(id="x", known_at="2026-11-06T00:00:00Z", kind="election", headline="h",
                                                       source="https://x", added_at="2026-11-05T00:00:00Z", added_by="c",
                                                       calendar_id="nope")])
probs = ev.check(os.path.join(bad, "calendar.csv"), os.path.join(bad, "log.csv"))
for want in ("id must be", "date must be", "times must be", "kind must be", "event is empty", "source must be a link",
             "known_at is after added_at", "calendar_id nope"):
    ok(any(want in p for p in probs), f"the check catches: {want}")
shutil.copytree(os.path.join("data", "events"), "base_events")
with open(ev.LOG, "a", encoding="utf-8") as f:
    f.write("fii-day,2026-11-05T10:00:00Z,IN,other,FIIs buy,,,https://x,2026-11-05T11:00:00Z,claude\n")
ok(len(ev.check(base="base_events")) == 1, "adding a row passes the add-only check")
rows = open(ev.LOG, encoding="utf-8").read().splitlines()
open(ev.LOG, "w", encoding="utf-8").write("\n".join(rows[:1] + rows[2:]) + "\n")
ok(any("only add rows" in p for p in ev.check(base="base_events")), "removing a row fails it")

print(f"events: {checks} checks passed")
