"""berlin_etf.py, his Nifty calls copied onto NIFTYBEES: every line on real NIFTYBEES bars against an independent
re-computation, two lines checked by hand, the gates (copied once, only after the record has scored a call), and
made-up cases for the paths his calls haven't used yet.
    python tests/test_berlin_etf.py <repo copy> <scratch folder>    (or: python tests/run_tests.py etf)
It works on its own copy of the repository, as the record stood at 3 pm UTC on 11 Nov 2026 (calls, updates and
results are only ever added to, so cutting them there is exact), with that period's 5-minute bars from
tests/data/: the saved bars are kept for 75 days only.
"""
import os
import shutil
import sys

import pandas as pd

REPO, TMP = os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2])
HERE = os.path.dirname(os.path.abspath(__file__))
repo = os.path.join(TMP, "repo")
shutil.copytree(REPO, repo, ignore=shutil.ignore_patterns("site", "__pycache__", ".git"))
os.chdir(repo)
sys.path.insert(0, repo)
import berlin_calls as bc      # noqa: E402
import berlin_etf as be        # noqa: E402
import zerodha                 # noqa: E402

AS_OF = "2026-11-11T15:00:00Z"
for path, column in ((bc.CALLS, "posted_at"), (bc.UPDATES, "posted_at"), (bc.RESULTS, "scored_at")):
    df = pd.read_csv(path, dtype=str, keep_default_na=False)
    df[df[column] <= AS_OF].to_csv(path, index=False)
for sym, name in ((be.SYMBOL, "NIFTYBEES_NS_5m"), ("^NSEI", "NSEI_5m")):
    shutil.copy(os.path.join(HERE, "data", f"{name}_2026-10-27_2026-11-19.csv"), bc.bars_path(sym))
record = {f: open(f, "rb").read() for f in (bc.RESULTS, bc.CALLS, "logs/berlin_variants.csv", bc.bars_path("^NSEI"))}

bc.update_bars = lambda sym, keep_days=75: (_ for _ in ()).throw(RuntimeError("offline in the test"))
ok = lambda name: print(f"  ok  {name}")  # noqa: E731


def bars_file(sym):
    return bc.bars_path(sym)


# ------------------------------------------------------------------ 1. real data, independent re-computation
if os.path.exists(be.RESULTS):
    os.remove(be.RESULTS)
be.main()
got = be.read_results()
assert len(got) == 22, len(got)
etf, nifty = bc.read_bars(be.SYMBOL), bc.read_bars("^NSEI")
calls, ups = bc.read_calls(), bc.read_updates()


def reference(call, late, aim):
    """The same rules written out from scratch, for calls whose only later posts are exits and claims."""
    posted = pd.Timestamp(call["posted_at"])
    begin = posted + pd.Timedelta(minutes=late)
    day_cut = pd.Timestamp(f"{posted.date()} 09:40", tz="UTC")
    if begin >= day_cut:
        return {"outcome": "after 3:10 pm"}
    end = pd.Timestamp(f"{posted.date()} 10:00", tz="UTC")
    if call["exit_at"]:
        end = min(end, pd.Timestamp(call["exit_at"]))
    mine = ups[(ups["call_id"] == call["id"])]
    assert set(mine["action"]) <= {"exit", "claim"}, "the reference only knows exits"
    for t in mine.loc[mine["action"] == "exit", "posted_at"]:
        if pd.Timestamp(t) > posted:
            end = min(end, pd.Timestamp(t))
    end = min(end, day_cut)
    first = etf[etf.index >= begin].index[0]
    k = etf.at[first, "Open"] / nifty.at[first, "Open"]
    window = etf[(etf.index >= begin) & (etf.index < end)]
    if window.empty:
        return {"outcome": "not filled", "k": k}
    sign = -1 if call["side"] == "short" else 1
    option = call["kind"] == "option"
    lvl = lambda x: None if x == "" else round(float(x) * k, 2)
    if not option and call["entry_type"] == "break":
        trigger = lvl(call["entry"])
        hit = None
        for t, b in window.iterrows():
            if (b["Low"] <= trigger) if sign < 0 else (b["High"] >= trigger):
                hit = t
                break
        if hit is None:
            return {"outcome": "not filled", "k": k}
        o = window.at[hit, "Open"]
        fill_at, fill = hit, (min(o, trigger) if sign < 0 else max(o, trigger))
    else:
        fill_at, fill = window.index[0], window["Open"].iloc[0]
    stop = None if option else lvl(call["stop"])
    if stop is None:
        stop = fill * (1 - sign * 0.002)
    target = None if option else lvl(call["target"])
    if target is None and not option and call["rr"] != "":
        target = fill + sign * float(call["rr"]) * abs(fill - stop)
    if late and aim is not None:
        target = aim
    if (stop - fill) * sign >= 0 or (target is not None and (target - fill) * sign <= 0):
        return {"outcome": "not filled", "k": k}
    outcome, exit_at, exit_ = None, None, None
    for t, b in window[window.index >= fill_at].iterrows():
        if (b["Low"] <= stop) if sign > 0 else (b["High"] >= stop):
            gap = (b["Open"] < stop) if sign > 0 else (b["Open"] > stop)
            outcome, exit_at, exit_ = "stop", t, (b["Open"] if gap else stop)
            break
        if target is not None and ((b["High"] >= target) if sign > 0 else (b["Low"] <= target)):
            gap = (b["Open"] > target) if sign > 0 else (b["Open"] < target)
            outcome, exit_at, exit_ = "target", t, (b["Open"] if gap else target)
            break
    if outcome is None:
        last = window.index[-1]
        exit_at, exit_ = last + pd.Timedelta(minutes=5), window.at[last, "Close"]
        outcome = "time" if end == day_cut or end == pd.Timestamp(f"{posted.date()} 10:00", tz="UTC") else "his exit"
    units = int(10000 // fill)
    entry_px = fill * (1 + sign * 0.00015)
    exit_px = exit_ if outcome == "target" else exit_ * (1 - sign * 0.00015)
    buy, sell = (entry_px, exit_px) if sign > 0 else (exit_px, entry_px)
    fees = zerodha.charges(units * buy, units * sell, "MIS", "equity_etf")["total"]
    net = units * (sell - buy) - fees
    return {"outcome": outcome, "k": k, "units": units, "fill_at": fill_at, "fill": fill, "stop": stop,
            "target": target, "exit_at": exit_at, "exit": exit_, "net": net, "fees": fees,
            "move": sign * units * (exit_ - fill)}


checked = 0
for cid, part in got.groupby("id", sort=False):
    call = calls[calls["id"] == cid].iloc[0]
    aim = None
    for _, g in part.iterrows():
        late = {"ontime": 0, "late15": 15, "late30": 30}[g["variant"]]
        ref = reference(call, late, aim)
        assert g["outcome"] == ref["outcome"], (cid, g["variant"], g["outcome"], ref["outcome"])
        if "units" in ref:
            assert int(g["units"]) == ref["units"]
            assert pd.Timestamp(g["fill_at"]) == ref["fill_at"] and pd.Timestamp(g["exit_at"]) == ref["exit_at"], (cid, g["variant"])
            for col, key, tol in (("fill", "fill", 0.006), ("stop", "stop", 0.006), ("exit", "exit", 0.006),
                                  ("pnl_rs", "net", 0.011), ("charges_rs", "fees", 0.011), ("move_rs", "move", 0.011)):
                assert abs(float(g[col]) - ref[key]) <= tol, (cid, g["variant"], col, g[col], ref[key])
            assert (g["target"] == "") == (ref["target"] is None)
            if ref["target"] is not None:
                assert abs(float(g["target"]) - ref["target"]) <= 0.006
            assert g["product"] == "MIS"
            if late == 0:
                aim = ref["target"]
        else:
            assert int(g["units"]) == 0 and float(g["pnl_rs"]) == 0
        if "k" in ref:
            assert abs(float(g["ratio"]) - ref["k"]) < 1e-7
        checked += 1
assert checked == 22
ok("all 22 lines on the real NIFTYBEES bars match an independent re-computation")

# two calls checked by hand against the raw bars on 11 Nov 2026
r = got[(got["id"] == "77751") & (got["variant"] == "ontime")].iloc[0]
assert (r["fill_at"], r["fill"], r["stop"], r["target"], r["exit_at"], r["outcome"]) == (
    "2026-10-29T04:25:00Z", "259.96", "259.32", "261.24", "2026-10-29T08:30:00Z", "target"), dict(r)
r = got[(got["id"] == "77872") & (got["variant"] == "ontime")].iloc[0]
assert (r["fill_at"], r["fill"], r["exit_at"], r["outcome"]) == ("2026-11-03T05:45:00Z", "269.23", "2026-11-03T06:15:00Z", "stop")
ok("77751 and 77872 as checked by hand against the bars")

# ------------------------------------------------------------------ 2. scored once, never rewritten
before = open(be.RESULTS).read()
be.main()
assert open(be.RESULTS).read() == before
ok("a second run adds nothing and rewrites nothing")

# the record itself is untouched by the copy
for f, saved in record.items():
    assert open(f, "rb").read() == saved, f
ok("the record's own files are byte-for-byte unchanged")

# ------------------------------------------------------------------ 3. gates
os.remove(be.RESULTS)
main_res = open(bc.RESULTS).read()
kept = [ln for ln in main_res.splitlines() if not ln.startswith("77751,")]
open(bc.RESULTS, "w").write("\n".join(kept) + "\n")
be.main()
assert "77751" not in set(be.read_results()["id"]) and len(be.read_results()) == 19
open(bc.RESULTS, "w").write(main_res)
be.main()
assert len(be.read_results()) == 22 and list(be.read_results()["id"])[-3:] == ["77751"] * 3
ok("a call isn't copied before the record has scored it, and is picked up the night it has")

s = be.summary()
c = s["books"]["calls"]
assert c["copied"] == 6 and c["ontime"]["n"] == 5 and c["ontime"]["wins"] == 1 and s["waiting"] == []
assert abs(c["ontime"]["net"] - (-49.66)) < 0.011 and abs(c["ontime"]["charges"] - 48.70) < 0.011
assert abs(c["ontime"]["move"] - c["ontime"]["slip"] - c["ontime"]["charges"] - c["ontime"]["net"]) < 0.03
assert abs(c["index_r"] - (-0.526 - 0.576 - 1.681 + 1.757 + 0)) < 1e-9          # the same five calls in the record
assert s["books"]["options"]["ontime"]["n"] == 2 and abs(s["books"]["options"]["index_r"] - (-0.315 - 0.378)) < 1e-9
ok("summary totals add up, and the index comparison uses the same calls")

# ------------------------------------------------------------------ 4. made-up cases
def fresh(call_rows, update_rows=(), main_ids=None, etf_bars=None, nifty_bars=None):
    """Replace the tagged calls, updates, record and bars with made-up ones."""
    cols = list(calls.columns)
    pd.DataFrame(call_rows, columns=cols).to_csv(bc.CALLS, index=False)
    pd.DataFrame(list(update_rows), columns=bc.UPDATE_COLS).to_csv(bc.UPDATES, index=False)
    ids = main_ids if main_ids is not None else [r["id"] for r in call_rows]
    rows = [{c: "" for c in bc.RESULT_COLS} | {"id": i, "outcome": "time", "r": 0, "pnl_rs": 0, "leg": "call", "kind": "level"} for i in ids]
    pd.DataFrame(rows, columns=bc.RESULT_COLS).to_csv(bc.RESULTS, index=False)
    if os.path.exists(be.RESULTS):
        os.remove(be.RESULTS)
    if etf_bars is not None:
        etf_bars.round(5).to_csv(bars_file(be.SYMBOL), index_label="time")
    if nifty_bars is not None:
        nifty_bars.round(5).to_csv(bars_file("^NSEI"), index_label="time")


def call(cid, posted, side="long", horizon="intraday", kind="level", entry_type="market", entry="", stop="", target="",
         rr="", scorable="yes", note="made up", instrument="NIFTY"):
    base = {c: "" for c in calls.columns}
    base.update(id=str(cid), posted_at=posted, kind=kind, instrument=instrument, side=side, entry_type=entry_type,
                entry=str(entry), stop=str(stop), target=str(target), rr=str(rr), horizon=horizon, scorable=scorable, note=note)
    return base


def day_bars(day, path, scale=1.0):
    """75 five-minute bars for one session from a list of (open, high, low, close) or a function of the bar number."""
    idx = pd.date_range(f"{day} 03:45", periods=75, freq="5min", tz="UTC")
    rows = [path(i) for i in range(75)]
    return pd.DataFrame(rows, index=idx, columns=["Open", "High", "Low", "Close"]) * scale


flat = lambda i: (100.0, 100.05, 99.95, 100.0)
K = 0.01                                       # made-up NIFTYBEES = Nifty / 100: Nifty 10,000, ETF 100


def both(days, path):
    e = pd.concat([day_bars(d, path) for d in days])
    return e, e / K


# (a) a positional short can't be held overnight
e, n = both(["2026-11-02", "2026-11-03"], flat)
fresh([call(1, "2026-11-02T05:00:00Z", side="short", horizon="positional")], etf_bars=e, nifty_bars=n)
be.main()
r = be.read_results()
assert len(r) == 1 and r.iloc[0]["outcome"] == "short can't be held overnight" and r.iloc[0]["units"] == "0"
ok("a positional short isn't copied")

# (b) a positional long: overnight, out at the end of the saved window -> delivery charges with the DP charge
def rising(i):
    return (100.0 + i * 0.01, 100.06 + i * 0.01, 99.96 + i * 0.01, 100.01 + i * 0.01)
days = [str(d.date()) for d in pd.bdate_range("2026-10-05", periods=12)]
e, n = both(days, rising)
fresh([call(2, "2026-10-05T05:00:00Z", horizon="positional")], etf_bars=e, nifty_bars=n)
be.main()
r = be.read_results()
on = r[r["variant"] == "ontime"].iloc[0]
assert on["product"] == "CNC" and on["outcome"] == "time" and on["units"] == "99", dict(on)
fill, exit_ = float(on["fill"]), float(on["exit"])
want = zerodha.charges(99 * fill * 1.00015, 99 * exit_ * 0.99985, "CNC", "equity_etf")
assert want["dp"] == 15.34 and want["brokerage"] == 0 and abs(float(on["charges_rs"]) - want["total"]) < 0.011
assert abs(float(on["stop"]) - fill * 0.985) < 0.006                       # the 1.5% default for a positional Nifty call
assert pd.Timestamp(on["exit_at"]) <= pd.Timestamp("2026-10-19T05:00:00Z")   # 14 days
ok("a positional long held overnight pays delivery charges, DP charge included")

# (b2) the same long stopped out the same day is an intraday trade for charges
def falls(i):
    p = 100.0 - i * 0.05
    return (p, p + 0.02, p - 0.06, p - 0.05)
e, n = both(days, falls)
fresh([call(3, "2026-10-05T05:00:00Z", horizon="positional")], etf_bars=e, nifty_bars=n)
be.main()
on = be.read_results().iloc[0]
assert on["product"] == "MIS" and on["outcome"] == "stop", dict(on)
ok("bought and sold the same day is charged as intraday")

# (c) posted after 3:10 pm: no trade, one line
e, n = both(["2026-11-02"], flat)
fresh([call(4, "2026-11-02T09:41:00Z")], etf_bars=e, nifty_bars=n)
be.main()
r = be.read_results()
assert len(r) == 1 and r.iloc[0]["outcome"] == "after 3:10 pm"
# posted at 3:00 pm: on time trades, 15 minutes late doesn't
fresh([call(5, "2026-11-02T09:29:00Z")], etf_bars=e, nifty_bars=n)
be.main()
r = be.read_results()
assert list(r["outcome"]) == ["time", "after 3:10 pm", "after 3:10 pm"] and r.iloc[0]["exit_at"] == "2026-11-02T09:40:00Z"
ok("nothing new after 3:10 pm; an open trade is closed at 3:10 pm")

# (d) his later posts: a stop moved to a Nifty level is converted, "entry" means the NIFTYBEES fill
def up_then_down(i):
    p = 100.0 + min(i, 20) * 0.05 - max(0, i - 20) * 0.05
    return (p, p + 0.03, p - 0.03, p)
e, n = both(["2026-11-02"], up_then_down)
upd = [{"id": "9", "call_id": "6", "posted_at": "2026-11-02T04:30:00Z", "action": "stop", "detail": "", "price": "10040",
        "trigger": "", "verdict": "", "note": "stop to 10040", "added_by": "test"}]
fresh([call(6, "2026-11-02T03:50:00Z", stop="9950", target="10300")], upd, etf_bars=e, nifty_bars=n)
be.main()
on = be.read_results().iloc[0]
assert on["outcome"] == "moved stop" and on["exit"] == "100.40" and on["stop"] == "99.50", dict(on)
upd[0]["price"] = "entry"
fresh([call(7, "2026-11-02T03:50:00Z", stop="9950", target="10300")], [dict(upd[0], call_id="7")], etf_bars=e, nifty_bars=n)
be.main()
on = be.read_results().iloc[0]
assert on["outcome"] == "moved stop" and on["exit"] == on["fill"], dict(on)
ok("stop moves in his later posts are converted to NIFTYBEES prices")

# (e) no NIFTYBEES bars for the day: wait; give up only once Yahoo can't have them any more
e, n = both(["2026-11-03"], flat)
fresh([call(8, "2026-11-02T05:00:00Z")], etf_bars=e, nifty_bars=pd.concat([day_bars("2026-11-02", flat), day_bars("2026-11-03", flat)]) / K)
be.GIVE_UP_DAYS = 10 ** 4
be.main()
assert len(be.read_results()) == 0 and [str(c["id"]) for c in be.pending()] == ["8"]
e2 = pd.concat([day_bars("2026-11-02", flat).iloc[:40], e])              # Yahoo sent only part of the day
e2.round(5).to_csv(bars_file(be.SYMBOL), index_label="time")
be.main()
assert len(be.read_results()) == 0 and [str(c["id"]) for c in be.pending()] == ["8"]   # half a day is never scored
e3 = pd.concat([day_bars("2026-11-02", flat).drop(day_bars("2026-11-02", flat).index[[20, 30]]), e])
e3.round(5).to_csv(bars_file(be.SYMBOL), index_label="time")
be.main()
assert len(be.read_results()) == 3                                       # two missing bars out of 56 are fine
os.remove(be.RESULTS)
e.round(5).to_csv(bars_file(be.SYMBOL), index_label="time")
be.GIVE_UP_DAYS = 0
be.main()
r = be.read_results()
assert len(r) == 1 and r.iloc[0]["outcome"] == "no saved prices" and be.pending() == []
be.GIVE_UP_DAYS = 58
ok("a call without NIFTYBEES prices waits, then is closed as 'no saved prices'")

# (f) Nifty has no bar at that moment: its last close in the 15 minutes before is used; none at all -> wait
e, n = both(["2026-11-02"], flat)
gap = n.drop(n.index[(n.index >= "2026-11-02 05:00") & (n.index < "2026-11-02 05:10")])
k, t0 = be.ratio(e, gap, pd.Timestamp("2026-11-02T05:01:00Z"))
assert t0 == pd.Timestamp("2026-11-02T05:05:00Z") and abs(k - K) < 1e-12
assert be.ratio(e, n.iloc[:5], pd.Timestamp("2026-11-02T05:01:00Z")) == (None, None)
assert be.ratio(e, n, pd.Timestamp("2026-11-03T05:01:00Z")) == (None, None)
e2d, n2d = both(["2026-11-02", "2026-11-03"], flat)
assert be.ratio(e2d, n2d, pd.Timestamp("2026-11-02T10:30:00Z")) == (None, None)            # next bar is tomorrow's
assert be.ratio(e2d, n2d, pd.Timestamp("2026-11-02T10:30:00Z"), same_day=False)[1] == pd.Timestamp("2026-11-03T03:45:00Z")
assert be.covered(e2d, pd.Timestamp("2026-11-02T03:00:00Z"), pd.Timestamp("2026-11-02T09:40:00Z"))
assert not be.covered(e2d.iloc[40:], pd.Timestamp("2026-11-02T03:00:00Z"), pd.Timestamp("2026-11-02T09:40:00Z"))
ok("the ratio falls back to Nifty's last close, and is missing when prices are")

# (g) non-Nifty calls, unscorable calls and plain option-premium calls are left alone
rows = [call(10, "2026-11-02T05:00:00Z", instrument="GOLD"), call(11, "2026-11-02T05:00:00Z", scorable="no", kind="option", note="Sell 22800 CE at Rs 25"),
        call(12, "2026-11-02T05:00:00Z", scorable="no", kind="option", note="Shorts on a line on a chart"),
        call(13, "2026-11-02T05:00:00Z", scorable="no", kind="level", note="levels on a chart image")]
rows[1]["side"] = "short"
fresh(rows, etf_bars=e, nifty_bars=n)
be.main()
r = be.read_results()
assert set(r["id"]) == {"11"} and set(r["book"]) == {"options"} and r.iloc[0]["side"] == "short" and r.iloc[0]["target"] == ""
ok("only Nifty calls the record scores are copied; an options trade is copied by direction only")

# (h) whole units: a position that can't buy one unit is 'too small'
be.POSITION = 50.0
fresh([call(14, "2026-11-02T05:00:00Z")], etf_bars=e, nifty_bars=n)
be.main()
assert list(be.read_results()["outcome"]) == ["too small"]
be.POSITION = 10000.0
ok("less than one unit is no trade")

print("berlin etf: all checks passed")
