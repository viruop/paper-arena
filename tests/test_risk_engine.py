"""Tests for risk_engine.py (written 13 Nov 2026).

    python tests/test_risk_engine.py <repo copy> <scratch folder>    (or: python tests/run_tests.py risk)

1. The engine's sums agree with the order ticket's own JavaScript (one rulebook, two copies).
2. Every check refuses what it should and lets through what it should.
3. The nightly run only ever adds rows, replays what it logged, and waits for what isn't known yet.
"""
import math
import os
import random
import shutil
import sys

import pandas as pd

REPO, TMP = os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2])
sys.path.insert(0, REPO)
os.chdir(REPO)
import risk_engine as re_  # noqa: E402
import ticket  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

checks = 0


def ok(cond, what):
    global checks
    checks += 1
    assert cond, what


def at(text):
    """A time in India as UTC."""
    return pd.Timestamp(text).tz_localize("Asia/Kolkata").tz_convert("UTC")


def order(**kw):
    o = {"id": "t", "stream": "t", "at": at("2026-11-13 11:00"), "instrument": "NIFTYBEES", "side": "buy",
         "intent": "open", "product": "MIS", "style": "trade", "price": 288.20, "last": 288.20,
         "last_at": at("2026-11-13 11:00"), "stop": 286.00, "target": 293.00}
    o.update(kw)
    return o


def failed(o, acct=None, halt_at=None, holidays=frozenset({"2026-11-10", "2026-11-24"})):
    d = re_.decide(o, acct or re_.Account(), halt_at, holidays)
    return d["failed"], d


# ------------------------------------------------------------------ 1. the same sums as the ticket's JavaScript
os.makedirs(TMP, exist_ok=True)
page_path = os.path.join(TMP, "ticket_for_engine.html")
with open(page_path, "w", encoding="utf-8") as f:
    f.write(ticket.page())
rng = random.Random(13)
cases = []
for i in range(1500):
    mkt = rng.choice(["nifty", "nifty", "nifty", "gold", "crude"])
    if mkt == "nifty":
        contract, price = "NIFTYBEES", round(rng.uniform(250, 300), 2)
        stop_d = rng.choice([0.001, 0.002, 0.003, 0.005, 0.01, 0.015, 0.03]) * rng.uniform(0.7, 1.3)
    elif mkt == "gold":
        contract = rng.choice(["GOLDPETAL", "GOLDGUINEA", "GOLDTEN", "GOLDM"])
        price = {"GOLDPETAL": 14800, "GOLDGUINEA": 118000, "GOLDTEN": 148000, "GOLDM": 148000}[contract] * rng.uniform(0.95, 1.05)
        price = round(price)
        stop_d = rng.choice([0.002, 0.004, 0.008, 0.015]) * rng.uniform(0.7, 1.3)
    else:
        contract, price = "CRUDEOILM", round(rng.uniform(7000, 8200))
        stop_d = rng.choice([0.005, 0.01, 0.02, 0.03]) * rng.uniform(0.7, 1.3)
    side = rng.choice(["long", "short"])
    sign = 1 if side == "long" else -1
    horizon = "day" if mkt != "nifty" else rng.choice(["day", "day", "days"])
    stop = round(price * (1 - sign * stop_d), 2)
    target = round(price * (1 + sign * stop_d * rng.choice([0.5, 1, 1.5, 2, 3, 5])), 2) if rng.random() < 0.8 else None
    account = rng.choice([5000, 5000, 20000, 100000, 500000, 2000000])
    cases.append({"inp": {"market": mkt, "contract": contract, "side": side, "horizon": horizon, "his": price,
                          "stop": stop, "target": target, "rr": None, "trade": price, "marginLot": None},
                  "account": account})
with sync_playwright() as pw:
    browser = pw.chromium.launch()
    page = browser.new_page()
    page.goto(f"file://{page_path}")
    page.wait_for_function("!!(window.ticket && window.ticket.compute)")
    js = page.evaluate("""(cases) => cases.map(c => {
        const rules = {account: c.account, riskPct: 2, maxLosses: 2, maxTrades: 3, minRR: 1.5, maxCostPct: 25};
        const o = window.ticket.compute(c.inp, rules, {trades: 0, losses: 0}, new Date('2026-11-13T05:30:00Z'));
        return {need: o.need || null, n: o.n, costPct: o.costPct === undefined ? null : o.costPct,
                rrAfter: o.rrAfter === undefined ? null : o.rrAfter,
                checks: (o.checks || []).map(x => [x.ok, x.text])};
    })""", cases)
    browser.close()
agree = 0
for c, j in zip(cases, js):
    inp = c["inp"]
    product = "MCX" if inp["market"] != "nifty" else ("MIS" if inp["horizon"] == "day" else "CNC")
    o = order(instrument=inp["contract"], side="buy" if inp["side"] == "long" else "sell", product=product,
              price=inp["trade"], last=inp["trade"], stop=inp["stop"], target=inp["target"])
    f, d = failed(o, re_.Account(c["account"]))
    if j["need"]:
        ok(False, f"the ticket asked for input on a valid case: {c} {j}")
    sizes = [w for w in d["checks"] if w[0] == "size"]
    ok(d["quantity"] == j["n"], f"quantity: engine {d['quantity']} against ticket {j['n']} for {c}")
    if j["n"] >= 1:
        ok(abs(d["cost_pct"] - j["costPct"]) < 1e-6, f"costs: {d['cost_pct']} against {j['costPct']} for {c}")
        jcost = [x for x in j["checks"] if x[1].startswith("Charges and the spread")][0][0]
        ok(("costs" in f) == (jcost is False), f"costs check differs for {c}")
        jrew = [x for x in j["checks"] if x[1].startswith("After costs the target")]
        if jrew:
            ok(abs(d["rr_after"] - j["rrAfter"]) < 1e-9, f"reward: {d['rr_after']} against {j['rrAfter']} for {c}")
            ok(("reward" in f) == (jrew[0][0] is False), f"reward check differs for {c}")
        else:
            ok(d["rr_after"] is None, "no target, no reward figure")
    else:
        ok("size" in f and sizes and sizes[0][1] is False, f"both refuse a size of zero for {c}")
    jshort = [x for x in j["checks"] if x[1].startswith("A short can only be held for the day")]
    ok(bool(jshort) == ("short" in f), f"the short rule differs for {c}")
    agree += 1
print(f"  ticket agreement: {agree} random orders, the same quantity, costs and verdicts")

# ------------------------------------------------------------------ 2. each check
base = order()
f, d = failed(base)
ok(f == [] and d["approved"] and d["quantity"] == 38, f"a sound order goes through: {f}, {d['quantity']}")
ok(abs(d["risk_rs"] - 98.41) < 0.01 and d["value"] > 5000, "38 units lose Rs 98.41 at the stop, inside Rs 100")

# market
for inst, product, words in (("NZDCAD", "", "offshore forex"), ("XAUUSD", "", "offshore CFD"), ("NAS100", "", "offshore CFD"),
                             ("GOLD", "", "US exchange"), ("CRUDE", "", "US exchange"), ("BTC", "", "crypto"),
                             ("NIFTY", "", "can't be bought"), ("NIFTY", "OPT", "options aren't in the engine"),
                             ("RELIANCE", "MIS", "isn't on the engine's list"), ("NIFTYBEES", "MCX", "can't be traded as MCX"),
                             ("GOLDPETAL", "MIS", "can't be traded as MIS")):
    f, d = failed(order(instrument=inst, product=product))
    ok(f == ["market"] and words in d["reason"], f"{inst} {product}: {f} {d['reason']}")
f, d = failed(order(instrument="GOLDPETAL", product="MCX", price=14800, last=14800, stop=14600, target=15300), re_.Account(20000))
ok(f == [] and d["quantity"] == 1, f"one Gold Petal lot fits a Rs 20,000 account: {f}")
f, d = failed(order(instrument="GOLDPETAL", product="MCX", price=14800, last=14800, stop=14760, target=14950))
ok(f == ["costs"], f"in Rs 5,000, a 40-point stop is mostly costs: {f}")
f, d = failed(order(instrument="GOLDPETAL", product="MCX", price=14800, last=14800, stop=14700, target=15100))
ok(f == ["size"] and "even one lot loses" in d["reason"], f"with a 100-point stop it doesn't: {d['reason']}")

# session
for when, good, words in (("2026-11-14 11:00", False, "the market is shut"), ("2026-11-10 11:00", False, "NSE holiday"),
                          ("2026-11-13 09:14", False, "outside NSE's hours"), ("2026-11-13 09:15", True, ""),
                          ("2026-11-13 14:40", True, ""), ("2026-11-13 14:41", False, "too late"),
                          ("2026-11-13 15:31", False, "outside")):
    f, d = failed(order(at=at(when), last_at=at(when)))
    ok(("session" not in f) == good and (good or words in d["reason"]), f"{when}: {f} {d['reason']}")
f, d = failed(order(at=at("2026-11-13 15:29"), last_at=at("2026-11-13 15:29"), style="allocation", product="CNC", weight=1.0, quantity=10))
ok("session" not in f, "an end-of-day order at 3:29 pm is in hours")
f, d = failed(order(instrument="GOLDPETAL", product="MCX", price=14800, last=14800, stop=14700, target=15100,
                    at=at("2026-11-13 21:00"), last_at=at("2026-11-13 21:00")))
ok("session" not in f, "MCX trades in the evening")
f, d = failed(order(instrument="GOLDPETAL", product="MCX", price=14800, last=14800, stop=14700, target=15100,
                    at=at("2026-11-13 22:31"), last_at=at("2026-11-13 22:31")))
ok("session" in f, "but no new MCX intraday trade after 10:30 pm")

# fresh price and price check
f, _ = failed(order(last_at=at("2026-11-13 10:51")))
ok("fresh price" not in f, "9 minutes old is fresh")
f, _ = failed(order(last_at=at("2026-11-13 10:49")))
ok("fresh price" in f, "11 minutes old is stale")
f, _ = failed(order(last_at=at("2026-11-13 11:03")))
ok("fresh price" in f, "a price from after the order is refused")
f, _ = failed(order(style="allocation", product="CNC", weight=1.0, quantity=10, last_at=at("2026-11-09 15:28"), at=at("2026-11-13 15:29")))
ok("fresh price" in f, "an end-of-day order on a close 4 days and a minute old is refused")
f, _ = failed(order(style="allocation", product="CNC", weight=1.0, quantity=10, last_at=at("2026-11-09 15:30"), at=at("2026-11-13 15:29")))
ok("fresh price" not in f, "but 4 days is fine (a long weekend)")
f, _ = failed(order(price=288.20, last=289.70))
ok("price check" in f, "0.52% from the last price is refused")
f, _ = failed(order(price=288.20, last=289.60))
ok("price check" not in f, "0.48% is fine")

# stop, target, short
f, d = failed(order(stop=None))
ok(f == ["stop", ] or "stop" in f, "no stop, no trade")
f, d = failed(order(stop=289.0))
ok("stop" in f and "wrong side" in d["reason"], "a stop above a buy is refused")
f, d = failed(order(side="sell", stop=290.40, target=283.00))
ok(f == [], f"an intraday short is fine: {f}")
f, d = failed(order(side="sell", stop=290.40, target=283.00, product="CNC"))
ok("short" in f, "a delivery short is refused")
f, d = failed(order(target=287.0))
ok("target" in f, "a target already passed is refused")
f, d = failed(order(stop=287.90, target=288.80))
ok("costs" in f and "reward" in f, f"a 0.1% stop: costs swamp it: {f}")
f, d = failed(order(target=None))
ok(f == [] and [c for c in d["checks"] if c[0] == "reward"][0][1] is None, "no target: a note, not a refusal")

# the day's tally
acct = re_.Account()
acct.roll(at("2026-11-13 10:00"))
acct.trades = 3
f, _ = failed(order(), acct)
ok("trades today" in f, "a fourth trade in a day is refused")
acct = re_.Account(); acct.roll(at("2026-11-13 10:00")); acct.losses = 2
f, _ = failed(order(), acct)
ok("losses today" in f, "after two losses, nothing more that day")
acct = re_.Account(); acct.roll(at("2026-11-13 10:00")); acct.day_pnl = -200.0
f, _ = failed(order(), acct)
ok("day loss" in f, "4% lost in a day stops new trades")
acct = re_.Account(); acct.roll(at("2026-11-12 10:00")); acct.trades, acct.losses, acct.day_pnl = 3, 2, -300.0
f, _ = failed(order(), acct)
ok(not {"trades today", "losses today", "day loss"} & set(f), "a new day starts a new tally")

# repeats and the order rate
acct = re_.Account()
acct.recent = [(at("2026-11-13 10:50"), "NIFTYBEES", "buy")]
f, _ = failed(order(), acct)
ok("repeat" in f, "the same buy 10 minutes later is a repeat")
acct.recent = [(at("2026-11-13 10:44"), "NIFTYBEES", "buy")]
f, _ = failed(order(), acct)
ok("repeat" not in f, "16 minutes later it isn't")
acct.recent = [(at("2026-11-13 10:55"), "NIFTYBEES", "sell")]
f, _ = failed(order(), acct)
ok("repeat" not in f, "the opposite side isn't a repeat")
acct.recent = [(at("2026-11-13 10:59") + pd.Timedelta(seconds=5 + 10 * k), f"X{k}", "buy") for k in range(5)]
f, _ = failed(order(), acct)
ok("order rate" in f, "a sixth order inside a minute is refused")
acct.recent = [(at("2026-11-13 10:59") + pd.Timedelta(seconds=10 * k), f"X{k}", "buy") for k in range(5)]
f, _ = failed(order(), acct)
ok("order rate" not in f, "but an order a full minute old no longer counts")

# halts and the kill switch: new risk refused, exits always allowed
acct = re_.Account()
ok(not acct.mark(4600, at("2026-11-13 10:00")) and acct.mark(4500, at("2026-11-13 10:05")) and acct.halted,
   "the drawdown halt trips at 10% below the peak, not before")
ok(not acct.mark(6000, at("2026-11-14 10:00")) and acct.halted, "and stays on even if the account recovers")
f, d = failed(order(), acct)
ok("drawdown halt" in f, "a halted account takes no new risk")
acct.held = {"NIFTYBEES": 10}
f, d = failed(order(intent="close", side="sell", quantity=10, product="CNC", style="allocation"), acct)
ok(d["approved"] and d["quantity"] == 10, "but can always sell what it holds")
f, d = failed(order(), halt_at=at("2026-11-13 10:30"))
ok("kill switch" in f, "the kill switch refuses orders after its time")
f, d = failed(order(), halt_at=at("2026-11-13 11:30"))
ok("kill switch" not in f, "and not orders before it")
acct = re_.Account(); acct.held = {"NIFTYBEES": 5}
f, d = failed(order(intent="close", side="sell", quantity=9, product="CNC", style="allocation"), acct, halt_at=at("2026-11-13 10:30"))
ok(d["approved"] and d["quantity"] == 5, "with the kill switch on, an exit still goes, capped at what is held")
f, d = failed(order(intent="close", side="sell", quantity=1, product="CNC", style="allocation"), re_.Account())
ok(not d["approved"] and "position" in f, "selling what isn't held is refused")
halt_file = os.path.join(TMP, "HALT")
open(halt_file, "w").write("2026-12-15 10:42\nstopped by hand\n")
ok(re_.halt_since(halt_file) == at("2026-12-15 10:42"), "the kill switch file's time is read as India time")
open(halt_file, "w").write("stop everything\n")
ok(re_.halt_since(halt_file, now=at("2026-11-13 12:00")) == at("2026-11-13 12:00"), "without a time, it counts from now")
os.remove(halt_file)
ok(re_.halt_since(halt_file) is None, "no file, no kill switch")

# end-of-day orders
a = re_.Account()
f, d = failed(order(style="allocation", product="CNC", weight=1.0, quantity=19, at=at("2026-11-13 15:29"), last_at=at("2026-11-13 15:29"), price=257.22, last=257.22), a)
ok(d["approved"] and d["quantity"] == 19, f"19 NIFTYBEES fit in Rs 5,000: {f}")
f, d = failed(order(style="allocation", product="CNC", weight=1.0, quantity=20, at=at("2026-11-13 15:29"), last_at=at("2026-11-13 15:29"), price=257.22, last=257.22), a)
ok(d["approved"] and d["quantity"] == 19, "asking for 20 buys the 19 the cash allows")
f, d = failed(order(style="allocation", product="CNC", weight=1.5, quantity=10, at=at("2026-11-13 15:29"), last_at=at("2026-11-13 15:29")), a)
ok("weight" in f, "more than 100% of the account would borrow")
poor = re_.Account(100)
f, d = failed(order(style="allocation", product="CNC", weight=1.0, quantity=1, at=at("2026-11-13 15:29"), last_at=at("2026-11-13 15:29")), poor)
ok("money" in f, "Rs 100 doesn't buy a Rs 288 unit")
re_.ENGINE["maxAllocCostPct"], keep = 0.01, re_.ENGINE["maxAllocCostPct"]
f, d = failed(order(style="allocation", product="CNC", weight=1.0, quantity=19, at=at("2026-11-13 15:29"), last_at=at("2026-11-13 15:29"), price=257.22, last=257.22))
re_.ENGINE["maxAllocCostPct"] = keep
ok("costs" in f, "charges above the limit refuse an end-of-day order")

# holdings in the daily log
ok(re_.holding_of("NIFTY 50") == ("NIFTYBEES", 1.0) and re_.holding_of("50% NIFTY 50") == ("NIFTYBEES", 0.5)
   and re_.holding_of("Cash") == (None, 0.0) and re_.holding_of("GOLDBEES") == ("GOLDBEES", 1.0)
   and re_.holding_of("NIFTY PHARMA") is None and re_.holding_of("Long 1 lot of futures") is None, "holdings map onto ETFs")
ok(re_.to_tick(2.345, 0.01) == math.floor(234.5 + 1e-9 + 0.5) * 0.01 and re_.to_tick(14800.5, 1) == 14801, "ticks round halves up, as JavaScript does")

# ------------------------------------------------------------------ 3. the nightly run: add only
work = os.path.join(TMP, "riskrun")
shutil.rmtree(work, ignore_errors=True)
os.makedirs(os.path.join(work, "logs"))
log = os.path.join(work, "logs", "risk_orders.csv")

# The run reads the arena's logs, which only ever grow. So these checks stay fixed, it reads them as they
# stood at 3 pm UTC on 13 Nov 2026, when they were written; rows are only ever added, so that's exact.
AS_OF = "2026-11-13T15:00:00Z"


def as_of(path, column, limit, name):
    df = pd.read_csv(path, dtype=str, keep_default_na=False)
    out = os.path.join(work, name)
    df[df[column] <= limit].to_csv(out, index=False)
    return out


re_.DAILY = as_of(re_.DAILY, "date", AS_OF[:10], "daily.csv")
re_.BERLIN_ETF = as_of(re_.BERLIN_ETF, "scored_at", AS_OF, "berlin_etf.csv")
re_.BERLIN_CALLS = as_of(re_.BERLIN_CALLS, "posted_at", AS_OF, "berlin_calls.csv")
re_.AKASH_CALLS = [as_of(p, "posted_at", AS_OF, f"akash_{k}.csv") for k, p in enumerate(re_.AKASH_CALLS)]
now1 = pd.Timestamp("2026-11-13T15:00:00Z")
new1 = re_.run(now=now1, log_path=log)
ok(len(new1) > 20 and os.path.exists(log), f"the first run writes the log ({len(new1)} rows)")
before = open(log, "rb").read()
new2 = re_.run(now=now1 + pd.Timedelta(days=1), log_path=log)
ok(new2 == [] and open(log, "rb").read() == before, "a second run adds nothing and changes nothing")
df = pd.read_csv(log, dtype=str, keep_default_na=False)
ok(df["id"].is_unique, "every order is in the log once")
ok(set(df["decision"]) <= {"approved", "refused", "halt"} and (df["version"] == re_.VERSION).all(), "every row says which rules decided it")
ok(((df["stream"] == "akash") <= (df["decision"] == "refused")).all() and ((df["stream"] == "berlin-other") <= (df["decision"] == "refused")).all(),
   "offshore and unmapped calls are all refused")
bn = df[df["stream"] == "berlin-nifty"]
ok(len(bn) and (bn["failed"].str.contains("costs")).all(), "his Nifty calls at a 0.2% stop are refused on costs in a Rs 5,000 account")
agents = df[df["stream"].str.startswith("agent-")]
ok(len(agents) >= 5 and (agents["decision"] == "approved").all(), "the ETF agents' orders go through")
cl = df[df["stream"] == "agent-claude"]
ok(list(cl["intent"]) == ["open", "add"] and list(cl["quantity"]) == ["9", "9"], f"Claude: half on 26 Oct, the rest on 3 Nov: {list(cl['quantity'])}")

# a source that changes later never rewrites a row; a new source row is added once
etf_src = re_.BERLIN_ETF
tmp_src = os.path.join(work, "berlin_etf.csv")
src = pd.read_csv(etf_src, dtype=str, keep_default_na=False)
first = src[(src["variant"] == "ontime") & (src["book"] == "calls") & (src["fill_at"] != "")].index[0]
src.loc[first, "fill"] = "999.99"
extra = src.loc[[first]].copy()
extra["id"], extra["fill_at"], extra["exit_at"] = "99999", "2026-11-12T05:00:00Z", "2026-11-12T06:00:00Z"
extra["fill"], extra["stop"], extra["target"], extra["exit"], extra["outcome"] = "288.00", "286.00", "292.00", "292.00", "target"
extra["side"] = "long"
pd.concat([src, extra]).to_csv(tmp_src, index=False)
re_.BERLIN_ETF = tmp_src
try:
    new3 = re_.run(now=now1 + pd.Timedelta(days=2), log_path=log)
finally:
    re_.BERLIN_ETF = etf_src
after = open(log, "rb").read()
ok(after.startswith(before), "earlier rows are untouched, byte for byte, when a source changes")
ok([r["id"] for r in new3] == ["berlin-nifty:99999"], f"only the new call is added: {[r['id'] for r in new3]}")
r = new3[0]
ok(r["decision"] == "approved" and float(r["pnl_rs"]) > 0 and r["exit_at"] == "2026-11-12T06:00:00Z",
   f"a wide-stop call fits the rules and its result is logged with it: {r['decision']} {r['reason']} {r['pnl_rs']}")

# the drawdown halt is logged once, then refuses the rest
halt_src = os.path.join(work, "losses.csv")
rows = []
for k in range(8):
    day = pd.Timestamp("2026-11-02") + pd.Timedelta(days=k + (2 if k >= 5 else 0))
    rows.append({"id": f"L{k}", "variant": "ontime", "book": "calls", "side": "long", "product": "MIS", "ratio": "0.0114",
                 "units": "10", "fill_at": f"{day.date()}T05:00:00Z", "fill": "280.00", "stop": "277.00", "target": "288.00",
                 "exit_at": f"{day.date()}T06:00:00Z", "exit": "277.00", "outcome": "stop", "move_rs": "", "slip_rs": "",
                 "charges_rs": "", "pnl_rs": "", "pct": "", "r": "", "scored_at": ""})
pd.DataFrame(rows).to_csv(halt_src, index=False)
log2 = os.path.join(work, "logs", "halt_test.csv")
re_.BERLIN_ETF = halt_src
keep_daily, keep_b, keep_a = re_.DAILY, re_.BERLIN_CALLS, re_.AKASH_CALLS
re_.DAILY, re_.BERLIN_CALLS, re_.AKASH_CALLS = os.path.join(work, "none.csv"), os.path.join(work, "none.csv"), []
try:
    h1 = re_.run(now=now1, log_path=log2)
    h2 = re_.run(now=now1 + pd.Timedelta(days=1), log_path=log2)
finally:
    re_.BERLIN_ETF, re_.DAILY, re_.BERLIN_CALLS, re_.AKASH_CALLS = etf_src, keep_daily, keep_b, keep_a
hd = pd.read_csv(log2, dtype=str, keep_default_na=False)
ok((hd["decision"] == "halt").sum() == 1 and h2 == [], "the halt is logged once, and a second run adds nothing")
pos = hd.index[hd["decision"] == "halt"][0]
ok((hd.loc[: pos - 1, "decision"] == "approved").all() and (hd.loc[pos + 1:, "failed"].str.contains("drawdown halt")).all()
   and pos + 1 < len(hd), f"orders after it are refused: {list(hd['decision'])}")
eq_at_halt = float(hd.loc[pos, "equity_after"])
ok(eq_at_halt <= 5000 * 0.9 + 1e-6 and float(hd.loc[pos - 1, "equity_before"]) > 4500, f"it tripped at the first close 10% below the peak ({eq_at_halt})")

# summary for the page
s = re_.summary(log)
ok(s and {x["stream"] for x in s["streams"]} >= {"berlin-nifty", "agent-claude", "akash", "berlin-other"}, "the summary covers every account")
bn_s = [x for x in s["streams"] if x["stream"] == "berlin-nifty"][0]
ok(bn_s["approved"] == 1 and bn_s["trades"] == 1 and bn_s["pnl"] > 0 and abs(bn_s["value"] - (5000 + bn_s["pnl"])) < 1e-6,
   "the summary's result for his calls is the one approved trade")
ok(s["kill"] is None and "Momentum rotation" in s["skipped"], "the kill switch is off and the agents left out are named")
print(f"risk engine: {checks} checks passed")
