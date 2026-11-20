"""The scoreboards: when each agent's money went in, the confidence score (CONFIDENCE_LEVELS, 11 Nov 2026), what
goes on which page, and the built pages at phone and desktop width.
    python tests/test_board.py <repo copy> <scratch folder>    (or: python tests/run_tests.py board)
It builds the site in the repo copy first, downloading the day's prices as the nightly run does (about a minute),
so the page checks hold whatever the day's numbers are. Screenshots of the phone pages go in the scratch folder.
"""
import os
import re
import subprocess
import sys

import numpy as np
import pandas as pd

REPO, TMP = os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2])
sys.path.insert(0, REPO)
os.chdir(REPO)
build = subprocess.run([sys.executable, "build_site.py"], capture_output=True, text=True)
if build.returncode:
    sys.exit("build_site.py failed:\n" + (build.stdout + build.stderr)[-3000:])

import build_site as b  # noqa: E402
import logbook  # noqa: E402
import paper_arena as pa  # noqa: E402
import scorecard  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

CAP = pa.CAPITAL
checks = 0


def ok(cond, what):
    global checks
    checks += 1
    assert cond, what


# ------------------------------------------------------------------ started_values, nifty_over
days = pd.bdate_range("2026-01-01", periods=8)
vals = pd.DataFrame({
    "From day one": [CAP, 101000, 102000, 103000, 104000, 105000, 106000, 107000],
    "Moves on its first day": [CAP, CAP, CAP, 100023.126, 100046.2, 100069.3, 100092.5, 100115.7],
    "Buys at its first close": [CAP, CAP, CAP, CAP, 100500, 101000, 101500, 102000],
    "Not begun": [CAP] * 8,
}, index=days)
labels = {
    "From day one": pd.Series("NIFTY 50", index=days),
    "Moves on its first day": pd.Series(["Not started yet"] * 3 + ["Cash"] * 5, index=days),
    "Buys at its first close": {d: ("Not started yet" if i < 3 else "GOLDBEES") for i, d in enumerate(days)},
    "Not begun": pd.Series("Not started yet", index=days),
}
sv = b.started_values([{"values": vals, "labels": labels, "trades": [], "final": days[5]}])
ok(len(sv["From day one"]) == 8, "an agent with no flat days keeps every day")
ok(sv["Moves on its first day"].index[0] == days[2] and len(sv["Moves on its first day"]) == 6, "a first day with a move starts at the close before")
ok(sv["Buys at its first close"].index[0] == days[3] and len(sv["Buys at its first close"]) == 5, "a first day at the capital is the start")
ok(len(sv["Not begun"]) == 0 and b.started_values(None) == {}, "nothing begun, nothing counted")
nifty = sv["From day one"]
ok(abs(b.nifty_over(nifty, sv["Buys at its first close"]) - (107000 / 103000 - 1)) < 1e-12, "Nifty from the close the money went in")
ok(b.nifty_over(nifty.iloc[:-1], sv["Buys at its first close"]) is None and b.nifty_over(None, nifty) is None, "no comparison when Nifty stops short")
ok(scorecard.agent_luck(sv["Moves on its first day"], pa.CASH_DAILY)["days"] == 5, "days are counted from the agent's own start")

# ------------------------------------------------------------------ confidence: the levels set on 11 Nov 2026
rng = np.random.default_rng(7)


def curve(n, daily, noise=0.0):
    r = daily + noise * rng.standard_normal(n)
    return pd.Series(CAP * np.concatenate([[1.0], np.cumprod(1 + r)]), index=pd.bdate_range("2025-01-01", periods=n + 1))


cash = pa.CASH_DAILY
ok(b.confidence(curve(10, 0.01, 0.01)) == (0, "10 of 60 days"), "10 days is level 0")
ok(b.confidence(curve(19, 0.02, 0.001))[0] == 0 and b.confidence(curve(20, 0.02, 0.001))[0] == 1, "level 1 begins at 20 days")
ok(b.confidence(curve(59, 0.02, 0.001)) == (1, "59 of 60 days") and b.confidence(curve(60, 0.02, 0.001))[0] == 3, "the test begins at 60 days")
ok(b.confidence(curve(200, cash, 0.01))[0] == 2 and b.confidence(curve(200, cash - 0.002, 0.001))[0] == 2, "no edge, or behind cash, is level 2")
good = curve(300, 0.002, 0.004)
flat = pd.Series(CAP, index=good.index)
ok(b.confidence(good.iloc[:250])[0] == 3 and b.confidence(good.iloc[:251])[0] == 4, "level 4 needs 250 days")
ok(b.confidence(good, flat)[0] == 5 and b.confidence(good, good * 1.0)[0] == 4 and b.confidence(good, flat.iloc[:-1])[0] == 4, "level 5 needs to be ahead of Nifty")
tiny = pd.Series(CAP * np.cumprod(np.concatenate([[1.0], 1 + cash + np.where(np.arange(120) % 7 == 0, 0.0, 3e-13)])),
                 index=pd.bdate_range("2025-01-01", periods=121))
lk = scorecard.agent_luck(tiny, cash)
ok(lk["enough"] and lk["excess"] > 0 and lk["p"] < 0.05 and not b.beats_luck(lk) and b.confidence(tiny)[0] == 2, "rounding alone never passes")

# ------------------------------------------------------------------ the built pages


def board(path):
    html_ = open(path, encoding="utf-8").read()
    sec = re.search(r"<section class='scoreboard'.*?</section>", html_, re.S)
    rows = {}
    if sec:
        for m in re.finditer(r"<tbody class='row'><tr class='main'><td class='name'>(.*?)</td><td class='r num-big'>(.*?)</td>"
                             r"<td class='r'>(.*?)</td></tr><tr class='more'><td colspan='3'><div><span class='sub'>(.*?)</span>"
                             r"<span class='sub'>(.*?)</span></div></td></tr></tbody>", sec.group(0), re.S):
            rows[b.html.unescape(m.group(1))] = (m.group(2), re.sub(r"<[^>]+>", "", m.group(3)), b.html.unescape(m.group(4)),
                                                 b.html.unescape(re.sub(r"<[^>]+>", "", m.group(5))))
    return html_, (sec.group(0) if sec else ""), rows


pages = [f for f in sorted(os.listdir("site")) if f.endswith(".html")]
ok({"index.html", "berlin.html", "ticket.html"} <= set(pages) and len(pages) >= 4, f"every page is built: {pages}")
home_html, home_sec, home = board("site/index.html")
berlin_html, berlin_sec, berlin = board("site/berlin.html")
ok("<script" not in home_sec and "<form" not in home_sec and "<input" not in home_sec, "the home board is a plain table")
ok(home_html.count("<section class='scoreboard'") == 1, "one board on the home page")
for gone in ("His Telegram calls", "His signals", "Forex news-event plan", "3-day rule", "Gold breakdown short", "Small-capital series"):
    ok(gone not in home and gone not in home_sec, f"{gone} is not on the home board")
for kept in ("Buy & hold", "Cash only", "Claude", "Nifty-gold switch", "Weekly option buying"):
    ok(kept in home, f"{kept} is on the home board")
for here in ("3-day rule", "Gold breakdown short", "His Telegram calls", "Forex news-event plan"):
    ok(here in berlin, f"{here} is on the Berlin board")
groups = [re.sub(r" <span class='tag'>.*?</span>", "", t) for t in re.findall(r"<tr class='grp'><td colspan='3'>(.*?)</td>", home_sec)]
ok(groups[:3] == ["Nifty 50 agents and Claude", "Gold and multi-asset", "F&amp;O (3x leverage)"], f"the home board's groups: {groups}")
for f in pages:
    if f not in ("index.html", "berlin.html", "ticket.html"):
        _, _, rows = board(f"site/{f}")
        ok(list(rows) == ["His signals"], f"{f} has its own board with one row")

# the numbers are the arena's own, and the score and Nifty line are right for each agent's values
res, fres, ares = pa.compute(), logbook.fno_results(), logbook.asset_results()
view = logbook.merged(res, fres, ares)
began = b.started_values(view)
want = {}
for r in (res, fres, ares):
    for name, value, since, note in b.board_rows(r):
        want[name] = (value, since, note)
running = 0
for name, (val, chg, note, more) in home.items():
    value, since, note_ = want[name]
    ok(val == (b.inr(value) if value is not None else "–") and chg == (b.pct(since, True, 2) if since is not None else ""),
       f"{name}: value and change are the arena's own ({val} {chg})")
    ok(note == note_, f"{name}: its note is the arena's own")
    if value is None or not len(began.get(name, ())):
        ok(more == "", f"{name}: no score before it begins")
        continue
    running += 1
    score, why = b.confidence(began[name], began.get(b.NIFTY_HOLD))
    over = b.nifty_over(began.get(b.NIFTY_HOLD), began[name]) if name != b.NIFTY_HOLD else None
    cut = min([i for i in (more.find("Worst fall"), more.find("No fall yet")) if i >= 0], default=len(more))
    more, stats = more[:cut], more[cut:]
    v = began[name]
    fall = float((v / v.cummax() - 1).min())
    n = sum(1 for blk in view for t in blk["trades"] if t["agent"] == name)
    ok(stats == ((f"Worst fall {b.pct(fall)}" if fall < -1e-9 else "No fall yet") + f" · {n} trade{'' if n == 1 else 's'}"),
       f"{name}: worst fall and trades {stats!r}")
    ok(more == f"Confidence {score} of 5: {why}" + (f" · Nifty {b.pct(over, True, 2)}" if over is not None else ""), f"{name}: score line {more!r}")
ok(running > 10 and len(home) == len(want) - 2, "every agent is on the home board except Berlin's two")
ok("Confidence" not in berlin["His Telegram calls"][3] and "Worth following?" in berlin["His Telegram calls"][3], "his calls carry their checks, not a score")
ok(berlin["3-day rule"][3].startswith("Confidence ") and berlin["Gold breakdown short"][3].startswith("Confidence "), "his two strategies carry a score")
ok("What the confidence score means" in home_sec and "over the same days" in home_sec, "the board says what the score and the Nifty figure mean")

errors = []
with sync_playwright() as pw:
    browser = pw.chromium.launch()
    for width, tag in ((390, "phone"), (1100, "wide")):
        page = browser.new_page(viewport={"width": width, "height": 844})
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" and "Failed to load resource" not in m.text else None)
        for f in pages:
            page.goto(f"file://{REPO}/site/{f}")
            ok(page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth"), f"{tag}: {f} doesn't scroll sideways")
            if tag == "phone" and f in ("index.html", "berlin.html"):
                page.screenshot(path=os.path.join(TMP, f"board-{f[:-5]}-phone.png"))
        page.close()
    browser.close()
ok(not errors, f"no script errors on any page: {errors[:3]}")
print(f"board: {checks} checks passed")
