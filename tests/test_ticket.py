"""The order ticket in a real browser: its charges against zerodha.py, its sums against an independent
re-computation, every rule check, what it remembers, and the layout on a phone.

    python tests/test_ticket.py <repo copy> <scratch folder>    (or: python tests/run_tests.py ticket)
It works on its own copy of the repository, and leaves screenshots of the ticket (phone, light and dark) in the
scratch folder for a look."""
import math
import os
import random
import shutil
import sys
import tempfile

work, shots = os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2])
tmp = tempfile.mkdtemp(prefix="ticket_")
repo = os.path.join(tmp, "repo")
shutil.copytree(work, repo, ignore=shutil.ignore_patterns("site", "__pycache__", ".git", "intraday", "fno", "akash", "berlin"))
os.chdir(repo)
sys.path.insert(0, repo)
import warnings
warnings.filterwarnings("ignore")
import build_site      # noqa: E402
import ticket          # noqa: E402
import zerodha         # noqa: E402
from playwright.sync_api import sync_playwright   # noqa: E402

os.makedirs("site", exist_ok=True)
os.makedirs(shots, exist_ok=True)
html = ticket.page(css=build_site.CSS, hint_values={"nifty_his": 25255.05, "nifty_trade": 286.54, "gold_his": 4012.3})
open("site/ticket.html", "w", encoding="utf-8").write(html)
URL = "file://" + os.path.join(repo, "site", "ticket.html")
ok = lambda name: print(f"  ok  {name}")
RULES = dict(ticket.RULES)
MORNING = "2026-11-12T05:00:00Z"          # Thursday 10:30 am in India


def tick_round(x, tick):
    return math.floor(x / tick + 1e-9 + 0.5) * tick


def expected(inp, rules=RULES):
    """The ticket's main numbers, worked out here from zerodha.py."""
    m = ticket.MARKETS[inp["market"]]
    c = next((x for x in m["contracts"] if x["code"] == inp.get("contract")), m["contracts"][0])
    future, sign, day = inp["market"] != "nifty", (1 if inp["side"] == "long" else -1), inp["horizon"] == "day"
    product, kind = ("MCX", "future") if future else (("MIS" if day else "CNC"), "equity_etf")
    ratio, entry, mult, tick = inp["trade"] / inp["his"], inp["trade"], c["mult"], c["tick"]
    stop = tick_round(inp["stop"] * ratio if inp.get("stop") else entry * (1 - sign * m["stop"][inp["horizon"]]), tick)
    target = None
    if inp.get("target"):
        target = tick_round(inp["target"] * ratio, tick)
    elif inp.get("rr"):
        target = tick_round(entry + sign * inp["rr"] * abs(entry - stop), tick)
    slip = m["slip"]
    entry_fill, stop_fill = entry * (1 + sign * slip), stop * (1 - sign * slip)

    def net(n, exit_fill):
        a, b = n * mult * entry_fill, n * mult * exit_fill
        fees = zerodha.cost(a, b, product, kind) if sign > 0 else zerodha.cost(b, a, product, kind)
        return sign * (b - a) - fees

    limit = rules["account"] * rules["riskPct"] / 100
    margin_lot = ((inp.get("marginLot") or 0.10 * entry * mult) if future else (0.2 * entry if product == "MIS" else entry))
    n = max(0, min(math.floor(limit / (mult * abs(entry_fill - stop_fill)) + 1e-9), math.floor(rules["account"] / margin_lot + 1e-9)))
    while n > 0 and -net(n, stop_fill) > limit + 1e-9:
        n -= 1
    out = {"n": n, "stop": stop, "target": target, "product": product}
    if n:
        out["atStop"] = net(n, stop_fill)
        out["value"] = n * mult * entry
        if target is not None:
            out["atTarget"] = net(n, target)
    return out


with sync_playwright() as p:
    browser = p.chromium.launch()
    ctx = browser.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=1)
    page = ctx.new_page()
    errors = []
    page.on("console", lambda msg: errors.append(msg.text) if msg.type == "error" else None)
    page.on("pageerror", lambda exc: errors.append(str(exc)))
    page.add_init_script(f"window.__now = '{MORNING}';")
    page.goto(URL)
    assert page.inner_text("#order") == "Waiting for the numbers"
    assert "Type Nifty now" in page.inner_text("#note")

    # ------------------------------------------------------------ charges: the page against zerodha.py
    random.seed(5)
    cases = []
    for _ in range(3000):
        product, kind = random.choice([("MIS", "equity_etf"), ("CNC", "equity_etf"), ("MCX", "future"), ("MIS", "metal_etf"),
                                       ("CNC", "metal_etf"), ("MIS", "share"), ("CNC", "share")])
        v = round(random.uniform(50, 400000), 2)
        w = round(v * random.uniform(0.9, 1.1), 2)
        buy, sell = random.choice([(v, w), (v, 0), (0, w), (v, v)])
        cases.append({"buy": buy, "sell": sell, "product": product, "kind": kind})
    got = page.evaluate("cases => cases.map(c => window.ticket.charges(c.buy, c.sell, c.product, c.kind))", cases)
    for c, g in zip(cases, got):
        want = zerodha.charges(c["buy"], c["sell"], c["product"], c["kind"])
        for k, v in want.items():
            assert abs(g[k] - v) < 1e-9, (c, k, g[k], v)
    ok("the page's charges equal zerodha.py's on 3,000 cases, every line of them")

    # ------------------------------------------------------------ the sums, as a function
    def compute(inp, rules=RULES, tally=None, now=MORNING):
        full = {"contract": None, "stop": None, "target": None, "rr": None, "marginLot": None}
        full.update(inp)
        return page.evaluate("([i, r, t, n]) => { const o = window.ticket.compute(i, r, t, new Date(n)); return JSON.parse(JSON.stringify(o)); }",
                             [full, rules, tally or {"trades": 0, "losses": 0}, now])

    random.seed(9)
    n_cases = 0
    for _ in range(1500):
        market = random.choice(["nifty", "nifty", "gold", "crude"])
        side, horizon = random.choice(["long", "short"]), random.choice(["day", "days"])
        sign = 1 if side == "long" else -1
        if market == "nifty":
            his, trade, contract = random.uniform(20000, 28000), None, "NIFTYBEES"
            trade = round(his * random.uniform(0.01135, 0.01145), 2)
        elif market == "gold":
            his = random.uniform(3500, 4500)
            contract = random.choice(["GOLDPETAL", "GOLDGUINEA", "GOLDTEN", "GOLDM"])
            per = {"GOLDPETAL": 1, "GOLDGUINEA": 8, "GOLDTEN": 10, "GOLDM": 10}[contract]
            trade = float(round(his * 3.6 * per))
        else:
            his, contract = random.uniform(60, 110), "CRUDEOILM"
            trade = float(round(his * 89))
        stop_pct = random.choice([0.001, 0.002, 0.004, 0.01, 0.02, 0.05])
        inp = {"market": market, "contract": contract, "side": side, "horizon": horizon, "his": his, "trade": trade}
        if random.random() < 0.75:
            inp["stop"] = his * (1 - sign * stop_pct)
        choice = random.random()
        if choice < 0.4:
            inp["target"] = his * (1 + sign * stop_pct * random.choice([1, 2, 3]))
        elif choice < 0.7:
            inp["rr"] = random.choice([1, 1.5, 2, 3])
        if market != "nifty" and random.random() < 0.5:
            inp["marginLot"] = round(trade * ticket.MARKETS[market]["contracts"][0]["mult"] * random.uniform(0.05, 0.2))
        rules = dict(RULES, account=random.choice([5000, 10000, 25000, 100000, 500000]), riskPct=random.choice([1, 2, 5]))
        got, want = compute(inp, rules), expected(inp, rules)
        assert "need" not in got, (inp, got)
        assert got["n"] == want["n"] and got["product"] == want["product"], (inp, rules, got["n"], want)
        assert abs(got["stop"] - want["stop"]) < 1e-6 and (got["target"] is None) == (want["target"] is None), (inp, got["stop"], want)
        if want["target"] is not None:
            assert abs(got["target"] - want["target"]) < 1e-6
        if want["n"]:
            assert abs(got["atStop"] - want["atStop"]) < 1e-6 and abs(got["value"] - want["value"]) < 1e-6, (inp, got["atStop"], want)
            assert -got["atStop"] <= rules["account"] * rules["riskPct"] / 100 + 1e-6            # never over the limit
            if want["target"] is not None:
                assert abs(got["atTarget"] - want["atTarget"]) < 1e-6
                assert abs(got["rrAfter"] - want["atTarget"] / -want["atStop"]) < 1e-9
        n_cases += 1
    ok(f"quantity, stop, target and both outcomes match an independent re-computation on {n_cases} random calls")

    # one more unit would always break a limit: the quantity is the largest that fits
    inp = {"market": "nifty", "side": "long", "horizon": "day", "his": 25000.0, "trade": 285.0, "stop": 24950.0, "target": 25100.0}
    r = compute(inp, dict(RULES, account=100000, riskPct=1))
    e = expected(inp, dict(RULES, account=100000, riskPct=1))
    assert r["n"] == e["n"] and r["n"] > 100
    m = ticket.MARKETS["nifty"]
    more = r["n"] + 1
    a, b = more * 285.0 * 1.00015, more * r["stop"] * 0.99985
    assert (a - b) + zerodha.cost(a, b, "MIS", "equity_etf") > 1000 > -r["atStop"]
    ok("one more unit would lose more than the limit")

    # ------------------------------------------------------------ the form: Berlin's kind of call on a small account
    def fill(**values):
        for k, v in values.items():
            page.fill(f"#{k}", "" if v is None else str(v))

    def pick(name, value):
        page.locator(f"input[name='{name}'][value='{value}']").check(force=True)

    def stats():
        return dict(zip(page.locator("#stats dt").all_inner_texts(), page.locator("#stats dd").all_inner_texts()))

    def checks():
        return [(li.get_attribute("class"), li.inner_text()) for li in page.locator("#checks li").all()]

    def open_rules():
        if not page.evaluate("document.querySelector('details.more').open"):
            page.click("details.more >> nth=0 >> summary")                      # opened the way a person would
        assert page.is_visible("#r-account")

    pick("side", "short")
    fill(his=25000, trade=284.81, stop=25050, target=24900)
    want = expected({"market": "nifty", "side": "short", "horizon": "day", "his": 25000, "trade": 284.81, "stop": 25050, "target": 24900})
    assert want["n"] == 87, want
    assert page.inner_text("#order") == "Sell 87 NIFTYBEES, for the day (MIS)", page.inner_text("#order")
    st = stats()
    assert st["Stop"] == "₹285.38" and st["Target"] == "₹283.67", st
    assert st["If the stop is hit"] == f"−₹{-want['atStop']:,.2f}" and st["If the target is hit"] == f"+₹{want['atTarget']:,.2f}", (st, want)
    assert st["Order value"] == "₹24,778" and st["Margin needed"] == "₹4,956", st
    ch = checks()
    kinds = [c for c, _ in ch]
    assert kinds.count("no") == 2 and "Fails 2 checks: it doesn’t fit your own rules." in page.inner_text("#verdict"), ch
    assert any(c == "no" and "of the money at risk" in t for c, t in ch) and any(c == "no" and "times what the stop loses" in t for c, t in ch)
    assert any(c == "ok" and "4 hours 40 minutes until 3:10 pm" in t for c, t in ch), ch
    assert any(c == "wait" and "times your money" in t for c, t in ch)
    assert page.is_visible("#copy")
    page.click("#copy")
    page.wait_for_function("document.getElementById('copied').textContent.length > 0")     # the clipboard answers later
    assert "SELL 87 NIFTYBEES MIS at market, about ₹284.81. Stop-loss ₹285.38. Target ₹283.67. Out by 3:10 pm." in page.inner_text("#copied")
    page.screenshot(path=os.path.join(shots, "ticket-nifty-light.png"), full_page=True)
    ok("a Nifty short on Rs 5,000: the order, its outcomes and the failed checks are right, and it copies as text")

    # no stop given -> the record's 0.2%; a reward ratio instead of a target
    fill(stop=None, target=None, rr=2)
    st = stats()
    assert st["Stop (none given: 0.2%)"] == "₹285.38" and st["Target (from his ratio)"] == "₹283.67", st
    fill(rr=None)
    assert stats()["Target"] == "none" and any(c == "wait" and "No target" in t for c, t in checks())
    # a wrong-side stop and a passed target say so instead of showing nonsense
    fill(stop=24900)
    assert page.inner_text("#order") == "Check the numbers" and "wrong side" in page.inner_text("#note") and not page.is_visible("#copy")
    fill(stop=25050, target=25020)
    assert "already past his target" in page.inner_text("#note")
    fill(stop=None, target=None, his=None)
    assert page.inner_text("#order") == "Waiting for the numbers" and page.locator("#checks li").count() == 0
    ok("missing stop, reward ratio, wrong-side stop, passed target and empty boxes are each handled")

    # holding for days: a long is a delivery order, a short isn't possible
    fill(his=25000, trade=284.81, stop=24600)
    pick("side", "long"); pick("horizon", "days")
    assert page.inner_text("#order").endswith("to hold (CNC)") and "Money needed" in stats()
    pick("side", "short"); fill(stop=25400)
    assert any(c == "no" and "only be held for the day" in t for c, t in checks())
    pick("horizon", "day"); pick("side", "long"); fill(stop=24950)
    ok("days: a buy becomes a delivery order; a short for days is refused")

    # ------------------------------------------------------------ the clock (India's, whatever the phone says)
    def at(when):
        page.evaluate(f"window.__now = '{when}'")
        page.dispatch_event("#his", "input")
        return checks()
    assert any(c == "no" and "past 3:10 pm" in t for c, t in at("2026-11-12T09:45:00Z"))             # 3:15 pm
    assert any(c == "no" and "Only 20 minutes" in t for c, t in at("2026-11-12T09:20:00Z"))           # 2:50 pm
    assert any(c == "wait" and "opens at 9:15" in t for c, t in at("2026-11-12T03:00:00Z"))           # 8:30 am
    assert any(c == "wait" and "weekend" in t for c, t in at("2026-11-14T06:00:00Z"))                 # Saturday
    assert any(c == "ok" and "until 3:10 pm" in t for c, t in at("2026-11-11T18:30:00Z")) is False    # midnight IST Thursday: before the open
    assert any(c == "wait" and "opens at 9:15" in t for c, t in at("2026-11-11T18:30:00Z"))
    assert page.evaluate("window.ticket.india(new Date('2026-11-12T09:45:00Z'))") == {"day": 4, "minutes": 915}
    at(MORNING)
    ok("the time checks use India's clock: before the open, near and past 3:10 pm, the weekend")

    # ------------------------------------------------------------ today's count and the daily stop
    assert page.inner_text("#tally") == "0 trades, 0 losses today"
    page.click("#add-trade"); page.click("#add-loss")
    assert page.inner_text("#tally") == "1 trade, 1 loss today"
    page.click("#add-loss")
    assert page.inner_text("#tally") == "2 trades, 2 losses today"
    assert any(c == "no" and "your rule says stop for the day" in t for c, t in checks())
    page.reload()
    assert page.inner_text("#tally") == "2 trades, 2 losses today"                                    # it survives a reload
    page.evaluate("window.__now = '2026-11-13T05:00:00Z'")
    page.click("#add-trade")
    assert page.inner_text("#tally") == "1 trade, 0 losses today"                                     # and starts again the next day
    page.click("#reset-day")
    assert page.inner_text("#tally") == "0 trades, 0 losses today"
    for _ in range(3):
        page.click("#add-trade")
    fill(his=25000, trade=284.81, stop=24950)
    assert any(c == "no" and "3 trades today: your rule allows 3" in t for c, t in checks())
    page.click("#reset-day")
    ok("today's count: losses lock the day, it survives a reload and starts again the next day")

    # ------------------------------------------------------------ your rules are remembered; nonsense falls back
    open_rules()
    assert page.input_value("#r-account") == "5000" and page.input_value("#r-riskPct") == "2"
    page.fill("#r-account", "20000"); page.fill("#r-riskPct", "1")
    assert expected({"market": "nifty", "side": "long", "horizon": "day", "his": 25000, "trade": 284.81, "stop": 24950},
                    dict(RULES, account=20000, riskPct=1))["n"] == int(page.inner_text("#order").split()[1])
    page.reload()
    assert page.input_value("#r-account") == "20000" and page.input_value("#r-riskPct") == "1"
    open_rules()
    page.fill("#r-account", "-5"); page.fill("#r-riskPct", "")
    fill(his=25000, trade=284.81, stop=24950)
    assert "limit of ₹100 a trade" in " ".join(t for _, t in checks())                                # back to Rs 5,000 and 2%
    page.fill("#r-account", "5000"); page.fill("#r-riskPct", "2")
    ok("your rules are kept in the browser; an empty or negative rule goes back to its starting value")

    # ------------------------------------------------------------ gold and crude on MCX
    pick("market", "gold")
    assert page.is_visible("#contract") and page.is_visible("#marginLot")
    assert page.locator("#contract option").all_inner_texts() == ["Gold Petal (1 gram)", "Gold Guinea (8 grams)", "Gold Ten (10 grams)", "Gold Mini (100 grams)"]
    assert page.inner_text("#his-label") == "Gold now, on his chart" and page.inner_text("#trade-label") == "GOLDPETAL now"
    assert page.get_attribute("#his", "placeholder") == "4012.3"
    fill(his=4000, trade=14800, stop=3940, target=4120)              # a 1.5% stop: Rs 222 on one Petal
    assert page.inner_text("#order") == "No order: it doesn’t fit"
    assert any(c == "no" and "Even one lot loses" in t for c, t in checks()), checks()
    open_rules()
    page.fill("#r-riskPct", "6")
    want = expected({"market": "gold", "contract": "GOLDPETAL", "side": "long", "horizon": "day", "his": 4000, "trade": 14800, "stop": 3940, "target": 4120},
                    dict(RULES, riskPct=6))
    assert want["n"] == 1 and page.inner_text("#order") == "Buy 1 lot of GOLDPETAL, MCX future, for the day"
    st = stats()
    assert st["Stop"] == "₹14,578" and st["Target"] == "₹15,244" and st["Margin (a guess)"] == "₹1,480", st
    fill(marginLot=1250)
    assert stats()["Margin"] == "₹1,250"
    page.select_option("#contract", "GOLDM")
    assert page.inner_text("#trade-label") == "GOLDM now"
    fill(trade=148000)
    assert any(c == "no" and "Even one lot loses" in t for c, t in checks())                          # margin typed, stop too wide
    fill(marginLot=None)
    assert any(c == "no" and "Not enough money for one lot" in t and "a guess" in t for c, t in checks())
    pick("market", "crude")
    assert not page.is_visible("#contract") and page.inner_text("#trade-label") == "CRUDEOILM now"
    fill(his=85, trade=7565, stop=84, target=None, marginLot=None)
    assert any(c == "no" and "Not enough money for one lot" in t for c, t in checks())
    page.fill("#r-riskPct", "2")
    pick("market", "nifty")
    assert not page.is_visible("#contract") and not page.is_visible("#marginLot") and page.inner_text("#trade-label") == "NIFTYBEES now"
    ok("gold and crude move onto MCX contracts, with lots, margin and the 'doesn't fit' cases")

    # ------------------------------------------------------------ every box has a label; nothing spills sideways
    unlabelled = page.evaluate("""() => [...document.querySelectorAll('input[type=number], select')]
        .filter(el => !document.querySelector('label[for="' + el.id + '"]')).map(el => el.id)""")
    assert unlabelled == [], unlabelled
    assert page.evaluate("[...document.querySelectorAll('input[type=radio]')].every(el => el.closest('fieldset').querySelector('legend'))")
    for width in (320, 360, 390, 768, 1280):
        page.set_viewport_size({"width": width, "height": 800})
        over = page.evaluate("document.documentElement.scrollWidth - window.innerWidth")
        assert over <= 0, (width, over)
        small = page.evaluate("""() => [...document.querySelectorAll('button, .seg span, input[type=number], select')]
            .filter(el => el.offsetParent !== null && el.getBoundingClientRect().height < 44).length""")
        assert small == 0, (width, small)
    ok("every box is labelled, tap targets are at least 44px, and no width from 320px up scrolls sideways")
    real = [e for e in errors if "Failed to load resource" not in e]      # the web fonts can't be fetched in this sandbox
    assert real == [], real
    ok("no script errors in the browser")

    # screenshots for a look: phone, light and dark, with a call filled in
    page.set_viewport_size({"width": 390, "height": 844})
    page.evaluate(f"window.__now = '{MORNING}'")
    pick("side", "short"); fill(his=25000, trade=284.81, stop=25050, target=24900)
    page.screenshot(path=os.path.join(shots, "ticket-phone-light.png"), full_page=True)
    dark = browser.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=1, color_scheme="dark")
    dp = dark.new_page()
    dp.add_init_script(f"window.__now = '{MORNING}';")
    dp.goto(URL)
    dp.locator("input[name='market'][value='gold']").check(force=True)
    dp.fill("#his", "4000"); dp.fill("#trade", "14800"); dp.fill("#stop", "3940"); dp.fill("#target", "4120")
    dp.screenshot(path=os.path.join(shots, "ticket-phone-dark.png"), full_page=True)
    dark.close()

    # ------------------------------------------------------------ a browser that refuses to remember
    blocked = browser.new_context(viewport={"width": 390, "height": 844})
    bp = blocked.new_page()
    berr = []
    bp.on("pageerror", lambda exc: berr.append(str(exc)))
    bp.add_init_script("""Object.defineProperty(window, 'localStorage', { get() { throw new Error('blocked'); } });""")
    bp.goto(URL)
    bp.fill("#his", "25000"); bp.fill("#trade", "284.81")
    assert bp.inner_text("#order").startswith("Buy ") and not bp.is_visible("#memory")
    bp.click("#add-trade")
    assert bp.is_visible("#memory") and bp.inner_text("#tally") == "1 trade, 0 losses today" and berr == [], berr
    blocked.close()
    ok("with storage blocked the ticket still works and says it can't remember")
    browser.close()

shutil.rmtree(tmp)
print("ticket: all checks passed")
