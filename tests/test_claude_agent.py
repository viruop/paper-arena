"""claude_agent.py without the API: when a decision is due (holidays and the Muhurat session from the event
calendar), reading a reply, the limits on what is saved, the challenger's turn and what it reads, the reply format in
both agents' instructions, and that Claude's own snapshot never mentions the challenger.
    python tests/test_claude_agent.py <repo copy> <scratch folder>    (or: python tests/run_tests.py claude)
It works on its own copy of the repository, offline: the arena's prices come from the saved copies in data/market.
"""
import contextlib
import datetime as dt
import io
import os
import shutil
import sys

import pandas as pd

REPO, TMP = os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2])
repo = os.path.join(TMP, "repo")
shutil.copytree(REPO, repo, ignore=shutil.ignore_patterns("site", "__pycache__", ".git", "intraday", "fno", "akash", "berlin"))
os.chdir(repo)
sys.path.insert(0, repo)
import claude_agent as ca  # noqa: E402
import paper_arena as pa  # noqa: E402

checks = 0


def ok(cond, what):
    global checks
    checks += 1
    assert cond, what


IST = ca.IST
at = lambda *a: dt.datetime(*a, tzinfo=IST)  # noqa: E731

# ------------------------------------------------------------------ when a decision is due
fri, mon = pd.Timestamp("2026-11-06"), pd.Timestamp("2026-11-09")
ok(ca.status(fri, [], at(2026, 11, 7, 20, 0))[0], "Saturday evening: a decision for Friday's close is still due")
due, why = ca.status(fri, [], at(2026, 11, 8, 15, 0))
ok(not due and "already opened" in why, "Sunday 3 pm: the Muhurat session has opened, so it's too late for Friday's close")
ok(ca.status(mon, [], at(2026, 11, 10, 20, 0))[0], "Tuesday 10 Nov, an NSE holiday: a decision for Monday's close is still due")
ok(not ca.status(mon, [], at(2026, 11, 11, 9, 5))[0], "Wednesday 9:05 am: too late for Monday's close")
due, why = ca.status(mon, [{"date": "2026-11-09"}], at(2026, 11, 9, 20, 0))
ok(not due and "already decided" in why, "one decision per close")

# ------------------------------------------------------------------ reading a reply
ok(ca.parse_decision('{"position": 0.5, "summary": "s"}') == {"position": 0.5, "summary": "s"}, "a plain reply")
ok(ca.parse_decision('Here it is:\n```json\n{"position": 1, "summary": "a {braced} word"}\n```')["position"] == 1,
   "a reply wrapped in words and a code block, with braces inside a string")
ok(ca.parse_decision('{"position": 0, "summary": "first"} then {"position": 1, "summary": "second"}')["summary"] == "second",
   "the last object with a position wins")
ok(ca.parse_decision('{"note": "no position"}') is None and ca.parse_decision("no JSON at all") is None, "no position, no decision")

# ------------------------------------------------------------------ what is saved
latest, now = pd.Timestamp("2026-11-19"), at(2026, 11, 19, 21, 30)
rec = ca.make_record(latest, {"position": "1", "summary": "x" * 400, "reasons": ["r" * 400] + ["a", "", "b", "c", "d", "e"],
                              "go_to_cash_if": "c" * 300, "go_fully_in_if": "i"}, "M", now, 2)
ok(rec["date"] == "2026-11-19" and rec["position"] == 1.0 and rec["model"] == "M" and rec["searches"] == 2, f"the record: {rec}")
ok(len(rec["summary"]) == 300 and len(rec["reasons"]) == 5 and len(rec["reasons"][0]) == 300 and "" not in rec["reasons"],
   "summary and reasons are cut to 300 characters, at most five non-empty reasons")
ok(len(rec["go_to_cash_if"]) == 200 and rec["made_at"] == "2026-11-19T21:30+05:30", "conditions cut to 200; the time in India")
for bad, words in (({"position": 0.25, "summary": "s"}, "0, 0.5 or 1"), ({"position": "half", "summary": "s"}, "0, 0.5 or 1"),
                   ({"summary": "s"}, "0, 0.5 or 1"), ({"position": 0, "summary": "  "}, "summary is required")):
    try:
        ca.make_record(latest, bad, "M", now)
        refused = ""
    except ValueError as err:
        refused = str(err)
    ok(words in refused, f"refused: {bad} ({refused})")
first = {"date": "2026-11-19", "position": 1.0, "summary": "in", "reasons": ["trend"], "go_to_cash_if": "c", "go_fully_in_if": "i"}
ch = ca.make_challenger_record(latest, {"position": 0.5, "summary": "half", "against": ["a1", "a2", "a3", "a4"], "for": ["f1"],
                                        "decided_by": "a1"}, first, "M", now)
ok(ch["challenged"] == {"date": "2026-11-19", "position": 1.0} and ch["against"] == ["a1", "a2", "a3"] and ch["for"] == ["f1"],
   f"the challenger's record names the decision it tested, three points at most: {ch}")
for missing in ("against", "for", "decided_by"):
    d = {"position": 0.5, "summary": "half", "against": ["a"], "for": ["f"], "decided_by": "a"}
    d[missing] = [] if missing != "decided_by" else ""
    try:
        ca.make_challenger_record(latest, d, first, "M", now)
        refused = False
    except ValueError:
        refused = True
    ok(refused, f"the challenger must give {missing}")

# ------------------------------------------------------------------ the challenger's turn and what it reads
ok(not ca.challenger_status(latest, [], [], now)[0], "the challenger waits for Claude's decision")
ok(ca.challenger_status(latest, [first], [], now)[0], "then it's due")
ok(not ca.challenger_status(latest, [first], [{"date": "2026-11-19"}], now)[0], "once per close")
ok(not ca.challenger_status(latest, [first], [], at(2026, 11, 20, 9, 30))[0], "and not after the next open")
text = ca.challenger_text("data\nYour decisions so far (newest first):\n  old", [], first)
ok("Claude's decisions so far" in text and "Your decisions so far" not in text and "None yet." in text, "Claude's past decisions are named as Claude's")
ok("CLAUDE'S DECISION TONIGHT (2026-11-19): 100% in Nifty 50." in text and "Reason: trend" in text, "and tonight's decision is given in full")

# the reply format is part of both agents' instructions (a session's challenger once had to be given it by hand)
for rules, keys in ((ca.RULES, ("position", "summary", "reasons", "go_to_cash_if", "go_fully_in_if")),
                    (ca.CHALLENGER_RULES, ("position", "summary", "against", "for", "decided_by", "go_to_cash_if", "go_fully_in_if"))):
    full = rules.format(news=ca.NEWS_ON.format(n=ca.MAX_SEARCHES))
    reply = ca.parse_decision(full)
    ok(reply is not None and all(k in reply for k in keys), f"the reply format has every field: {reply}")
    ok("at most 3 searches" in full, "and the search limit")

# ------------------------------------------------------------------ offline: the saved prices, and what each agent is shown
pa._download_close = lambda name: (_ for _ in ()).throw(RuntimeError("offline in the test"))
ca.mc.context = lambda: {"breadth": None, "flows": None}
closes = pa.load_all()
res = pa.compute(closes)
log = ca.load_log()
snap = ca.snapshot(closes, res, log, None, as_of=now)
ok(pa.CHALLENGER not in snap and "challeng" not in snap.lower(), "Claude's snapshot never mentions the challenger")
ok("Buy & hold" in snap and "Cash only" in snap and "Your decisions so far" in snap, "but shows the rule agents and its own decisions")
out = io.StringIO()
with contextlib.redirect_stdout(out):
    ca.run_snapshot(now=now, agent="challenger")
printed = out.getvalue()
ok("DECISION NEEDED:" in printed and '"decided_by"' in printed and "The case against it" in printed,
   "the challenger's snapshot prints all its instructions, reply format included")
print(f"claude agent: {checks} checks passed")
