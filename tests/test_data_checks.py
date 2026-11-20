"""Tests for the data checks and the record of what each day was built from (16 Nov 2026): data_health.py,
logbook.py's provenance and replay list, when an F&O day may be logged (fno_prices.py), and the page's labels,
worst fall, data checks and replay table.
    python tests/test_data_checks.py <repo copy> <scratch folder>    (or: python tests/run_tests.py data)"""
import os
import shutil
import sys

REPO, TMP = os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2])
sys.path.insert(0, REPO)
os.chdir(REPO)

import pandas as pd  # noqa: E402

import data_health as dh  # noqa: E402
import logbook  # noqa: E402

passed = failed = 0


def ok(cond, what):
    global passed, failed
    if cond:
        passed += 1
    else:
        failed += 1
        print("FAIL:", what)


T = pd.Timestamp
IST_ = lambda s: T(s, tz="Asia/Kolkata").tz_convert("UTC")          # noqa: E731
hol, spec = dh.nse_calendar()

# ---------------- calendars ----------------
ok("2026-11-10" in hol and "2026-11-24" in hol, "calendar has the Nov 2026 NSE holidays")
ok("2026-11-08" in spec, "calendar has the Muhurat session")
ok(dh.last_closed(IST_("2026-11-13 15:59"), "NSE", dh.NSE, hol, spec) == T("2026-11-12"), "before 16:00: yesterday")
ok(dh.last_closed(IST_("2026-11-13 16:00"), "NSE", dh.NSE, hol, spec) == T("2026-11-13"), "at 16:00: today")
ok(dh.last_closed(IST_("2026-11-16 08:30"), "NSE", dh.NSE, hol, spec) == T("2026-11-13"), "Monday morning: Friday")
ok(dh.last_closed(IST_("2026-11-10 20:00"), "NSE", dh.NSE, hol, spec) == T("2026-11-09"), "holiday: day before")
ok(dh.last_closed(IST_("2026-11-08 20:00"), "NSE", dh.NSE, hol, spec) == T("2026-11-08"), "Muhurat Sunday counts")
ok(dh.last_closed(IST_("2026-11-25 09:00"), "NSE", dh.NSE, hol, spec) == T("2026-11-23"), "24 Nov holiday skipped")
ny = ("America/New_York", "17:30")
ok(dh.last_closed(T("2026-11-13 22:14", tz="UTC"), "weekdays", ny) == T("2026-11-12"), "COMEX at 17:14 ET: day before")
ok(dh.last_closed(T("2026-11-13 22:31", tz="UTC"), "weekdays", ny) == T("2026-11-13"), "COMEX at 17:31 ET: today")
ok(len(dh.sessions_after(T("2026-11-06"), T("2026-11-13"), "NSE", hol, spec)) == 5,
   "6 to 13 Nov: Muhurat 8, 9, 11, 12, 13 (10 is a holiday)")
ok(dh.sessions_after(T("2026-11-13"), T("2026-11-13"), "NSE", hol, spec) == [], "nothing after the same day")

# ---------------- file checks on synthetic data ----------------
work = os.path.join(TMP, "dh")
shutil.rmtree(work, ignore_errors=True)
os.makedirs(os.path.join(work, "indices"))
dh.MARKET = work


def write(rel, days, closes=None, extra=None):
    days = list(days)
    closes = closes or [100 + i * 0.1 for i in range(len(days))]
    df = pd.DataFrame({"Date": [d.strftime("%Y-%m-%d") for d in days], "Open": closes, "High": [c * 1.01 for c in closes],
                       "Low": [c * 0.99 for c in closes], "Close": closes})
    if extra:
        extra(df)
    df.to_csv(os.path.join(work, rel), index=False)


sess = [d for d in pd.bdate_range("2026-08-03", "2026-11-13") if d.strftime("%Y-%m-%d") not in hol and
        d.strftime("%Y-%m-%d") not in ("2026-10-02", "2026-10-20")] + [T("2026-11-08")]
sess = sorted(sess)
for rel in dh.SOURCES:
    write(rel, sess)
now = IST_("2026-11-16 08:30")
ref = dh.nse_sessions()
ok(len(ref) == len(sess) and T("2026-10-02") not in ref, "sessions = days two sources have")
spec_n = ("Nifty 50 (Yahoo)", "NSE", dh.NSE, 0, 0.06, True)
r = dh.check_file("NIFTY50.csv", spec_n, now, hol, spec, ref)
ok(not r["problems"] and not r["warnings"] and r["rows"] == len(sess), f"clean file passes: {r}")
ok(len(r["version"]) == 12, "version is 12 characters")

write("NIFTY50.csv", sess[:-2])
r = dh.check_file("NIFTY50.csv", spec_n, now, hol, spec, ref)
ok(any("2 sessions behind" in p for p in r["problems"]), f"2 sessions behind fails for an agents' file: {r}")
r = dh.check_file("NIFTY50.csv", ("x", "NSE", dh.NSE, 0, 0.06, False), now, hol, spec, ref)
ok(not r["problems"] and any("behind" in w for w in r["warnings"]), "the same only warns for a context file")
r = dh.check_file("NIFTY50.csv", ("x", "NSE", dh.NSE, 2, 0.06, True), now, hol, spec, ref)
ok(not r["problems"], "grace of 2 sessions accepts it")
write("NIFTY50.csv", sess[:-1])
r = dh.check_file("NIFTY50.csv", spec_n, now, hol, spec, ref)
ok(any("1 session behind" in p for p in r["problems"]), f"1 session behind fails with no grace: {r}")
r = dh.check_file("NIFTY50.csv", ("x", "NSE", dh.NSE, 1, 0.06, True), now, hol, spec, ref)
ok(not r["problems"], "grace of 1 accepts 1 behind")

write("NIFTY50.csv", sess[:30] + sess[31:])
r = dh.check_file("NIFTY50.csv", spec_n, now, hol, spec, ref)
miss = sess[30]
ok(any("1 session missing" in w for w in r["warnings"]) == (miss >= ref[-dh.WINDOW]), f"gap flagged inside the window: {r}")
write("NIFTY50.csv", sess[:-6] + sess[-5:])
r = dh.check_file("NIFTY50.csv", spec_n, now, hol, spec, ref)
ok(any("1 session missing" in w and sess[-6].strftime("%d %b") in w for w in r["warnings"]), f"recent gap named: {r}")

write("NIFTY50.csv", sess + [sess[-1]])
r = dh.check_file("NIFTY50.csv", spec_n, now, hol, spec, ref)
ok(any("saved twice" in p for p in r["problems"]), "duplicate date fails")
write("NIFTY50.csv", sess[:-1][::-1] + [sess[-1]])
r = dh.check_file("NIFTY50.csv", spec_n, now, hol, spec, ref)
ok(any("out of order" in p for p in r["problems"]), "unsorted dates fail")
closes = [100.0] * len(sess)
closes[-3] = 0.0
write("NIFTY50.csv", sess, closes)
r = dh.check_file("NIFTY50.csv", spec_n, now, hol, spec, ref)
ok(any("zero or negative" in p for p in r["problems"]), "zero price fails")
closes = [100.0] * len(sess)
closes[-4] = 91.0
write("NIFTY50.csv", sess, closes)
r = dh.check_file("NIFTY50.csv", spec_n, now, hol, spec, ref)
ok(any("−9.0%" in w for w in r["warnings"]) and any("+9.9%" in w for w in r["warnings"]),
   f"big moves warned with a real minus sign: {r['warnings']}")
closes = [100.0] * len(sess)
closes[5] = 80.0
write("NIFTY50.csv", sess, closes)
r = dh.check_file("NIFTY50.csv", spec_n, now, hol, spec, ref)
ok(not any("moved" in w for w in r["warnings"]), "big moves before the last 60 sessions are ignored")


def flip(df):
    df.loc[len(df) - 2, "High"] = df.loc[len(df) - 2, "Low"] * 0.98


write("NIFTY50.csv", sess, None, flip)
r = dh.check_file("NIFTY50.csv", spec_n, now, hol, spec, ref)
ok(any("high below low" in w for w in r["warnings"]) and not r["problems"], "high below low warns")
r = dh.check_file("missing.csv", spec_n, now, hol, spec, ref)
ok(r["problems"] == ["file missing"], "a missing agents' file fails")
with open(os.path.join(work, "bad.csv"), "w") as f:
    f.write("Date,Close\nnot a date,1\n2026-11-13,2\n")
r = dh.check_file("bad.csv", ("x", "NSE", dh.NSE, 0, None, False), now, hol, spec, ref)
ok(any("without a readable date" in p for p in r["problems"]), "unreadable dates fail")

# two sources disagreeing
write("NIFTY50.csv", sess)
closes = [100 + i * 0.1 for i in range(len(sess))]
closes[-2] *= 1.001
write(os.path.join("indices", "NIFTY_50.csv"), sess, closes)
ok("differ by 0.10%" in (dh.check_agree() or ""), f"sources 0.1% apart flagged: {dh.check_agree()}")
write(os.path.join("indices", "NIFTY_50.csv"), sess)
ok(dh.check_agree() is None, "agreeing sources pass")

# option files
fno = os.path.join(TMP, "fno")
shutil.rmtree(fno, ignore_errors=True)
os.makedirs(fno)
dh.FNO = fno
for d in [x for x in sess if x >= T("2026-10-28")]:
    pd.DataFrame({"expiry": ["2026-11-17"], "strike": [25000], "type": ["CE"], "close": [100.0]}).to_csv(
        os.path.join(fno, f"{d:%Y-%m-%d}.csv"), index=False)
r = dh.check_fno(now, hol, spec, ref)
ok(not r["problems"] and r["last"] == T("2026-11-13") and len(r["version"]) == 12, f"complete option files pass: {r}")
os.remove(os.path.join(fno, "2026-11-11.csv"))
r = dh.check_fno(now, hol, spec, ref)
ok(any("1 session without NSE's file (latest 11 Nov)" in p for p in r["problems"]), f"missing option file fails: {r}")
pd.DataFrame({"expiry": ["2026-11-17"], "strike": [25000], "type": ["CE"], "close": [100.0]}).to_csv(
    os.path.join(fno, "2026-11-11.csv"), index=False)
r = dh.check_fno(IST_("2026-11-13 21:30"), hol, spec, ref)
ok(not r["problems"], "before 22:00 IST the day's file isn't due yet")
os.remove(os.path.join(fno, "2026-11-13.csv"))
r = dh.check_fno(IST_("2026-11-13 21:30"), hol, spec, ref)
ok(not r["problems"], "13 Nov missing at 21:30 is fine")
r = dh.check_fno(IST_("2026-11-13 22:05"), hol, spec, ref)
ok(any("latest 13 Nov" in p for p in r["problems"]), "13 Nov missing at 22:05 fails")
with open(os.path.join(fno, "2026-11-13.csv"), "w") as f:
    f.write("expiry,strike\n")
r = dh.check_fno(now, hol, spec, ref)
ok(any("no usable prices" in p for p in r["problems"]), "an empty option file fails")

# when an F&O day may be logged: with NSE's file as soon as it is saved, with estimated prices only after 10 pm
import fno_prices as fp  # noqa: E402

fp_folder, fp.FOLDER = fp.FOLDER, os.path.join(TMP, "fno_timing")
os.makedirs(fp.FOLDER)
dates = pd.to_datetime(["2026-11-02", "2026-11-03", "2026-11-04"])
for dd in dates[:2]:
    open(fp.path(dd), "w").write("x")
ist = lambda t: T(t).tz_localize("Asia/Kolkata")          # noqa: E731
ok(fp.final_until(dates, "2026-11-02", now=ist("2026-11-04 16:12")) == T("2026-11-03"), "a 4:12 pm upload: 4 Nov not logged yet")
ok(fp.final_until(dates, "2026-11-02", now=ist("2026-11-04 22:13")) == T("2026-11-04"), "the 10:13 pm run: 4 Nov logged, estimated")
open(fp.path(dates[2]), "w").write("x")
ok(fp.final_until(dates, "2026-11-02", now=ist("2026-11-04 20:47")) == T("2026-11-04"), "with NSE's file at 8:47 pm: logged then")
fp.FOLDER = fp_folder

# ---------------- run log ----------------
ok(dh.scheduled_time("17 15 * * 1-5", T("2026-11-16 15:40", tz="UTC")) == T("2026-11-16 15:17", tz="UTC"), "same day")
ok(dh.scheduled_time("43 16 * * 1-5", T("2026-11-17 00:10", tz="UTC")) == T("2026-11-16 16:43", tz="UTC"),
   "after midnight UTC: the day before")
ok(dh.scheduled_time("", T("2026-11-16 15:40", tz="UTC")) is None, "no schedule")
res = {"versions": {"python": "3.12.9", "pandas": "3.1.1", "numpy": "2.5.5"}, "last_close": T("2026-11-16"),
       "failed": 1, "warnings": 2}
env = {"RUN_STARTED": "2026-11-16T15:40:12Z", "RUN_SCHEDULE": "17 15 * * 1-5", "GITHUB_EVENT_NAME": "schedule",
       "GITHUB_RUN_ID": "123", "GITHUB_SHA": "abcdef1234567"}
path = os.path.join(TMP, "runs.csv")
if os.path.exists(path):
    os.remove(path)
row = dh.log_run(res, path, env, "2026-11-16T15:44:00Z")
ok(row["late_min"] == "23" and row["scheduled"] == "2026-11-16T15:17:00Z" and row["commit"] == "abcdef1", f"row {row}")
ok(row["started"] == "2026-11-16T15:40:12Z" and row["logged"] == "2026-11-16T15:44:00Z", "times kept in UTC")
row2 = dh.log_run(res, path, {"GITHUB_EVENT_NAME": "push"}, "2026-11-16T16:00:00Z")
ok(row2["scheduled"] == "" and row2["late_min"] == "" and row2["trigger"] == "push", "push run has no schedule")
lines = open(path).read().splitlines()
ok(lines[0] == ",".join(dh.RUN_COLS) and len(lines) == 3, "header once, one line per run")
got = dh.runs(path)
ok(got[0]["trigger"] == "push" and got[1]["late_min"] == "23", "runs() newest first")
ok(dh.runs(os.path.join(TMP, "none.csv")) == [], "no file, no runs")

# ---------------- real data (the repository's own files) ----------------
# Whether today's data pass is for the nightly run to say; here only that the checks run on them, and that
# the same files fail as stale a week after their last day.
dh.MARKET, dh.FNO = os.path.join("data", "market"), os.path.join("data", "fno")
last = dh.read(os.path.join(dh.MARKET, "NIFTY50.csv")).index.max()
real = dh.check(last.tz_localize("UTC") + pd.Timedelta(hours=11))         # 4:30 pm IST on its last day
ok(real["last_close"] == last, "the last Nifty close is the newest saved day")
ok(len(real["files"]) == len(dh.FILES) + 1 and all(f["version"] for f in real["files"]),
   "every file and the option folder checked, each with a version")
late = dh.check(last.tz_localize("UTC") + pd.Timedelta(days=7, hours=11))
ok(late["failed"] >= 5, f"a week later the agents' files fail as stale ({late['failed']})")

# ---------------- logbook: provenance and drift ----------------
lb = os.path.join(TMP, "lb")
shutil.rmtree(lb, ignore_errors=True)
os.makedirs(lb)
logbook.DAILY, logbook.TRADES, logbook.PROVENANCE = (os.path.join(lb, f) for f in ("daily.csv", "trades.csv", "prov.csv"))
p1 = logbook.provenance_row("2026-11-13", logbook.FNO, {"GITHUB_SHA": "1234567890", "GITHUB_RUN_ID": "9"},
                            T("2026-11-13 22:30", tz="Asia/Kolkata"))
ok(p1["prices"].startswith("NSE's option file") and p1["commit"] == "1234567" and p1["run_id"] == "9", f"{p1}")
ok(p1["logged_at"] == "2026-11-13T22:30+0530" and len(p1["data"]) == 12, "time and data version")
p2 = logbook.provenance_row("2026-11-15", logbook.FNO, {})
ok(p2["prices"].startswith("estimated") and p2["data"] == "" and p2["commit"] == "local", f"no file: estimates {p2}")
p3 = logbook.provenance_row("2026-11-13", logbook.ASSETS, {})
p4 = logbook.provenance_row("2026-11-13", logbook.NIFTY, {})
ok(p3["prices"] == "ETF and futures closes" and p4["prices"].startswith("index closes") and p3["data"] != p4["data"], "groups")
tmpf = os.path.join(lb, "v.csv")
open(tmpf, "w").write("a")
v1 = logbook.files_version([tmpf])
open(tmpf, "w").write("b")
ok(v1 != logbook.files_version([tmpf]) and logbook.files_version([os.path.join(lb, "none")]) == "", "version follows content")

idx = pd.to_datetime(["2026-11-11", "2026-11-12", "2026-11-13"])
vals = pd.DataFrame({"A": [100000.0, 100100.0, 100200.0], "B": [100000.0, 99900.0, 99800.0]}, index=idx)
labels = {a: pd.Series({d: "NIFTY 50" for d in idx}) for a in vals.columns}
vals2 = pd.DataFrame({"C": [100000.0, 100050.0, 100075.0]}, index=idx)
view = [{"values": vals, "labels": labels, "trades": [{"date": idx[0], "agent": "A", "what": "Buy"}], "final": idx[-1],
         "arena": logbook.NIFTY},
        {"values": vals2, "labels": {"C": pd.Series({d: "Cash" for d in idx})}, "trades": [], "final": idx[1],
         "arena": logbook.FNO}]
closes = {"NIFTY 50": pd.Series([25000.0, 25100.0, 25200.0], index=idx)}
n, t = logbook.update(view, closes)
prov = logbook.read(logbook.PROVENANCE, logbook.PROVENANCE_COLS)
ok(n == 8 and t == 1, f"rows {n}, trades {t}")
ok(len(prov) == 5 and set(prov["arena"]) == {logbook.NIFTY, logbook.FNO}, f"one provenance row per group and day: {prov}")
ok(list(prov[prov.arena == logbook.FNO]["date"]) == ["2026-11-11", "2026-11-12"], "F&O only to its final day")
n2, _ = logbook.update(view, closes)
ok(n2 == 0 and len(logbook.read(logbook.PROVENANCE, logbook.PROVENANCE_COLS)) == 5, "nothing added twice")
saved_with = logbook.provenance()
ok(saved_with[("2026-11-12", logbook.FNO)]["arena"] == logbook.FNO, "provenance() keyed by day and group")
view[0]["values"].loc[idx[1], "B"] = 99000.0       # a replay that disagrees with a saved row
d = logbook.drift(view)
ok(d and d["rows"] == 1 and d["list"][0]["agent"] == "B" and d["list"][0]["saved"] == 99900.0
   and d["list"][0]["replay"] == 99000.0 and d["list"][0]["arena"] == logbook.NIFTY, f"drift list {d}")
blocks = logbook.merged
ok(blocks.__doc__ is not None, "merged still documented")

# ---------------- page parts ----------------
import build_site as bs  # noqa: E402

html = bs.drift_html(view)
ok("Every row that differs (1)" in html and "Saved with: index closes (Nifty 50 and the sector indices); data" in html and "−₹900.00" in html,
   "drift table shows provenance and the gap")
logbook.PROVENANCE = os.path.join(lb, "none.csv")
html = bs.drift_html(view)
ok("not recorded (saved before 16 Nov 2026)" in html, "rows without provenance say so")
dsum = {"checked": T("2026-11-16 15:44", tz="UTC"), "failed": 1, "warnings": 1, "versions": res["versions"],
        "files": [{"name": "Nifty 50 (Yahoo)", "rows": 4700, "version": "abc", "last": T("2026-11-13"),
                   "problems": ["2 sessions behind"], "warnings": []},
                  {"name": "Brent", "rows": 10, "version": "def", "last": None, "problems": [], "warnings": ["x"]}],
        "runs": dh.runs(path)}
html = bs.data_html(dsum)
ok("1 failed, 1 to look at" in html and "Failed: 2 sessions behind" in html and "To look at: x" in html, "data checks")
ok("23 min after its schedule" in html and "After an upload" in html and "code abcdef1" in html, "runs table")
ok("pandas 3.1.1" in html and bs.data_html(None) == "", "versions line; nothing without checks")
ok(bs.worst_fall(pd.Series([100, 110, 99, 120])) == 99 / 110 - 1 and bs.worst_fall(pd.Series([1, 2, 3])) == 0, "worst fall")
ok("Backtest, model prices" in bs.evidence_html() and "Live" in bs.evidence_html(), "legend")
ok(bs.tag("shadow") == "<span class='tag'>Shadow mode</span>", "tag")
groups = [("Nifty 50 agents and Claude", [("A", 100200.0, 0.002, "NIFTY 50", "A"), ("B", 99800.0, -0.002, "NIFTY 50", "B")])]
board = bs.board_section(groups, view, "intro")
a_part, b_part = board.split(">B<")[0].split(">A<")[1], board.split(">B<")[1]
ok("No fall yet" in a_part and "1 trade<" in a_part, "A: no fall, 1 trade")
ok("Worst fall \u22121.0%" in b_part and "0 trades" in b_part, "B: worst fall and 0 trades")
ok("<span class='tag'>Paper, simulated fills</span>" in board and "What the labels mean" in board, "group label and legend")

print(f"data checks: {passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
