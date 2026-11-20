"""zerodha.py against Zerodha's brokerage calculator, worked again in zerodha_calc.js beside this file (needs Node),
and against the sample on the calculator's page.
    python tests/test_zerodha.py <repo copy> [<scratch folder>]    (or: python tests/run_tests.py zerodha)"""
import json, os, random, subprocess, sys
repo = os.path.abspath(sys.argv[1]); sys.path.insert(0, repo)
import zerodha as z

here = os.path.dirname(os.path.abspath(__file__))
random.seed(11)
cases = []
for _ in range(4000):
    f = random.choice(["intra", "delivery", "mcx"])
    if f == "mcx":
        mult = random.choice([1, 10, 100])
        bp = round(random.uniform(50, 160000), random.choice([0, 1, 2])); sp = round(bp * random.uniform(0.97, 1.03), random.choice([0, 1, 2]))
        qty = random.randint(1, 30)
        cases.append({"f": f, "bp": bp, "sp": sp, "qty": qty, "mult": mult})
    else:
        bp = round(random.uniform(5, 3000), 2); sp = round(bp * random.uniform(0.95, 1.05), 2)
        qty = random.randint(1, 2000)
        if random.random() < 0.1: sp = 0.0            # a buy only
        elif random.random() < 0.1: bp = 0.0          # a sale only
        cases.append({"f": f, "bp": bp, "sp": sp, "qty": qty})
# awkward sizes on purpose: the ones this arena uses, and halves
for value in (5000, 10000, 25000, 66666.67, 66700, 200000, 0.5, 1.0, 16666.5, 16700):
    cases.append({"f": "intra", "bp": value, "sp": value, "qty": 1})
    cases.append({"f": "delivery", "bp": value, "sp": value, "qty": 1})
js = json.loads(subprocess.run(["node", os.path.join(here, "zerodha_calc.js")], input=json.dumps(cases), capture_output=True, text=True, check=True).stdout)
bad = ties = 0
for c, want in zip(cases, js):
    if c["f"] == "intra":
        got = z.charges(c["bp"] * c["qty"], c["sp"] * c["qty"], "MIS", "share")
    elif c["f"] == "delivery":
        got = z.charges(c["bp"] * c["qty"], c["sp"] * c["qty"], "CNC", "share", dp=False)
    else:
        got = z.charges(c["bp"] * c["qty"] * c["mult"], c["sp"] * c["qty"] * c["mult"], "MCX", "future")
    tie = False
    if c["f"] == "mcx":      # CTT lands exactly on half a paisa: the calculator multiplies price, quantity and lot size
        raw = c["sp"] * c["qty"] * c["mult"] * 0.0001 * 100          # in a different order, so the last bit can differ
        tie = abs(raw - int(raw) - 0.5) < 1e-6
    for k, v in want.items():
        if abs(got[k] - v) > 1e-9:
            if tie and k in ("tax", "total") and abs(got[k] - v) < 0.0101:
                ties += 1
                continue
            bad += 1
            if bad <= 12: print("DIFF", c, k, "zerodha.py", got[k], "calculator", v)
print(f"{len(cases)} cases against the calculator's arithmetic: {bad} differences "
      f"({ties // 2} MCX cases sit exactly on half a paisa of CTT and round either way)")
assert bad == 0

# the sample on Zerodha's calculator page (commodity futures): buy 250, sell 252, one lot of 1,000
c = z.charges(250 * 1000, 252 * 1000, "MCX", "future")
assert (c["brokerage"], c["exchange"], c["gst"], c["tax"], c["sebi"], c["stamp"], c["total"]) == (40.0, 10.54, 9.19, 25.2, 0.5, 5.0, 90.43), c
print("page sample (MCX futures, total Rs 90.43): matches")

# ETFs: what the support article says, which the calculator doesn't cover
e = z.charges(10000, 10000, "CNC", "equity_etf")
assert e["tax"] == 0.0 and e["brokerage"] == 0.0 and e["dp"] == 15.34 and e["stamp"] == 2.0, e   # 0.001% of 10,000 = 0.1 -> Rs 0
g = z.charges(10000, 10000, "MIS", "metal_etf")
assert g["tax"] == 0.0 and g["brokerage"] == 6.0, g
n = z.charges(10000, 10000, "MIS", "equity_etf")
assert n["tax"] == 3.0 and n["total"] == 10.82, n       # 2.5 rounds up to 3, as the calculator's Math.round does
assert z.charges(0, 5000, "CNC", "metal_etf")["dp"] == 15.34 and z.charges(5000, 0, "CNC", "metal_etf")["dp"] == 0.0
assert z.kind_of("NIFTYBEES") == "equity_etf" and z.kind_of("goldbees") == "metal_etf" and z.kind_of("RELIANCE") == "share" and z.kind_of("GOLDPETAL", "MCX") == "future"
for bad_call in (lambda: z.charges(1, 1, "NRML"), lambda: z.charges(1, 1, "MIS", "future"), lambda: z.charges(-1, 1)):
    try:
        bad_call(); raise SystemExit("should have failed")
    except ValueError:
        pass
assert abs(z.round_trip_pct(10000) - 0.001082) < 1e-12 and z.round_trip_pct(0) == 0.0
print("ETF rules, bad inputs: ok")
print(f"zerodha: {len(cases)} calculator cases, the page's sample and the ETF rules all agree")
