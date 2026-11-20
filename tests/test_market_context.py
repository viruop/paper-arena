"""market_context.py's second source for FII/DII flows: NSE's own figures on top of the dataset's, and every way
that can fail (blocked, stale, malformed, implausible), the saved copy while the dataset lags, and the fall-back
when the dataset is down. No network: NSE and the dataset are stood in for.
    python tests/test_market_context.py <repo copy> <scratch folder>    (or: python tests/run_tests.py market)
"""
import os
import shutil
import sys
import warnings

import pandas as pd

warnings.filterwarnings("ignore")
REPO, TMP = os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2])
repo = os.path.join(TMP, "repo")
shutil.copytree(REPO, repo, ignore=shutil.ignore_patterns("site", "__pycache__", ".git", "intraday", "fno", "akash", "berlin"))
os.chdir(repo)                      # the saved copies it writes stay in this copy
sys.path.insert(0, repo)
import market_context as mc  # noqa: E402

checks = 0


def ok(cond, what):
    global checks
    checks += 1
    assert cond, what


def boom():
    raise RuntimeError("HTTP Error 403: Forbidden")


mc.nse_flows.__defaults__ = (boom, None)          # NSE can't be reached unless a test says otherwise

# ------------------------------------------------------------------ NSE's reply
TODAY = pd.Timestamp("2026-11-11")
REAL = [{"buyValue": "19704.39", "category": "DII", "date": "11-Nov-2026", "netValue": "-8434.53", "sellValue": "28138.92"},
        {"buyValue": "30087.21", "category": "FII/FPI", "date": "11-Nov-2026", "netValue": "12563.33", "sellValue": "17523.88"}]
row = mc.nse_flows(lambda: REAL, today=TODAY)
ok(list(row.index) == [TODAY] and row.iloc[0]["FII_Net_Cr"] == 12563.33 and row.iloc[0]["DII_Net_Cr"] == -8434.53,
   "NSE's real reply of 11 Nov 2026 is read correctly")


def fails(rows, today=TODAY):
    try:
        mc.nse_flows(lambda: rows, today=today)
        return False
    except Exception:
        return True


ok(fails([]) and fails(REAL[:1]) and fails(REAL + REAL), "an empty, half or doubled reply is refused")
ok(fails([dict(REAL[0], date="10-Nov-2026"), REAL[1]]), "two different days are refused")
ok(fails([dict(r, date="12-Nov-2026") for r in REAL]), "a reply dated tomorrow is refused")
ok(fails([dict(r, date="20-Oct-2026") for r in REAL]), "a stale reply is refused")
ok(fails([dict(REAL[0], netValue="n/a"), REAL[1]]) and fails([dict(REAL[0], netValue="9999999"), REAL[1]]), "odd numbers are refused")
ok(fails([dict(r, date="2026-11-11") for r in REAL]) and fails({"error": "blocked"}), "another date format or an error page is refused")
ok(not fails([dict(REAL[0], netValue="-8,434.53"), REAL[1]]), "thousands separators are fine")

# ------------------------------------------------------------------ adding NSE's day to the dataset's
real_today = pd.Timestamp.now(tz="Asia/Kolkata").tz_localize(None).normalize()
days = pd.bdate_range(end=real_today - pd.Timedelta(days=1), periods=30)        # the dataset, up to the last weekday before today
base = pd.DataFrame({"FII_Net_Cr": [1000.0 + i for i in range(30)], "DII_Net_Cr": [-500.0 - i for i in range(30)]},
                    index=pd.DatetimeIndex(days, name="Date"))
fresh = [dict(r, date=f"{real_today:%d-%b-%Y}") for r in REAL]
out, day = mc.with_nse(base, lambda: fresh)
ok(day == real_today and len(out) == len(base) + 1 and out.iloc[-1]["FII_Net_Cr"] == 12563.33, "NSE's newer day is added")
out, day = mc.with_nse(base, boom)
ok(day is None and out.equals(base), "a failure changes nothing")
out, day = mc.with_nse(base, lambda: [dict(r, date=f"{days[-1]:%d-%b-%Y}") for r in REAL])
ok(day is None and out.equals(base), "a day the dataset already has keeps the dataset's figures")

# the whole path with the dataset stood in for: NSE's saved day survives until the dataset catches up
mc._save(mc.SAVED_FLOWS, base)
ds = base.reset_index()
mc._read_parquet = lambda url: ds.copy()
got = mc.flows(10, fetch=lambda: fresh)
ok(got.attrs.get("nse") and got.index[-1] == real_today and "NSE's provisional figures" in " ".join(mc.describe({"breadth": None, "flows": got})),
   "NSE's day is shown, marked provisional")
saved = mc._read_saved(mc.SAVED_FLOWS)
ok(saved.index[-1] == real_today and saved.iloc[-1]["DII_Net_Cr"] == -8434.53, "and saved")
got = mc.flows(10, fetch=boom)
ok(got.index[-1] == real_today and not got.attrs.get("nse") and len(mc._read_saved(mc.SAVED_FLOWS)) == len(saved),
   "the next night, with NSE blocked and the dataset still behind, the saved day is kept")
caught_up = pd.concat([ds, pd.DataFrame({"Date": [real_today], "FII_Net_Cr": [12001.0], "DII_Net_Cr": [-8000.0]})])
mc._read_parquet = lambda url: caught_up.copy()
got = mc.flows(10, fetch=boom)
ok(got.index[-1] == real_today and got.iloc[-1]["FII_Net_Cr"] == 12001.0 and mc._read_saved(mc.SAVED_FLOWS).iloc[-1]["FII_Net_Cr"] == 12001.0,
   "once the dataset has the day, its figure replaces NSE's")
ok(not mc._read_saved(mc.SAVED_FLOWS).index.duplicated().any(), "no day saved twice")


def down(url):
    raise RuntimeError("dataset down")


mc._read_parquet = down
ctx = mc.context()
ok(ctx["flows"] is not None and ctx["flows"].attrs.get("saved"), "with the dataset down, the saved copy is used")
ok(ctx["breadth"] is not None, "and the saved breadth too")
print(f"market context: {checks} checks passed")
