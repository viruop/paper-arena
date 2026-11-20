"""Tests for the three filters on Berlin's Nifty calls (20 Nov 2026): on made-up prices, then on his record as it
stood when they were added, where they must give the rows the nightly run wrote that night.
    python tests/test_filters.py <repo copy> <scratch folder>    (or: python tests/run_tests.py filters)
It works on its own copy of the repository. The record (calls, updates, results, checks) only ever grows, so it is
cut at 20 Nov 2026; the 5-minute bars are kept for 75 days only, so those weeks' Nifty bars are in tests/data/.
"""
import os
import shutil
import sys

REPO, TMP = (os.path.abspath(a) for a in sys.argv[1:3])
HERE = os.path.dirname(os.path.abspath(__file__))
NEW = os.path.join(TMP, "repo")
shutil.copytree(REPO, NEW, ignore=shutil.ignore_patterns("site", "__pycache__", ".git"))
sys.path.insert(0, NEW)
os.chdir(NEW)
import pandas as pd  # noqa: E402

import berlin_calls as b  # noqa: E402

passed = failed = 0


def ok(cond, what):
    global passed, failed
    if cond:
        passed += 1
    else:
        failed += 1
        print("FAIL:", what)


T = lambda s: pd.Timestamp(s, tz="UTC")  # noqa: E731


def bars(start, closes, highs=None, lows=None, opens=None):
    idx = pd.date_range(T(start), periods=len(closes), freq="5min")
    o = opens or closes
    return pd.DataFrame({"Open": o, "High": highs or [max(a, c) + 1 for a, c in zip(o, closes)],
                         "Low": lows or [min(a, c) - 1 for a, c in zip(o, closes)], "Close": closes}, index=idx)


def call(**kw):
    c = {"id": "1", "posted_at": "2026-11-23T03:46:00Z", "kind": "level", "instrument": "NIFTY", "side": "short",
         "entry_type": "market", "entry": "", "stop": "25300", "target": "25100", "rr": "", "horizon": "intraday",
         "event_at": "", "exit_at": "", "price_ref": "", "scorable": "yes", "note": ""}
    c.update(kw)
    return c


calls = pd.DataFrame([call()])
# a session from 9:15 to 3:30 IST (03:45 to 10:00 UTC), flat at 25,200 with small moves
day = bars("2026-11-23T03:45:00Z", [25200 - (i % 3) for i in range(75)])

# ---------------- the on-time rule, as it was before the filters ----------------
# (checked against the code before 20 Nov 2026 when the filters were added: these are its results)
r = b.score_level(call(), day, calls)
ok(r and (r[0]["fill_at"], r[0]["outcome"]) == ("2026-11-23T03:50:00Z", "time"), f"market call on time: {r}")
r = b.score_level(call(entry_type="break", entry="25190", posted_at="2026-11-23T05:00:00Z"), day, calls)
ok(r == [], f"a break of 25,190 that never comes: no trade {r}")

# ---------------- open15 ----------------
r = b.score_level(call(), day, calls, no_entry_before=b.OPEN15_UTC)
ok(r and r[0]["fill_at"] == "2026-11-23T04:00:00Z", f"a 9:16 call waits for 9:30: {r and r[0]['fill_at']}")
r0 = b.score_level(call(), day, calls)
ok(r0 and r0[0]["fill_at"] == "2026-11-23T03:50:00Z", "on time it fills at 9:20")
c_late = call(posted_at="2026-11-23T05:02:00Z")
ok(b.score_level(c_late, day, calls, no_entry_before=b.OPEN15_UTC) == b.score_level(c_late, day, calls),
   "after 9:30 nothing changes")
evening = call(posted_at="2026-11-23T10:01:00Z", horizon="positional")
two = pd.concat([day] + [bars(f"{d.date()}T03:45:00Z", [25200 - (i % 3) for i in range(75)])
                         for d in pd.bdate_range("2026-11-24", periods=15)])
r = b.score_level(evening, two, calls, no_entry_before=b.OPEN15_UTC)
ok(r and r[0]["fill_at"] == "2026-11-24T04:00:00Z", f"posted after the close: waits for 9:30 next day {r and r[0]['fill_at']}")

# ---------------- retest ----------------
# short on a break below 25,190: falls through at bar 3, comes back to 25,190 at bar 8, then falls to the target
closes = [25200, 25198, 25195, 25185, 25180, 25178, 25182, 25186, 25191, 25170, 25150, 25120, 25095, 25090] + [25090] * 61
highs = [c + 2 for c in closes]
lows = [c - 2 for c in closes]
lows[3] = 25183                                  # the break bar
highs[8] = 25193                                 # the retest bar
day2 = bars("2026-11-23T03:45:00Z", closes, highs, lows)
brk = call(entry_type="break", entry="25190", posted_at="2026-11-23T03:46:00Z")
on = b.score_level(brk, day2, calls)
rt = b.score_level(brk, day2, calls, retest=True)
ok(on and on[0]["fill_at"] == "2026-11-23T04:00:00Z", f"on time fills on the break bar {on and on[0]['fill_at']}")
ok(rt and rt[0]["fill_at"] == "2026-11-23T04:25:00Z" and float(rt[0]["fill"]) == 25191.0,
   f"retest fills when the price comes back (opens above the level, so at the open): {rt}")
ok(rt and rt[0]["outcome"] == "target", "the retest trade reaches his target")
highs2 = list(highs)
highs2[8] = 25188                                # never back to the level
none = b.score_level(brk, bars("2026-11-23T03:45:00Z", closes, highs2, lows), calls, retest=True)
ok(none == [], "no retest, no trade")
ok(b.score_level(call(), day, calls, retest=True) == [], "a market call has no level to retest")
wide = list(highs)
wide[3] = 25192                                  # the break bar itself spans the level both ways
rt_w = b.score_level(brk, bars("2026-11-23T03:45:00Z", closes, wide, lows), calls, retest=True)
ok(rt_w and rt_w[0]["fill_at"] == "2026-11-23T04:25:00Z", "the break bar itself never counts as the retest")

# ---------------- trend ----------------
closes_d = pd.Series([24000 + 10 * i for i in range(30)],
                     index=pd.date_range("2026-10-12", periods=30, freq="B"))
last = closes_d.index[-1]
ok(b.nifty_trend(closes_d, T(f"{last.date()}T10:05:00Z")) == "up", "rising closes: up")
ok(b.nifty_trend(closes_d[::-1].reset_index(drop=True).set_axis(closes_d.index), T(f"{last.date()}T10:05:00Z")) == "down",
   "falling closes: down")
ok(b.nifty_trend(closes_d.iloc[:10], T("2026-12-31T00:00:00Z")) is None, "fewer than 20 closes: no trend")
spike = closes_d.copy()
spike.iloc[-1] = 20000                           # today's close far below: down, but only once it's known
ok(b.nifty_trend(spike, T(f"{last.date()}T09:00:00Z")) == "up", "a close isn't used before 3:30 pm IST")
ok(b.nifty_trend(spike, T(f"{last.date()}T10:00:00Z")) == "down", "it is used from 3:30 pm IST")

# ---------------- filters_for ----------------
ok(b.filters_for(call()) == ["trend20", "open15"], "a market Nifty call: trend and open")
ok(b.filters_for(call(entry_type="break", entry="25190")) == list(b.FILTERS), "a break Nifty call: all three")
ok(b.filters_for(call(instrument="GOLD")) == [], "not Nifty: none")
ok(b.filters_for(call(kind="option", scorable="no")) == [], "chart-only or option: none")

# ---------------- filter_rows ----------------
up = pd.Series([24000 + 10 * i for i in range(30)], index=pd.date_range("2026-10-12", periods=30, freq="B"))
rows = b.filter_rows(brk, day2, calls, (), up)
names = [r["variant"] for r in rows]
ok(names == ["trend20", "open15", "retest"], f"rows {names}")
ok(rows[0]["outcome"].startswith("left out") and rows[0]["r"] == 0 and rows[0]["fill_at"] == "",
   "a short against an up trend is left out, counting nothing")
longc = call(side="long", stop="25100", target="25300", posted_at="2026-11-23T05:02:00Z")
rows_l = b.filter_rows(longc, day, pd.DataFrame([longc]), (), up)
ok(rows_l[0]["fill_at"] == b.score_level(longc, day, pd.DataFrame([longc]))[0]["fill_at"],
   "a long with the trend is the on-time trade")
ok(b.filter_rows(brk, day2, calls, (), up.iloc[:5]) is None, "no trend data: waits")
ok(b.filter_rows(call(instrument="GOLD"), day, calls, (), up) == [], "gold: no filter rows")
unfinished = day2.iloc[:20]
ok(b.filter_rows(brk, unfinished, calls, (), up) is None, "window not ended: waits")
rt_none = b.filter_rows(brk, bars("2026-11-23T03:45:00Z", closes, highs2, lows), calls, (), up)
ok([r for r in rt_none if r["variant"] == "retest"][0]["outcome"] == "no retest", "no retest is said so")

# ---------------- score_variants on the record of 20 Nov 2026: each (call, check) once ----------------
AS_OF = "2026-11-20T00:00:00Z"


def cut(path, column):
    df = pd.read_csv(path, dtype=str, keep_default_na=False)
    df[df[column] <= AS_OF].to_csv(path, index=False)
    return df


for path, column in ((b.CALLS, "posted_at"), (b.UPDATES, "posted_at"), (b.RESULTS, "scored_at")):
    cut(path, column)
log = cut(b.VARIANTS, "scored_at")
written = log[log["variant"].isin(b.FILTERS) & (log["scored_at"] <= AS_OF)]      # what the nightly run wrote that night
log[(log["scored_at"] <= AS_OF) & ~log["variant"].isin(b.FILTERS)].to_csv(b.VARIANTS, index=False)   # as if the filters were new
shutil.copy(os.path.join(HERE, "data", "NSEI_5m_2026-10-27_2026-11-19.csv"), b.bars_path("^NSEI"))
daily = pd.read_csv(b.NIFTY_DAILY, dtype=str, keep_default_na=False)
daily[daily["Date"] <= AS_OF[:10]].to_csv(b.NIFTY_DAILY, index=False)
before = b.read_variants()
n1 = b.score_variants(lambda inst: b.read_bars(b.symbol(inst)))
after = b.read_variants()
added = after.iloc[len(before):]
ok(n1 == len(added) == 13, f"13 filter rows for his 6 traded Nifty calls: {n1}")
ok(after.iloc[:len(before)].equals(before), "old rows unchanged")
ok(not after.duplicated(["id", "variant"]).any(), "each (call, check) once")
ok(set(added["variant"]) <= set(b.FILTERS), "a call that had its late and reversed checks only gets filter rows")
nifty_ids = {str(c["id"]) for _, c in b.read_calls().iterrows() if b.filters_for(c)}
ok(set(added["id"].astype(str)) <= nifty_ids, "filters only on Nifty level calls")
cols = [c for c in b.VARIANT_COLS if c != "scored_at"]
ok(added[cols].reset_index(drop=True).equals(written[cols].reset_index(drop=True)),
   "the same rows, to the last digit, as the nightly run wrote on 20 Nov 2026 (a filter never changes)")
n2 = b.score_variants(lambda inst: b.read_bars(b.symbol(inst)))
ok(n2 == 0, "a second run adds nothing")

print(f"filters: {passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
