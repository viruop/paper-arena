"""real_money.py, the real-money ledger: its sums against hand sums on the saved prices, the paper agent with the
same money, corrections, every check (the public-file check included), futures, only-added-to, and the command line.
    python tests/test_real_money.py <repo copy> <scratch folder>    (or: python tests/run_tests.py real_money)
It works on its own copy of the repository, with the saved prices and paper values cut off after 9 Nov 2026 (the
day the sums below were checked by hand); those files only ever grow, so the cut gives the same numbers every time.
"""
import os
import shutil
import subprocess
import sys

import pandas as pd

REPO, TMP = os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2])
repo = os.path.join(TMP, "repo")
shutil.copytree(REPO, repo, ignore=shutil.ignore_patterns("site", "__pycache__", ".git", "intraday", "fno", "akash", "berlin"))
os.chdir(repo)
sys.path.insert(0, repo)
import real_money as rm     # noqa: E402
import zerodha              # noqa: E402

AS_OF = "2026-11-09"
for name in ("NIFTYBEES", "GOLDBEES", "SILVERBEES"):
    path = os.path.join(rm.PRICE_DIR, f"{name}.csv")
    if os.path.exists(path):
        df = pd.read_csv(path, dtype=str, keep_default_na=False)
        df[df["Date"] <= AS_OF].to_csv(path, index=False)
daily = pd.read_csv(rm.DAILY, dtype=str, keep_default_na=False)
daily[daily["date"] <= AS_OF].to_csv(rm.DAILY, index=False)
os.makedirs(os.path.dirname(rm.FILE), exist_ok=True)

ok = lambda name: print(f"  ok  {name}")  # noqa: E731
HEAD = ",".join(rm.COLS) + "\n"
T = "2026-11-10T04:00:00Z"
NEXT_YEAR = rm.today().year + 1                    # a date that is always in the future


def ledger(*rows):
    """Write a ledger from short tuples: (id, date, action, symbol, quantity, price, amount, charges, product, agent, note)."""
    lines = []
    for i, r in enumerate(rows):
        r = list(r) + [""] * (11 - len(r))
        lines.append(",".join(str(x) for x in r) + f",2026-11-{10 + i // 60:02d}T04:{i % 60:02d}:00Z")
    open(rm.FILE, "w").write(HEAD + "\n".join(lines) + ("\n" if lines else ""))


def problems():
    return rm.check()


def run(*args):
    return subprocess.run([sys.executable, "real_money.py", *args], capture_output=True, text=True)


gold = pd.read_csv("data/market/GOLDBEES.csv", index_col=0, parse_dates=True)["Close"]
nifty = pd.read_csv("data/market/NIFTYBEES.csv", index_col=0, parse_dates=True)["Close"]
daily = pd.read_csv("logs/daily.csv", parse_dates=["date"])
agent = "Nifty-gold switch"
paper = daily[daily["agent"] == agent].set_index("date")["value"]
last_day = nifty.index[-1]
assert str(last_day.date()) == "2026-11-09", last_day

# ---------------------------------------------------------------- empty
ledger()
assert problems() == [] and not rm.summary()["started"]
ok("an empty ledger is fine and shows nothing started")

# ---------------------------------------------------------------- a plain ETF account, against hand sums
ledger((1, "2026-10-28", "deposit", "", "", "", 5000, "", "", agent),
       (2, "2026-10-28", "buy", "GOLDBEES", 42, 117.10, "", 1.05, "CNC", agent, "first order"),
       (3, "2026-11-04", "sell", "GOLDBEES", 42, 116.30, "", "", "CNC", agent),
       (4, "2026-11-04", "buy", "NIFTYBEES", 17, 272.40, "", 0.92, "CNC", agent),
       (5, "2026-11-05", "fee", "", "", "", 23.6, "", "", "", "pledge charge"))
assert problems() == [], problems()
s = rm.summary()
est_sell = zerodha.cost(0, 42 * 116.30, "CNC", "metal_etf")
assert abs(est_sell - (15.34 + round(42 * 116.30 * 0.0000297, 2) + 0.0 + round(0.18 * round(42 * 116.30 * 0.0000297, 2), 2))) < 0.011, est_sell
cash = 5000 - 42 * 117.10 - 1.05 + 42 * 116.30 - est_sell - 17 * 272.40 - 0.92 - 23.6
want_value = cash + 17 * nifty.loc[last_day]
assert abs(s["cash"] - cash) < 1e-6 and abs(s["value"] - want_value) < 1e-6, (s["cash"], cash, s["value"], want_value)
assert s["put_in"] == 5000 and abs(s["pnl"] - (want_value - 5000)) < 1e-6 and abs(s["pnl_pct"] - (want_value - 5000) / 5000) < 1e-12
assert abs(s["charges"] - (1.05 + est_sell + 0.92 + 23.6)) < 1e-9 and s["estimated"] == 1
assert abs(s["realised"] - 42 * (116.30 - 117.10)) < 1e-9
h = s["holdings"]
assert len(h) == 1 and h[0]["symbol"] == "NIFTYBEES" and h[0]["units"] == 17 and h[0]["priced"] and abs(h[0]["avg"] - 272.40) < 1e-9
assert abs(h[0]["gain"] - 17 * (nifty.loc[last_day] - 272.40)) < 1e-6
assert s["first"] == pd.Timestamp("2026-10-28") and s["asof"] == last_day and s["followed"] == {agent: 5000.0}
# the daily series: each day valued at that day's closes with that day's holdings
ser = s["series"]
d = pd.Timestamp("2026-10-30")
assert abs(ser.at[d, "value"] - (5000 - 42 * 117.10 - 1.05 + 42 * gold.loc[d])) < 1e-6
d = pd.Timestamp("2026-11-04")
assert abs(ser.at[d, "value"] - (5000 - 42 * 117.10 - 1.05 + 42 * 116.30 - est_sell - 17 * 272.40 - 0.92 + 17 * nifty.loc[d])) < 1e-6
assert list(ser.index) == [x for x in nifty.index if x >= pd.Timestamp("2026-10-28")]
ok("cash, value, gain, charges and the daily series match hand sums on the saved prices")

# the paper agent with the same money: 5,000 joins at the agent's close on 28 Oct
want_paper = 5000 * paper.loc[last_day] / paper.loc["2026-10-28"]
assert abs(s["paper"] - want_paper) < 1e-6, (s["paper"], want_paper)
assert abs(ser.at[pd.Timestamp("2026-10-28"), "paper"] - 5000) < 1e-9
ok("the paper comparison joins the agent at the deposit day's close")

# ---------------------------------------------------------------- deposits on other days, withdrawals, unknown agents
ledger((1, "2026-10-24", "deposit", "", "", "", 3000, "", "", agent),            # a Saturday, before the agent's first day
       (2, "2026-11-03", "deposit", "", "", "", 2000, "", "", agent),
       (3, "2026-11-05", "withdraw", "", "", "", 1000, "", "", agent),
       (4, "2026-11-05", "deposit", "", "", "", 500, "", "", "Berlin calls"),
       (5, "2026-11-06", "deposit", "", "", "", 250))
assert problems() == [], problems()
s = rm.summary()
first = paper.index[0]
want = (3000 / paper.loc[first] + 2000 / paper.loc["2026-11-03"] - 1000 / paper.loc["2026-11-05"]) * paper.loc[last_day] + 500 + 250
assert abs(s["paper"] - want) < 1e-6, (s["paper"], want)
assert s["put_in"] == 4750 and abs(s["value"] - 4750) < 1e-9 and s["holdings"] == []
assert any("Berlin calls" in w for w in s["warnings"]) and len(s["warnings"]) == 1
assert abs(s["series"].at[pd.Timestamp("2026-10-26"), "paper"] - 3000) < 1e-9      # waiting for the agent's first close
assert s["series"].index[0] == pd.Timestamp("2026-10-24")
ok("weekend deposits, withdrawals, and money with no paper agent are handled and explained")

# ---------------------------------------------------------------- corrections and cancellations are new rows
ledger((1, "2026-10-28", "deposit", "", "", "", 5000),
       (2, "2026-10-28", "buy", "GOLDBEES", 40, 117.10, "", 1.0),
       (3, "2026-10-29", "buy", "GOLDBEES", 2, 116.40, "", 0.1),
       (2, "2026-10-28", "buy", "GOLDBEES", 41, 117.00, "", 1.0, "", "", "quantity and price corrected"),
       (3, "2026-10-29", "void", "", "", "", "", "", "", "", "typed twice"))
assert problems() == [], problems()
s = rm.summary()
assert s["holdings"][0]["units"] == 41 and abs(s["cash"] - (5000 - 41 * 117.00 - 1.0)) < 1e-9 and len(s["rows"]) == 2
ok("a later row with the same id corrects a row; 'void' cancels it")

# ---------------------------------------------------------------- an intraday trade with leverage, and a short within the day
ledger((1, "2026-11-03", "deposit", "", "", "", 5000),
       (2, "2026-11-03", "sell", "NIFTYBEES", 37, 269.23, "", 4.9, "MIS"),
       (3, "2026-11-03", "buy", "NIFTYBEES", 37, 269.77, "", 4.9, "MIS"),
       (4, "2026-11-03", "buy", "NIFTYBEES", 70, 269.00, "", "", "MIS"),          # Rs 18,830 on Rs 5,000: intraday margin
       (5, "2026-11-03", "sell", "NIFTYBEES", 70, 269.50, "", "", "MIS"))
assert problems() == [], problems()
s = rm.summary()
e4, e5 = zerodha.cost(70 * 269.00, 0, "MIS", "equity_etf"), zerodha.cost(0, 70 * 269.50, "MIS", "equity_etf")
assert abs(s["cash"] - (5000 + 37 * (269.23 - 269.77) - 9.8 + 70 * 0.5 - e4 - e5)) < 1e-6 and s["holdings"] == [] and s["estimated"] == 2
assert abs(s["realised"] - (37 * (269.23 - 269.77) + 35.0)) < 1e-9
ok("a short and a leveraged trade closed the same day are fine; missing charges are estimated per order")

# ---------------------------------------------------------------- a commodity future moves only its profit or loss
ledger((1, "2026-11-02", "deposit", "", "", "", 5000),
       (2, "2026-11-02", "buy", "GOLDPETAL", 2, 14800, "", 12.0, "MCX"),
       (3, "2026-11-04", "sell", "GOLDPETAL", 1, 14950, "", 6.0, "MCX"),
       (4, "2026-11-05", "sell", "GOLDM", 1, 148000, "", 45.0, "MCX"),           # a short future, held overnight
       (5, "2026-11-06", "buy", "GOLDM", 1, 147500, "", 45.0, "MCX"))
assert problems() == [], problems()
s = rm.summary()
assert abs(s["cash"] - (5000 - 12 + 150 - 6 - 45 + 5000 - 45)) < 1e-9, s["cash"]       # GOLDM: Rs 500 x 10 = 5,000
h = s["holdings"]
assert len(h) == 1 and h[0]["symbol"] == "GOLDPETAL" and h[0]["units"] == 1 and h[0]["future"] and not h[0]["priced"]
assert abs(h[0]["gain"] - 150) < 1e-9 and abs(s["value"] - (s["cash"] + 150)) < 1e-9      # valued at the last trade, 14,950
assert any("GOLDPETAL" in w for w in s["warnings"])
ledger((1, "2026-11-02", "deposit", "", "", "", 5000), (2, "2026-11-02", "buy", "GOLDSOMETHING", 1, 100, "", "", "MCX"))
assert any("isn't an MCX contract" in p for p in problems())
ok("futures: only profit, loss and charges move cash; shorts can be held; unknown contracts are refused")

# ---------------------------------------------------------------- every check
def bad(rows, text, header=None):
    ledger(*rows)
    if header is not None:
        body = open(rm.FILE).read().split("\n", 1)[1]
        open(rm.FILE, "w").write(header + "\n" + body)
    got = problems()
    assert any(text in p for p in got), (text, got)

dep = (1, "2026-10-28", "deposit", "", "", "", 5000)
bad([dep], "first line must be exactly", header="id,date,action")
bad([(1, f"{NEXT_YEAR}-01-01", "deposit", "", "", "", 5000)], "in the future")
bad([(1, "28-10-2026", "deposit", "", "", "", 5000)], "must look like")
bad([("x", "2026-10-28", "deposit", "", "", "", 5000)], "whole number from 1")
bad([(1, "2026-10-28", "gift", "", "", "", 5000)], "action must be one of")
bad([(1, "2026-10-28", "deposit", "", "", "", -5)], "more than 0")
bad([(1, "2026-10-28", "deposit", "GOLDBEES", "", "", 5000)], "has only an amount")
bad([dep, (2, "2026-10-28", "buy", "goldbees", 10, 117)], "in capitals")
bad([dep, (2, "2026-10-28", "buy", "GOLDBEES", 1.5, 117)], "whole number of units")
bad([dep, (2, "2026-10-28", "buy", "GOLDBEES", 10, 0)], "average price")
bad([dep, (2, "2026-10-28", "buy", "GOLDBEES", 10, 117, 1170)], "has no amount")
bad([dep, (2, "2026-10-28", "buy", "GOLDBEES", 10, 117, "", -1)], "charges must be rupees")
bad([dep, (2, "2026-10-28", "buy", "GOLDBEES", 10, 117, "", "", "NRML")], "product must be")
bad([dep, (2, "2026-10-28", "buy", "GOLDBEES", 100, 117)], "more than the account held")
bad([dep, (2, "2026-10-28", "sell", "GOLDBEES", 5, 117)], "was sold than the account held")
bad([dep, (2, "2026-10-28", "buy", "GOLDBEES", 10, 117), (3, "2026-10-29", "sell", "GOLDBEES", 11, 117)], "was sold than the account held")
bad([dep, (9, "2026-10-28", "void")], "no earlier row with id 9")
bad([(1, "2026-10-28", "deposit", "", "", "", 5000, "", "", "", "PAN ABCDE1234F")], "This file is public")
bad([(1, "2026-10-28", "deposit", "", "", "", 5000, "", "", "", "from account 123456789012")], "This file is public")
bad([(1, "2026-10-28", "deposit", "", "", "", 5000, "", "", "", "mail me at someone@example.com")], "This file is public")
ledger(dep, (2, "2026-10-28", "buy", "GOLDBEES", 40, 117.1, "", "", "", "", "bought 40 @ 117.10 in two fills"))
assert problems() == [], problems()                                       # an ordinary note with @ and numbers is fine
lines = open(rm.FILE).read().splitlines()
open(rm.FILE, "w").write("\n".join([lines[0], lines[2], lines[1]]) + "\n")
assert any("added_at is earlier" in p for p in problems())
ok("20 kinds of mistake are each caught with a plain reason")

# ---------------------------------------------------------------- only ever added to (--base)
ledger(dep, (2, "2026-10-28", "buy", "GOLDBEES", 40, 117.1))
base_dir = os.path.join(TMP, "rm_base")
os.makedirs(base_dir, exist_ok=True)
shutil.copy(rm.FILE, os.path.join(base_dir, "orders.csv"))
assert rm.check(base=base_dir) == []
open(rm.FILE, "a").write("3,2026-10-29,fee,,,,10,,,,AMC,2026-11-11T05:00:00Z\n")
assert rm.check(base=base_dir) == [] and rm.check(base=os.path.join(base_dir, "orders.csv")) == []
text = open(rm.FILE).read().replace(",40,117.1,", ",41,117.1,")
open(rm.FILE, "w").write(text)
assert any("only ever added to" in p for p in rm.check(base=base_dir))
ok("--base proves rows were only added")

# ---------------------------------------------------------------- the command line
open(rm.FILE, "w").write(HEAD)
r = run("--check"); assert r.returncode == 0 and "looks fine" in r.stdout, r.stdout + r.stderr
r = run("--add", "deposit", "5000", "--agent", agent, "--date", "2026-10-28"); assert r.returncode == 0 and "Saved" in r.stdout, r.stdout + r.stderr
r = run("--add", "buy", "goldbees", "42", "117.10", "--charges", "1.05", "--agent", agent, "--date", "2026-10-28", "--note", "first order")
assert r.returncode == 0 and "symbol=GOLDBEES" in r.stdout, r.stdout + r.stderr
before = open(rm.FILE).read()
r = run("--add", "buy", "GOLDBEES", "500", "117.10", "--date", "2026-10-29"); assert r.returncode == 1 and "Not saved" in r.stdout and open(rm.FILE).read() == before
r = run("--add", "sell", "GOLDBEES", "42"); assert r.returncode == 1 and open(rm.FILE).read() == before
r = run("--add", "void", "--id", "7"); assert r.returncode == 1 and open(rm.FILE).read() == before
r = run("--add", "buy", "GOLDBEES", "1", "117", "--date", f"{NEXT_YEAR}-01-01"); assert r.returncode == 1 and open(rm.FILE).read() == before
r = run("--add", "sell", "GOLDBEES", "42", "116.30", "--date", "2026-11-04"); assert r.returncode == 0, r.stdout
r = run("--add", "sell", "GOLDBEES", "42", "116.80", "--id", "3", "--note", "price corrected"); assert r.returncode == 0, r.stdout      # no --date: the row's own
assert rm.read().iloc[-1]["date"] == "2026-11-04" and rm.read().iloc[-1]["product"] == "CNC"
df = rm.read()
assert list(df["id"]) == ["1", "2", "3", "3"] and before in open(rm.FILE).read() and open(rm.FILE).read().startswith(before)
assert rm.summary()["holdings"] == [] and abs(rm.summary()["realised"] - 42 * (116.80 - 117.10)) < 1e-9
r = run(); assert "Real account on" in r.stdout and "prices up to 2026-11-09" in r.stdout and "Put in" in r.stdout and "Paper agent with the same money" in r.stdout, r.stdout
r = run("--check"); assert r.returncode == 0
open(rm.FILE, "a").write("4,2026-11-05,sell,GOLDBEES,5,117,,,,,,2026-11-11T05:00:00Z\n")
r = run("--check"); assert r.returncode == 1 and "problem" in r.stdout
r = run("--add", "fee", "10"); assert r.returncode == 1 and "problems already" in r.stdout          # a broken ledger takes no new rows
ok("the command line adds checked rows, refuses bad ones without touching the file, and reports")

# an intraday trade is written one half at a time: the first half is saved with a warning, a delivery order isn't
open(rm.FILE, "w").write(HEAD)
run("--add", "deposit", "5000", "--date", "2026-11-03")
r = run("--add", "sell", "NIFTYBEES", "37", "269.23", "--product", "MIS", "--date", "2026-11-03")
assert r.returncode == 0 and "Saved" in r.stdout and "isn't square yet" in r.stdout and "more NIFTYBEES was sold" in r.stdout, r.stdout
assert run("--check").returncode == 1                                              # the final check still says so
r = run("--add", "buy", "NIFTYBEES", "37", "269.77", "--product", "MIS", "--date", "2026-11-03")
assert r.returncode == 0 and "isn't square" not in r.stdout and run("--check").returncode == 0, r.stdout
r = run("--add", "buy", "NIFTYBEES", "70", "269.00", "--product", "MIS", "--date", "2026-11-04")        # leverage: Rs 18,830 on Rs 5,000
assert r.returncode == 0 and "isn't square yet" in r.stdout and "more than the account held" in r.stdout, r.stdout
r = run("--add", "sell", "NIFTYBEES", "70", "269.50", "--product", "MIS", "--date", "2026-11-04")
assert r.returncode == 0 and run("--check").returncode == 0
before = open(rm.FILE).read()
r = run("--add", "sell", "GOLDBEES", "5", "117", "--date", "2026-11-05")           # a delivery sale of something not held
assert r.returncode == 1 and "Not saved" in r.stdout and open(rm.FILE).read() == before
r = run("--add", "void", "--id", "2", "--note", "wrong day")                       # cancelling keeps the row's date
assert r.returncode == 0 and rm.read().iloc[-1]["date"] == "2026-11-03" and "isn't square yet" in r.stdout, r.stdout
r = run("--add", "void", "--id", "3", "--note", "wrong day")                       # ... and its other half squares the day again
assert r.returncode == 0 and "isn't square" not in r.stdout and run("--check").returncode == 0, r.stdout
assert len(rm.settled(rm.read())) == 3
ok("an intraday trade can be written one half at a time; a delivery order that doesn't add up is refused")

# the default date is today in India, and the id counts up
open(rm.FILE, "w").write(HEAD)
run("--add", "deposit", "100")
df = rm.read()
assert df.iloc[0]["date"] == rm.today().isoformat() and df.iloc[0]["id"] == "1" and df.iloc[0]["added_at"].endswith("Z")
ok("defaults: today's date in India, the next id, a UTC time")

print("real money: all checks passed")
