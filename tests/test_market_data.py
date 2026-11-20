"""market_data.py's Yahoo download on replies stood in for (no network): a session still trading is never saved,
whether it is today's bar before the cutoff or, for CME metals and Brent, the next session that opens in the New
York evening and carries the old date until midnight (the bug of 19 Nov 2026); finished bars are kept, a saved
wrong row is replaced by the next download, and a bar in the Indian or London day is handled the same way.
    python tests/test_market_data.py <repo copy> <scratch folder>    (or: python tests/run_tests.py market_data)
"""
import io
import json
import os
import sys

import pandas as pd

REPO, TMP = os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2])
sys.path.insert(0, REPO)
os.chdir(TMP)
import market_data as md  # noqa: E402

checks = 0


def ok(cond, what):
    global checks
    checks += 1
    assert cond, what


def stamp(text, zone):
    return int(pd.Timestamp(text, tz=zone).timestamp())


def reply(zone, bars):
    """A chart reply like Yahoo's: bars are (timestamp text in the exchange zone, open, high, low, close)."""
    return {"chart": {"result": [{"meta": {"dataGranularity": "1d", "exchangeTimezoneName": zone},
                                   "timestamp": [stamp(b[0], zone) for b in bars],
                                   "indicators": {"quote": [{k: [b[i] for b in bars]
                                                             for i, k in ((1, "open"), (2, "high"), (3, "low"), (4, "close"))}]}}],
                      "error": None}}


class Fake:
    def __init__(self, data):
        self.data = data

    def __enter__(self):
        return io.StringIO(json.dumps(self.data))

    def __exit__(self, *a):
        return False


def fetch(data, symbol, zone, cutoff, now):
    md.urllib.request.urlopen = lambda req, timeout=20: Fake(data)
    return md.yahoo(symbol, "1mo", zone, cutoff, now=pd.Timestamp(now, tz=zone))


NY = "America/New_York"
# COMEX gold as Yahoo gave it at 11:33 pm New York on 19 Nov 2026: finished days stamped at midnight, and the
# 20 Nov session (open since 6 pm) stamped with its last trade, 19 Nov 23:33
gold = [("2026-11-16 00:00", 3869.7, 3904.3, 3835.2, 3853.0), ("2026-11-17 00:00", 3859.5, 3894.0, 3839.2, 3864.2),
        ("2026-11-18 00:00", 3855.2, 3859.3, 3721.8, 3741.9), ("2026-11-19 00:00", 3730.3, 3759.5, 3620.6, 3685.5),
        ("2026-11-19 23:33", 3633.8, 3638.1, 3518.5, 3525.6)]
df = fetch(reply(NY, gold), "GC=F", NY, "17:30", "2026-11-19 23:40")
ok(df.index[-1] == pd.Timestamp("2026-11-19") and df.loc["2026-11-19", "Close"] == 3685.5 and len(df) == 4,
   f"in the New York evening, 19 Nov keeps its finished bar and the open 20 Nov session is left out: {df.tail(2)}")
df = fetch(reply(NY, gold[:4] + [("2026-11-20 00:30", 3633.8, 3638.1, 3518.5, 3530.0)]), "GC=F", NY, "17:30", "2026-11-20 00:35")
ok(df.index[-1] == pd.Timestamp("2026-11-19") and df.loc["2026-11-19", "Close"] == 3685.5, "after midnight the same session is today's, still out")
df = fetch(reply(NY, gold[:4] + [("2026-11-20 10:00", 3633.8, 3638.1, 3518.5, 3560.0)]), "GC=F", NY, "17:30", "2026-11-20 10:05")
ok(df.index[-1] == pd.Timestamp("2026-11-19"), "during the day session, today's bar is out until the cutoff")
done = gold[:4] + [("2026-11-20 00:00", 3633.8, 3638.1, 3518.5, 3540.0)]
df = fetch(reply(NY, done), "GC=F", NY, "17:30", "2026-11-20 17:35")
ok(df.index[-1] == pd.Timestamp("2026-11-20") and df.loc["2026-11-20", "Close"] == 3540.0, "after the cutoff, the finished day is in")
df = fetch(reply(NY, gold[:4] + [("2026-11-20 16:59", 3633.8, 3638.1, 3518.5, 3540.0)]), "GC=F", NY, "17:30", "2026-11-20 17:35")
ok(df.index[-1] == pd.Timestamp("2026-11-20"), "a finished bar still stamped with its last trade is in too")
df = fetch(reply(NY, done + [("2026-11-22 18:20", 3540.0, 3550.0, 3500.0, 3510.0)]), "GC=F", NY, "17:30", "2026-11-22 18:25")
ok(df.index[-1] == pd.Timestamp("2026-11-20") and len(df) == 5, "Sunday evening: Monday's session is left out, nothing dated Sunday")
ok(fetch(reply(NY, gold), "GC=F", NY, "17:30", "2026-11-21 10:00").index[-1] == pd.Timestamp("2026-11-19"),
   "the next day, a bar stamped in the previous evening is still the open session")

# the next download puts the finished bar in place of a wrong row saved earlier
cached = pd.DataFrame({"Open": [3855.2, 3633.8], "High": [3859.3, 3638.1], "Low": [3721.8, 3552.1], "Close": [3741.9, 3557.9]},
                      index=pd.DatetimeIndex(["2026-11-18", "2026-11-19"], name="Date"))
merged = md.merge(cached, fetch(reply(NY, gold), "GC=F", NY, "17:30", "2026-11-19 23:40"))
ok(merged.loc["2026-11-19", "Close"] == 3685.5 and len(merged) == 4, "merge: the saved 19 Nov row is revised")

# Indian shares: Yahoo stamps the open session at its 9:15 start, so only the cutoff tells
IN = "Asia/Kolkata"
nifty = [("2026-11-18 09:15", 25323.2, 25390.8, 25141.8, 25227.9), ("2026-11-19 09:15", 25186.8, 25514.3, 25104.8, 25514.3),
         ("2026-11-20 09:15", 25368.0, 25543.7, 25345.2, 25500.2)]
ok(fetch(reply(IN, nifty), "^NSEI", IN, "16:00", "2026-11-20 10:20").index[-1] == pd.Timestamp("2026-11-19"), "Nifty at 10:20 am: today's bar out")
ok(fetch(reply(IN, nifty), "^NSEI", IN, "16:00", "2026-11-20 16:05").index[-1] == pd.Timestamp("2026-11-20"), "at 4:05 pm: in")
ok(fetch(reply(IN, nifty), "^NSEI", IN, "16:00", "2026-11-21 09:00").index[-1] == pd.Timestamp("2026-11-20"), "the day after: in")
# the rupee, a 24-hour market with a 23:59 cutoff: a bar stamped in the evening is today's, still trading
LN = "Europe/London"
inr = [("2026-11-18 00:00", 93.2, 93.5, 93.1, 93.4), ("2026-11-19 00:00", 93.4, 93.6, 93.3, 93.47), ("2026-11-20 21:30", 93.47, 93.7, 93.4, 93.6)]
ok(fetch(reply(LN, inr), "INR=X", LN, "23:59", "2026-11-20 21:35").index[-1] == pd.Timestamp("2026-11-19"), "USD/INR at 9:35 pm: today's bar out")
ok(fetch(reply(LN, inr[:2] + [("2026-11-20 00:00", 93.47, 93.7, 93.4, 93.6)]), "INR=X", LN, "23:59", "2026-11-21 08:00").index[-1]
   == pd.Timestamp("2026-11-20"), "next morning: in")
print(f"market data: {checks} checks passed")
