"""The signal channel's code (signal_calls.py, dukascopy.py, channels.py) on made-up prices: fills at the bid and
ask, targets, his breakeven and exits, a minute touching stop and target, limits never reached, late and reversed
checks, the weekend close, the wait for posts marked "needs review", Claude's answers kept in files of their own,
Dukascopy's tick files, and the nightly price check.
    python tests/test_signal_calls.py <repo copy> <scratch folder>    (or: python tests/run_tests.py signal)
Claude's answers are tested on the channel's posts as saved on 4 Nov 2026 (tests/data/akash_posts_2026-11-04.csv):
the live archive was started again later, so those posts aren't in it.
"""
import json
import lzma
import os
import shutil
import struct
import sys

import pandas as pd

REPO, TMP = os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2])
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, REPO)
os.chdir(TMP)                       # anything written goes in the scratch folder
import berlin_calls as bc  # noqa: E402
import channels  # noqa: E402
import dukascopy as dk  # noqa: E402
import signal_calls as sc  # noqa: E402

checks = 0


def ok(cond, what):
    global checks
    checks += 1
    assert cond, what


# ------------------------------------------------------------------ 1. scoring a signal on one-minute bid and ask bars
def bars(rows, start="2026-10-30 10:01", spread=0.3):
    idx = pd.date_range(start, periods=len(rows), freq="1min", tz="UTC")
    df = pd.DataFrame(rows, columns=["bid_o", "bid_h", "bid_l", "bid_c"], index=idx)
    for c in "ohlc":
        df[f"ask_{c}"] = df[f"bid_{c}"] + spread
    return df


def pad(df, minutes=1500):
    last = df.iloc[-1]
    idx = pd.date_range(df.index[-1] + pd.Timedelta(minutes=1), periods=minutes, freq="1min", tz="UTC")
    return pd.concat([df, pd.DataFrame([last.values] * minutes, columns=df.columns, index=idx)])


def call(**kw):
    c = {"id": "1", "posted_at": "2026-10-30T10:00:20Z", "kind": "signal", "instrument": "XAUUSD", "side": "long",
         "entry_type": "market", "entry": "", "stop": "3990.6", "target": "3997.209", "rr": "", "horizon": "scalp",
         "exit_at": "", "price_ref": "", "scorable": "yes", "note": ""}
    c.update(kw)
    return c


def upd(action, posted, trigger=""):
    return {"id": "9", "call_id": "1", "posted_at": posted, "action": action, "detail": "", "price": "entry", "trigger": trigger}


b = pad(bars([[3993.0, 3994.0, 3992.5, 3993.5], [3993.5, 3997.3, 3993.4, 3997.0]]))
r = sc.score_signal(call(), b)
ok(r[0]["fill"] == 3993.3 and r[0]["outcome"] == "target" and abs(r[0]["exit"] - 3997.209) < 1e-9,
   f"a long fills at the ask and reaches its target on the bid: {r}")
b = pad(bars([[3993.0, 3994.0, 3992.5, 3993.5], [3993.5, 3996.2, 3993.4, 3995.0], [3995.0, 3995.1, 3993.0, 3993.2]]))
r = sc.score_signal(call(), b, [upd("stop_when", "2026-10-30T10:00:50Z", "3996.132")])
ok(r[0]["outcome"] == "moved stop" and abs(r[0]["r"]) < 1e-9, f"his breakeven once 3996.132 is reached: out at entry: {r}")
ok(sc.score_signal(call(), b)[0]["outcome"] == "time", "without his breakeven: out when the window ends")
b = pad(bars([[3993.0, 3998.0, 3990.0, 3995.0]]))
ok(sc.score_signal(call(), b)[0]["outcome"] == "stop", "a minute touching both stop and target counts as the stop")
c4 = call(side="short", entry_type="limit", entry="77985.79", stop="78123.4", target="77850|77711.46", instrument="BTCUSD")
b = pad(bars([[77900, 77950, 77880, 77940], [77940, 77990, 77930, 77980], [77980, 77985, 77840, 77845], [77845, 77860, 77800, 77820]],
             spread=10))
r = sc.score_signal(c4, b, [upd("exit", "2026-10-30T10:04:30Z")])
ok(r[0]["fill"] == 77985.79 and r[0]["outcome"] == "target 1" and r[1]["outcome"] == "his exit", f"two targets, half each: {r}")
ok(abs(sum(x["pnl_rs"] for x in r) - (500 * (77985.79 - 77850) / 137.61 + 500 * (77985.79 - 77830) / 137.61)) < 1,
   "half at the first target, his exit closes the rest")
ok(sc.score_signal(c4, pad(bars([[77900, 77950, 77880, 77940]], spread=10))) == [], "a limit never reached: no trade")
ok(sc.score_signal(call(), bars([[3993.0, 3994.0, 3992.5, 3993.5]])) is None, "the window not over in the prices given: wait")
b = pad(bars([[3993.0, 3994.0, 3992.5, 3993.5]] + [[3993.5, 3994.0, 3993.0, 3993.8]] * 20 + [[3993.8, 3997.3, 3993.7, 3997.0]]))
ok([x["variant"] for x in sc.variants(call(), b)] == ["late15", "late30", "flip"], "late and reversed checks")

# a gold signal on Friday evening: prices stop at the weekend close, and it is still scored
fri = {"id": "1", "posted_at": "2026-11-06T20:30:00Z", "kind": "signal", "instrument": "XAUUSD", "side": "long",
       "entry_type": "market", "entry": "", "stop": "3990", "target": "4020", "scorable": "yes"}
idx = pd.date_range("2026-11-06T20:00:00Z", "2026-11-06T21:59:00Z", freq="1min", tz="UTC")     # the market shuts at 22:00
wk = pd.DataFrame({f"{s}_{c}": 4000.0 + (0.2 if s == "ask" else 0) for s in ("bid", "ask") for c in "ohlc"}, index=idx)
rows = sc.score_signal(fri, wk, ended=True)
ok(sc.score_signal(fri, wk) is None and rows[0]["outcome"] == "time" and rows[0]["exit_at"] == "2026-11-06T22:00:00Z",
   f"Friday's signal ends at the weekend close: {rows}")
ok(len(sc.variants(fri, wk, ended=True)) == 3, "and gets its checks")
d = os.path.join(TMP, "weekend")
os.makedirs(os.path.join(d, "data", "t"))
os.makedirs(os.path.join(d, "logs"))
ch = {"name": "t", "handle": "t", "url": "u", "since": "2026-11-01", "start_id": 1, "folder": os.path.join(d, "data", "t"),
      "results": os.path.join(d, "logs", "t_calls.csv"), "tagging": "parser"}
row = dict.fromkeys(sc.CALL_COLS, "")
row.update(fri, horizon="scalp", note="x")
bc.append(sc.paths(ch)["calls"], sc.CALL_COLS, [row])
ok(sc.score_all(ch, bars_for=lambda inst, a, b: wk, now=pd.Timestamp("2026-11-08T21:00:00Z")) == 1, "scored on Sunday night")

# ------------------------------------------------------------------ 2. a "needs review" post inside the 24 hours holds the score
sig = pd.Series({"id": "500", "posted_at": "2026-11-02T04:00:00Z"})
rev = pd.DataFrame({"id": ["500", "501", "502"], "posted_at": ["2026-11-02T04:00:00Z", "2026-11-02T06:00:00Z", "2026-11-04T06:00:00Z"],
                    "decision": ["signal", "needs review", "needs review"]})
ok(sc.waiting_for_review(sig, [], rev) == "501", "needs review inside the window: waits")
later = pd.DataFrame({"id": ["501"], "posted_at": ["2026-11-02T06:00:00Z"], "decision": ["other"]})
ok(sc.waiting_for_review(sig, [], pd.concat([rev, later])) == "", "Claude's later answer settles it; post 502 is after the window")

# ------------------------------------------------------------------ 3. Claude's answers, on the posts saved on 4 Nov 2026
d = os.path.join(TMP, "review")
os.makedirs(os.path.join(d, "data", "akash"))
os.makedirs(os.path.join(d, "logs"))
shutil.copy(os.path.join(HERE, "data", "akash_posts_2026-11-04.csv"), os.path.join(d, "data", "akash", "telegram_posts.csv"))
ch = {"name": "t", "handle": "tradewithakashgarg", "url": "u", "since": "2026-10-27", "start_id": 18840,
      "folder": os.path.join(d, "data", "akash"), "results": os.path.join(d, "logs", "akash_calls.csv"), "tagging": "parser"}
sc.parse_new(ch, now=pd.Timestamp("2026-11-04T09:00:00Z"))
ok(sorted(sc.summary(ch)["review"]["id"]) == ["18893", "18894", "18898", "18982"], "four posts need Claude")
log = sc.read_both(sc.paths(ch), "reviewed", sc.REVIEW_COLS).set_index("id")
ok(log.loc["18982", "note"].startswith("Voice note: read its transcript"), "a voice note waits for its transcript")
p = sc.paths(ch)
bc.append(p["claude_updates"], bc.UPDATE_COLS, [{"id": "18893", "call_id": "18846", "posted_at": "2026-10-29T08:00:00Z",
          "action": "exit", "detail": "", "price": "", "trigger": "", "verdict": "", "note": "\"Closing my Nas100 Trade\"",
          "added_by": "claude"}])
bc.append(p["claude_reviewed"], sc.REVIEW_COLS, [
    {"id": "18893", "posted_at": "2026-10-29T08:00:00Z", "reviewed_at": "2026-11-04T17:40:00Z", "decision": "update",
     "call_id": "18846", "note": "Read by Claude: closes the Nas100 signal, the only Nas100 trade that day"},
    {"id": "18898", "posted_at": "x", "reviewed_at": "2026-11-04T17:40:00Z", "decision": "other", "call_id": "",
     "note": "Read by Claude: about a signal not posted here"}])
ok(sorted(sc.summary(ch)["review"]["id"]) == ["18894", "18982"], "two answered, two still waiting")
ups = sc.read_both(p, "updates", bc.UPDATE_COLS)
ok("18893" in set(ups["id"]) and len(ups) == 12, "Claude's exit is read with the code's own updates")
sig = dict(sc.read_both(p, "calls", sc.CALL_COLS).set_index("id").loc["18846"], id="18846")
idx = pd.date_range("2026-10-29T06:00:00Z", "2026-10-30T07:00:00Z", freq="1min", tz="UTC")
flat = pd.DataFrame({f"{s}_{c}": 29500.0 + (0.5 if s == "ask" else 0) for s in ("bid", "ask") for c in "ohlc"}, index=idx)
rows = sc.score_signal(sig, flat, [u for _, u in ups[ups["call_id"] == "18846"].iterrows()])
ok(all(x["outcome"] == "his exit" for x in rows) and rows[0]["exit_at"] <= "2026-10-29T08:01:00Z", "Claude's exit is used when scoring")
before = {f: open(p[f]).read() for f in ("claude_updates", "claude_reviewed")}
sc.parse_new(ch, now=pd.Timestamp("2026-11-05T09:00:00Z"))
ok(all(open(p[f]).read() == before[f] for f in before), "a later run never writes Claude's files")

# ------------------------------------------------------------------ 4. Dukascopy's hourly tick files
def make_hour(ticks, point):
    raw = b"".join(struct.pack(">IIIff", ms, round(ask * point), round(bid * point), 1.0, 1.0) for ms, ask, bid in ticks)
    return lzma.compress(raw, format=lzma.FORMAT_ALONE)


h10 = [(m * 60000 + s * 1000, 4000 + m * 0.5 + 0.2 + s * 0.01, 4000 + m * 0.5 + s * 0.01) for m in range(60) for s in (0, 20, 40)]
files = {"/XAUUSD/2026/09/30/10h_ticks.bi5": make_hour(h10, 1000), "/XAUUSD/2026/09/30/11h_ticks.bi5": b""}   # months count from 0


def opener(url):
    for k, v in files.items():
        if url.endswith(k):
            return v
    raise AssertionError(url)


m = dk.minute_bars("XAUUSD", pd.Timestamp("2026-10-30 10:00", tz="UTC"), pd.Timestamp("2026-10-30 11:30", tz="UTC"), opener=opener)
ok(len(m) == 60 and abs(m.iloc[0]["bid_o"] - 4000.0) < 1e-6 and abs(m.iloc[0]["ask_h"] - 4000.6) < 1e-6, "an hour of ticks makes 60 bars")
ok(abs(m.iloc[-1]["bid_c"] - (4000 + 59 * 0.5 + 0.4)) < 1e-6, "an empty hour (no trading) adds nothing")
files["/XAUUSD/2026/09/30/10h_ticks.bi5"] = make_hour(h10, 1)
try:
    dk.minute_bars("XAUUSD", pd.Timestamp("2026-10-30 10:00", tz="UTC"), pd.Timestamp("2026-10-30 10:59", tz="UTC"), opener=opener)
    refused = False
except RuntimeError:
    refused = True
ok(refused, "prices on the wrong scale are refused, never scored")
ok({i: dk.supported(i) for i in ("XAUUSD", "NAS100", "BTCUSD", "EURUSD", "NIFTY")} ==
   {"XAUUSD": True, "NAS100": True, "BTCUSD": True, "EURUSD": True, "NIFTY": False}, "which markets Dukascopy has")

# ------------------------------------------------------------------ 5. the nightly price check
real = dk.minute_bars
cp = os.path.join(TMP, "check.json")
dk.minute_bars = lambda inst, a, b, opener=None: pd.DataFrame({"bid_c": [3990.5, 3991.0]}, index=pd.date_range(a, periods=2, freq="1min"))
st = channels.check_prices(cp, now=pd.Timestamp("2026-11-09T01:00:00Z"))
ok(st["ok"] and st["hour"] == "2026-11-06T12:00Z", "on Monday morning it reads Friday's noon hour")


def boom(*a, **k):
    raise RuntimeError("timed out")


dk.minute_bars = boom
st = channels.check_prices(cp)
ok(st["ok"] is False and "timed out" in st["error"] and json.load(open(cp))["ok"] is False, "a failure is written down")
dk.minute_bars = real

print(f"signal calls: {checks} checks passed")
