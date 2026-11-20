"""Trade Like Berlin's record (berlin_calls.py) on made-up posts and prices: saving posts (edits and deletions
kept, never overwritten), his later posts moving a stop or target or ending a call without hindsight, the wait for
every post to be reviewed, crude oil levels moved onto futures, and claims checked against results.
    python tests/test_berlin_calls.py <repo copy> <scratch folder>    (or: python tests/run_tests.py berlin_calls)
"""
import os
import sys

import numpy as np
import pandas as pd

REPO, TMP = os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2])
sys.path.insert(0, REPO)
os.chdir(TMP)                       # anything written goes in the scratch folder
import berlin_calls as bc  # noqa: E402

checks = 0


def ok(cond, what):
    global checks
    checks += 1
    assert cond, what


# ------------------------------------------------------------------ 1. saving posts
def msg(pid, when, text, reply=None, edited=False, photo=False):
    r = (f'<a class="tgme_widget_message_reply user-color-default" href="https://t.me/tradelikeberlin/{reply}" ">'
         f'<div class="tgme_widget_message_text js-message_reply_text" dir="auto">quoted</div></a>') if reply else ""
    ph = '<a class="tgme_widget_message_photo_wrap 1 2" href="x"></a>' if photo else ""
    meta = ("edited  " if edited else "") + (f'<a class="tgme_widget_message_date" href="https://t.me/tradelikeberlin/{pid}">'
                                             f'<time datetime="{when}" class="time">08:01</time></a>')
    return (f'<div class="tgme_widget_message_wrap js-widget_message_wrap"><div class="tgme_widget_message text_not_supported_wrap '
            f'js-widget_message" data-post="tradelikeberlin/{pid}" data-view="x"><div class="tgme_widget_message_bubble">{r}{ph}'
            f'<div class="tgme_widget_message_text js-message_text" dir="auto">{text}</div><div class="tgme_widget_message_footer '
            f'compact js-message_footer"><div class="tgme_widget_message_info short js-message_info"><span class="tgme_widget_message_'
            f'views">25.6K</span><span class="copyonly"> views</span><span class="tgme_widget_message_meta">{meta}</span></div></div>'
            f'</div></div></div>')


page1 = "<html>" + "".join(msg(i, f"2026-10-29T0{i % 10}:00:00+00:00", f"post {i} &amp; <b>bold</b><br/>line2",
                                 reply=i - 1 if i % 3 == 0 else None, edited=(i == 77770), photo=(i == 77771))
                             for i in range(77760, 77773)) + "</html>"
page0 = "<html>" + "".join(msg(i, "2026-10-28T10:00:00+00:00", f"post {i}") for i in range(77650, 77760)) + "</html>"
p = bc.parse(page1)
ok(len(p) == 13 and p[0]["id"] == 77760 and p[0]["posted_at"] == "2026-10-29T00:00:00Z", f"a page of 13 posts: {p[:1]}")
ok(p[0]["text"] == "post 77760 & bold\nline2" and p[0]["reply_to"] == "77759", f"text unescaped, line breaks kept, reply noted: {p[0]}")
ok([x["id"] for x in p if x["edited"] == "yes"] == [77770] and [x["id"] for x in p if x["media"] == "yes"] == [77771], "edited and media flags")
asked = []
posts = os.path.join(TMP, "posts.csv")
n = bc.archive(fetch=lambda before=None: (asked.append(before), {None: page1, 77760: page0}.get(before, ""))[1], posts_path=posts)
ok(n == 117 and asked == [None, 77760], f"new posts from the start id on, reading older pages as needed: {n} {asked}")
page1b = page1.replace("post 77765 &amp;", "post 77765 CHANGED &amp;")
ok(bc.archive(fetch=lambda before=None: page1b if before is None else page0, posts_path=posts) == 1, "a changed post adds one row")
d = bc.read_posts(posts)
v = d[d["id"] == "77765"]
ok(list(v["text"]) == ["post 77765 & bold\nline2", "post 77765 CHANGED & bold\nline2"] and v.iloc[1]["edited"] == "changed after saving",
   "both versions are kept, the later one marked as changed")
ok(bc.archive(fetch=lambda before=None: page1b if before is None else page0, posts_path=posts) == 0, "nothing new, nothing added")

# deleted posts: noted once Telegram's own page for the post says so, never removed from the archive
pp, dp = os.path.join(TMP, "chan_posts.csv"), os.path.join(TMP, "chan_deleted.csv")


def page(ids):
    return "".join(f'<div class="tgme_widget_message_wrap"><div data-post="chan/{i}"><time datetime="2026-11-04T0{i % 10}:00:00+00:00">'
                   f'</time><div class="tgme_widget_message_text js-message_text">post {i}</div></div></div>' for i in ids)


ids = list(range(10, 31))
bc.archive(start_id=10, fetch=lambda before=None: page(ids), handle="chan", posts_path=pp, deleted_path=dp, gone=lambda i: True)
ok(not os.path.exists(dp), "first save: nothing deleted")
shown = [i for i in ids if i not in (15, 22)]
asked = []
bc.archive(start_id=10, fetch=lambda before=None: page(shown), handle="chan", posts_path=pp, deleted_path=dp,
           gone=lambda i: (asked.append(i), i == 22)[1])
ok(list(pd.read_csv(dp, dtype=str)["id"]) == ["22"] and sorted(asked) == [15, 22], "15 missing but still on its own page; 22 deleted")
bc.archive(start_id=10, fetch=lambda before=None: page(shown), handle="chan", posts_path=pp, deleted_path=dp, gone=lambda i: True)
ok(sorted(pd.read_csv(dp, dtype=str)["id"]) == ["15", "22"], "a later run adds 15 once its page says deleted; 22 not twice")
bc.archive(start_id=10, fetch=lambda before=None: page([i for i in shown if i > 20]), handle="chan", posts_path=pp,
           deleted_path=dp, gone=lambda i: True)
ok(len(pd.read_csv(dp)) == 2, "posts outside the range read are never marked")
ok(len(pd.read_csv(pp)) == 21, "the archive itself keeps deleted posts")

# ------------------------------------------------------------------ 2. his later posts, without hindsight
calls = pd.DataFrame(columns=["id", "posted_at", "entry"])
call = {"id": "1", "posted_at": "2026-11-02T10:00:00Z", "kind": "level", "instrument": "GOLD", "side": "short",
        "entry_type": "market", "entry": "", "stop": "4100", "target": "3900", "rr": "", "horizon": "positional",
        "event_at": "", "exit_at": "", "price_ref": "", "scorable": "yes", "note": "test"}
idx = pd.date_range("2026-11-02T10:00:00Z", periods=14 * 288 + 20, freq="5min", tz="UTC")
path = np.full(len(idx), 4000.0)    # 4000, a spike to 4060 on day 2 before any post, 4050 on day 3, then 3950
path[300:320] = 4060
path[700:900] = 4050
path[900:] = 3950
bars = pd.DataFrame({"Open": path, "High": path + 1, "Low": path - 1, "Close": path}, index=idx)
at = lambda i: idx[i].strftime("%Y-%m-%dT%H:%M:%SZ")  # noqa: E731


def up(action, when, price="", trigger=""):
    return {"id": "9", "call_id": "1", "posted_at": when, "action": action, "detail": "", "price": price,
            "trigger": trigger, "verdict": "", "note": "", "added_by": "claude"}


def one(updates=()):
    r = bc.score_level(call, bars, calls, list(updates))
    return (r[0]["outcome"], r[0]["exit"], r[0]["exit_at"]) if r else r


ok(one()[0] == "time", "no later posts: out when the window ends")
r = one([up("stop", at(400), "4047")])
ok(r[0] == "moved stop" and r[2] == at(700) and abs(r[1] - 4050) < 1e-6, f"a stop moved after the spike ignores it, and gaps through: {r}")
r = one([up("stop", at(200), "4047")])
ok(r[0] == "moved stop" and r[2] == at(300), f"the same stop moved before the spike is hit by it: {r}")
r = one([up("target", at(800), "3960")])
ok(r[0] == "target" and r[2] == at(900), f"a target moved to 3960 is reached when the price falls: {r}")
r = one([up("target", at(950), "3990")])
ok(r[0] == "target" and r[2] == at(950), f"a target moved after the fall counts only from its post: {r}")
ok(one([up("exit", at(800))])[0] == "his exit", "his exit post ends the call")
r = one([up("stop", at(400), "entry")])
ok(r[0] == "moved stop" and r[2] == at(400) and r[1] == 4000, f"a stop moved to cost: out at the entry price: {r}")

# ------------------------------------------------------------------ 3. a finished call waits until every post before its end is reviewed
c = pd.Series({"id": "100", "posted_at": "2026-11-02T04:00:00Z", "kind": "level", "instrument": "NIFTY", "side": "short",
               "entry_type": "market", "entry": "", "stop": "", "target": "", "rr": "", "horizon": "intraday", "event_at": "",
               "exit_at": "", "price_ref": "", "scorable": "yes", "note": ""})
posts_ = pd.DataFrame({"id": ["100", "101", "102", "103"],
                       "posted_at": ["2026-11-02T04:00:00Z", "2026-11-02T05:00:00Z", "2026-11-02T09:00:00Z", "2026-11-02T11:00:00Z"]})
ok(bc.waiting_for_review(c, [], posts_, None) == "", "no decision log yet: nothing waits")
log = pd.DataFrame({"id": ["100", "101"], "decision": ["call", "other"]})
ok("102" in bc.waiting_for_review(c, [], posts_, log), "post 102 (before the 3:30 pm close) not reviewed: waits")
log = pd.DataFrame({"id": ["100", "101", "102"], "decision": ["call", "other", "other"]})
ok(bc.waiting_for_review(c, [], posts_, log) == "", "every post up to the close reviewed (103 is after it): scored")
log2 = pd.concat([log, pd.DataFrame({"id": ["102"], "decision": ["needs levels"]})])
ok("needs levels" in bc.waiting_for_review(c, [], posts_, log2), "a 'needs levels' post inside the window: waits")
ok(bc.waiting_for_review(c, [], posts_, pd.concat([log2, pd.DataFrame({"id": ["102"], "decision": ["update"]})])) == "",
   "a later line settles it")
ok(bc.waiting_for_review(c, [{"action": "exit", "posted_at": "2026-11-02T04:30:00Z"}], posts_,
                         pd.DataFrame({"id": ["100"], "decision": ["call"]})) == "", "his exit at 10 am ends the call: later posts don't matter")

# ------------------------------------------------------------------ 4. crude oil: his CFD levels moved onto NYMEX futures
crude = pd.DataFrame([{"id": "77897", "posted_at": "2026-11-04T10:29:34Z", "kind": "level", "instrument": "CRUDE", "side": "short",
                       "entry_type": "market", "entry": "", "stop": "", "target": "", "rr": "", "horizon": "positional",
                       "event_at": "", "exit_at": "", "price_ref": "96.13@2026-11-04T10:38:42Z", "scorable": "yes", "note": ""}])
cidx = pd.date_range("2026-11-04T10:00Z", periods=14 * 288 + 50, freq="5min")
cp = np.full(len(cidx), 96.40)                       # futures = his CFD + 0.27
cp[30:] = 96.40 - np.linspace(0, 7.0, len(cidx) - 30).clip(max=6.5)
cbars = pd.DataFrame({"Open": cp, "High": cp + 0.05, "Low": cp - 0.05, "Close": cp}, index=cidx)
cbars.loc[cidx[7]:cidx[8], ["Open", "High", "Low", "Close"]] = 96.40
ups = [{"id": "77909", "call_id": "77897", "posted_at": "2026-11-04T12:09:19Z", "action": "stop", "price": "96.96", "trigger": ""},
       {"id": "77909", "call_id": "77897", "posted_at": "2026-11-04T12:09:19Z", "action": "target", "price": "90.028", "trigger": ""}]
gap = bc.level_gap(crude, "96.13@2026-11-04T10:38:42Z", cbars)
ok(abs(gap - 0.27) < 1e-9, f"the gap from his 96.13 quote: {gap}")
r = bc.score_level(crude.iloc[0], cbars, crude, ups)
ok(r and r[0]["outcome"] == "target" and abs(r[0]["exit"] - (90.028 + 0.27)) < 0.06, f"his target, moved onto futures: {r and r[0]}")
ok(bc.symbol("CRUDE") == "CL=F" and ("CRUDE", "positional") in bc.DEFAULT_STOP, "crude oil is scored on CL=F, with a default stop")

# ------------------------------------------------------------------ 5. claims checked against the results (a claim never changes a score)
res = pd.DataFrame([{"id": "1", "leg": "call", "outcome": "target"}, {"id": "2", "leg": "call", "outcome": "stop"},
                    {"id": "3", "leg": "underlying", "outcome": "his exit"}, {"id": "4", "leg": "call", "outcome": "time"}])
u = pd.DataFrame([{"id": "a", "call_id": "1", "action": "claim", "detail": "tp", "verdict": ""},
                  {"id": "b", "call_id": "2", "action": "claim", "detail": "tp", "verdict": ""},
                  {"id": "c", "call_id": "3", "action": "claim", "detail": "tp", "verdict": ""},
                  {"id": "d", "call_id": "4", "action": "claim", "detail": "sl", "verdict": ""},
                  {"id": "e", "call_id": "2", "action": "claim", "detail": "", "verdict": "matches"},
                  {"id": "f", "call_id": "9", "action": "claim", "detail": "sl", "verdict": ""}])
got = bc.checked_claims(u, res)
v = dict(zip(got["id"], got["verdict"]))
ok(v == {"a": "matches", "b": "doesn't match", "c": "", "d": "doesn't match", "e": "matches", "f": ""}, f"claim verdicts: {v}")

print(f"berlin calls: {checks} checks passed")
