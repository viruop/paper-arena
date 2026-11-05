"""
signal_calls.py - Telegram channels that post structured trade signals, read and paper traded
automatically (see channels.py for which channels; the first is Trade with Akash Garg).

Such channels post signals like

    GOLD BUY NOW / STOPS :- 3990.6          (and a minute later)   TARGET :- 3997.209
    BTC SELL LIMIT :- 77985.79 / STOPS :- 78123.40 / Target 1 :- 77850 / Target 2 :- 77711.46

and follow them with "SL HIT", "TP done", "Target 1 is done", "move to breakeven", "Closing full".
Because the format is regular, plain code reads them; no AI and no uploads are needed:

  1. parse_new() runs after every 30-minute save (channels.save_all). Each new post gets one line in
     the channel's decision log (telegram_reviewed.csv): a signal, part of a signal, an update or
     claim about one, needs review, or other. Signals go to telegram_calls.csv, his later
     instructions and claims to telegram_updates.csv. Posts are only read once they are 10 minutes
     old, so a signal split over two posts is read whole. All three files are only ever added to.
     A signal missing its stop or target, an update that can't be tied to one signal, or a voice
     note (its English transcript is in voice_notes.csv) is marked "needs review" and never guessed. Claude answers those each night (berlin-telegram-calls skill)
     in claude_calls.csv, claude_updates.csv and claude_reviewed.csv, which the user uploads; the
     code reads them together with its own files, and a later line in claude_reviewed.csv settles
     a post. The 30-minute job never writes the claude_ files, so an upload can't overwrite its rows.
  2. score_all() runs each night (berlin_calls.main -> channels.score_all_channels) and paper trades
     every signal whose 24-hour window has ended, on one-minute bid and ask prices from Dukascopy
     (dukascopy.py): market orders fill at the next minute's open (the ask for a buy, the bid for a
     sell), limit and stop orders when the price reaches his level. Each signal risks Rs 1,000,
     split equally over his targets; a buy is stopped out by the bid and takes profit at the bid.
     If a minute touches both the stop and a target, the stop counts. His later instructions apply
     from the minute after he posts them: a breakeven move puts the stop at the entry, an exit
     closes what is left. Results go to logs/<channel>_calls.csv; each signal is also checked 15
     and 30 minutes late and reversed (logs/<channel>_variants.csv). Results are never rewritten.

His claims ("TP done", "SL HIT") are compared with the record, which is the point: a channel's own
results posts are not the record.

FOR LEARNING ONLY. Paper trading; no real orders. Offshore forex and CFD trading isn't legal for
Indian residents, so these signals are only ever paper traded here.
"""

import os
import re
import sys

import numpy as np
import pandas as pd

import berlin_calls as bc
import dukascopy

WINDOW = pd.Timedelta(hours=24)
SETTLE = pd.Timedelta(minutes=10)       # a post is read once it is this old, so split signals are whole
GROUP = pd.Timedelta(minutes=3)         # stop and targets posted within this time belong to the signal
LINK = pd.Timedelta(hours=24)           # updates are tied to a signal at most this long after it
REVIEW_COLS = ["id", "posted_at", "reviewed_at", "decision", "call_id", "note"]
CALL_COLS = ["id", "posted_at", "kind", "instrument", "side", "entry_type", "entry", "stop", "target", "rr", "horizon",
             "event_at", "exit_at", "price_ref", "scorable", "note"]
NUMBER = r"(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)"

ALIASES = [
    (r"\b(?:gold|xau\s*/?\s*usd)\b", "XAUUSD"),
    (r"\b(?:silver|xag\s*/?\s*usd)\b", "XAGUSD"),
    (r"\b(?:nas\s*-?\s*100|nasdaq(?:\s*100)?|us\s*100|ustec)\b", "NAS100"),
    (r"\b(?:us\s*30|dow\s*jones|dj\s*30)\b", "US30"),
    (r"\b(?:us\s*500|spx\s*500|s&p\s*500)\b", "SPX500"),
    (r"\b(?:btc\s*/?\s*usdt?|btc|bitcoin)\b", "BTCUSD"),
    (r"\b(?:eth\s*/?\s*usdt?|eth|ethereum)\b", "ETHUSD"),
    (r"\b(?:us\s*oil|usoil|wti)\b", "USOIL"),
]
FX = "eur|gbp|aud|nzd|usd|cad|chf|jpy"


def paths(ch):
    folder = ch["folder"]
    return {"posts": os.path.join(folder, "telegram_posts.csv"), "calls": os.path.join(folder, "telegram_calls.csv"),
            "updates": os.path.join(folder, "telegram_updates.csv"),
            "reviewed": os.path.join(folder, "telegram_reviewed.csv"),
            # Claude's answers to posts marked "needs review", uploaded by the user. The 30-minute job never
            # writes these, so an upload can't overwrite rows the job added in the meantime.
            "claude_calls": os.path.join(folder, "claude_calls.csv"),
            "claude_updates": os.path.join(folder, "claude_updates.csv"),
            "claude_reviewed": os.path.join(folder, "claude_reviewed.csv"),
            "corrections": os.path.join(folder, "call_corrections.csv"),     # Claude's notes on misread signals
            "deleted": os.path.join(folder, "telegram_deleted.csv"),         # saved posts he deleted later
            "results": ch["results"], "variants": ch["results"].replace("_calls.csv", "_variants.csv")}


def read(path, cols):
    if not os.path.exists(path):
        return pd.DataFrame(columns=cols)
    return pd.read_csv(path, dtype=str, keep_default_na=False)


def read_both(p, name, cols):
    """The code's rows and Claude's rows for one kind of file (calls, updates or reviewed), code's first."""
    parts = [read(p[name], cols), read(p["claude_" + name], cols)]
    parts = [x for x in parts if len(x)]
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(columns=cols)


def numbers(text):
    return [float(n.replace(",", "")) for n in re.findall(NUMBER, text)]


def exact(x):
    """A price written back exactly as he wrote it (no rounding): 77711.46 stays 77711.46."""
    return ("%.10f" % x).rstrip("0").rstrip(".")


# ------------------------------------ reading posts ------------------------------------
def instrument_of(text):
    t = text.lower()
    for pattern, name in ALIASES:
        if re.search(pattern, t):
            return name
    m = re.search(rf"\b({FX})\s*/?\s*({FX})\b", t)
    if m and m.group(1) != m.group(2):
        return (m.group(1) + m.group(2)).upper()
    return None


def order_of(text):
    """(side, entry type, limit or stop price) if the post opens a trade, else None."""
    t = text.lower()
    m = re.search(rf"\b(buy|sell)\s*(limit|stop)(?!\s*s\b|s\b|\s*loss)\s*(?:at|@|:-|:|-|=)?\s*{NUMBER}?", t)
    if m:
        price = float(m.group(3).replace(",", "")) if m.group(3) else None
        return m.group(1).replace("buy", "long").replace("sell", "short"), m.group(2), price
    m = re.search(r"\b(buy|sell)\b[^\n]{0,30}?\b(now|cmp)\b|\b(now)\s+(buy|sell)\b", t)
    if m and not re.search(r"\b(?:don'?t|dont|do\s+not|avoid|never|mat)\b[^\n]{0,20}\b(?:buy|sell)", t):
        side = m.group(1) or m.group(4)
        return ("long" if side == "buy" else "short"), "market", None
    return None


def stop_of(text):
    m = re.search(rf"\b(?:stops?|sl|stop\s*loss)\b\s*(?:is|at|@|:-|:|-|=)?\s*{NUMBER}", text.lower())
    return float(m.group(1).replace(",", "")) if m else None


def targets_of(text):
    out = []
    for m in re.finditer(rf"\b(?:targets?|tp)\s*(\d)?\s*(?:is|at|@|:-|:|-|=)\s*{NUMBER}|\b(?:targets?|tp)\s*(\d)?\s+{NUMBER}",
                         text.lower()):
        value = m.group(2) or m.group(4)
        if value:
            out.append(float(value.replace(",", "")))
    return out


def claim_of(text):
    """His update or claim in one post: (action, detail, trigger) or None."""
    t = text.lower()
    if re.search(r"\b(?:sl|stop\s*loss)\s*(?:hit|hogaya|ho\s*gaya|triggered)\b", t):
        return "claim", "sl", None
    if re.search(r"\b(?:be|break\s*even|breakeven)\s*(?:hit|hogaya|ho\s*gaya)\b", t):
        return "claim", "be", None
    m = re.search(r"\b(?:tp|target)\s*(\d)\s*(?:is\s*)?(?:done|hit|achieved|complete)", t)
    if m:
        return "claim", f"tp{m.group(1)}", None
    if re.search(r"\b(?:tp|target)\s*(?:is\s*)?(?:done|hit|achieved)|\b(?:complete|full)\s*(?:tp|target)", t):
        return "claim", "tp", None
    if re.search(r"\b(?:go|move|shift|set)\s+(?:sl\s+|stops?\s+)?(?:to\s+)?(?:break\s*even|breakeven|be|entry|cost)\b|"
                 r"\b(?:break\s*even|breakeven|be)\s+(?:kar|kr)\w*", t):
        m = re.search(rf"(?:jab|when|at|after)\s*(?:price\s*)?{NUMBER}", t)
        return ("stop_when", "breakeven", float(m.group(1).replace(",", ""))) if m else ("stop", "breakeven", None)
    if re.search(r"\b(?:closing|close|closed)\s+(?:my|the|this|our|full|all|now|trade|position|half|partial|day)|"
                 r"\bexit(?:ed|ing)?\b|\bbook(?:ing)?\s+(?:profit|full|all)|\bbooked\s+and\s+closed", t):
        return "exit", "", None
    if re.search(r"\bactivated\b|\btriggered\b", t):
        return "claim", "activated", None
    if re.search(r"\bbooked\b|\b\d+\s*(?:k|thousand|lakh|lacs?)\b|\brunning\b", t) and not re.search(r"\bsend\b", t):
        return "claim", "profit", None
    return None


def parse_new(ch, now=None):
    """Read the channel's new posts into signals, updates and the decision log. Returns counts."""
    p = paths(ch)
    now = now or pd.Timestamp.now(tz="UTC")
    posts = read(p["posts"], bc.POST_COLS).drop_duplicates("id", keep="first")   # as first saved
    reviewed = read_both(p, "reviewed", REVIEW_COLS)
    calls, updates = read_both(p, "calls", CALL_COLS), read_both(p, "updates", bc.UPDATE_COLS)
    done = set(reviewed["id"].astype(str))
    posts = posts.assign(n=posts["id"].astype(int), t=pd.to_datetime(posts["posted_at"], utc=True)).sort_values("n")
    todo = posts[(~posts["id"].isin(done)) & (posts["n"] >= int(ch["start_id"])) & (posts["t"] <= now - SETTLE)]
    stamp = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    new_calls, new_updates, decisions, used = [], [], [], set()
    part_of = {}                                            # post id -> signal id (signal and its parts)
    for _, c in calls.iterrows():
        part_of[str(c["id"])] = str(c["id"])
    for _, r in reviewed[reviewed["call_id"] != ""].iterrows():
        part_of[str(r["id"])] = str(r["call_id"])
    closed = set(updates.loc[(updates["action"] == "exit") | updates["detail"].isin(["sl", "tp", "be"]), "call_id"].astype(str))
    signal_times = {str(c["id"]): pd.Timestamp(c["posted_at"]) for _, c in calls.iterrows()}
    instruments = {str(c["id"]): c["instrument"] for _, c in calls.iterrows()}

    def decide(post, decision, call_id="", note=""):
        decisions.append({"id": post["id"], "posted_at": post["posted_at"], "reviewed_at": stamp,
                          "decision": decision, "call_id": call_id, "note": note[:200]})
        used.add(post["id"])

    for _, post in todo.iterrows():
        if post["id"] in used:
            continue
        text = post["text"]
        if post["media"] == "voice":            # spoken: code can't read it, so Claude reads its transcript
            decide(post, "needs review", "", "Voice note: read its transcript in voice_notes.csv"
                   + (f". Caption: {text[:150]}" if text else ""))
            continue
        order = order_of(text)
        if order and not re.search(r"\b(?:will|plan|wait|agar|jab\s+tak|look\s+for|ban\s+sakt)", text.lower()):
            side, kind, level = order
            group = posts[(posts["t"] >= post["t"]) & (posts["t"] <= post["t"] + GROUP) & (posts["n"] > post["n"])
                          & (~posts["id"].isin(done)) & (~posts["id"].isin(used))]
            parts = [post] + [g for _, g in group.iterrows() if not order_of(g["text"]) and g["media"] != "voice"
                              and (g["reply_to"] in ("", post["id"]))]
            instrument = instrument_of(text) or next((instrument_of(g["text"]) for g in parts[1:] if instrument_of(g["text"])), None)
            stop = next((stop_of(g["text"]) for g in parts if stop_of(g["text"]) is not None), None)
            targets = [x for g in parts for x in targets_of(g["text"])]
            ok = instrument and stop is not None and targets and (kind == "market" or level is not None)
            if ok:
                ref = level if level is not None else np.median(targets)
                sign = 1 if side == "long" else -1
                ok = (all(abs(x / ref - 1) < 0.05 for x in [stop] + targets)
                      and all((x - stop) * sign > 0 for x in targets)
                      and (level is None or ((level - stop) * sign > 0 and all((x - level) * sign > 0 for x in targets))))
            ids = [g["id"] for g in parts]
            quote = " / ".join(g["text"].replace("\n", " / ") for g in parts if g["text"])[:220]
            if not ok:
                decide(post, "needs review", "", f"Trade post without a readable instrument, stop and target: {quote}")
                continue
            sid = post["id"]
            new_calls.append({"id": sid, "posted_at": post["posted_at"], "kind": "signal", "instrument": instrument,
                              "side": side, "entry_type": kind, "entry": "" if level is None else exact(level),
                              "stop": exact(stop), "target": "|".join(exact(x) for x in targets), "rr": "", "horizon": "scalp",
                              "event_at": "", "exit_at": "", "price_ref": "",
                              "scorable": "yes" if dukascopy.supported(instrument) else "no",
                              "note": f"Posts {'+'.join(ids)}: \"{quote}\" (read automatically)"})
            signal_times[sid], instruments[sid] = post["t"], instrument
            for g in parts:
                part_of[g["id"]] = sid
                decide(g, "signal" if g["id"] == sid else "part of signal", sid)
            continue
        claim = claim_of(text)
        if not claim:
            decide(post, "other")
            continue
        action, detail, trigger = claim
        named = instrument_of(text)
        def fits(s, within):
            return (signal_times[s] <= post["t"] <= signal_times[s] + within
                    and (named is None or instruments.get(s) == named))
        target_sid = part_of.get(post["reply_to"]) if post["reply_to"] else None
        if target_sid is not None and not (target_sid in signal_times and fits(target_sid, LINK)):
            target_sid = None
        if target_sid is None:
            open_ = [s for s in signal_times if fits(s, LINK) and s not in closed]
            recent = [s for s in signal_times if fits(s, pd.Timedelta(hours=2))]
            if len(open_) == 1:
                target_sid = open_[0]
            elif not open_ and action == "claim" and len(recent) == 1:
                target_sid = recent[0]              # a result claim about the signal that just closed
        if target_sid is None:
            result = action == "claim" and (detail in ("sl", "tp", "be") or detail.startswith("tp"))
            decide(post, "needs review" if action != "claim" else "claim without signal" if result else "other", "",
                   f"Not tied to one signal posted here: {text[:150]}")
            continue
        new_updates.append({"id": post["id"], "call_id": target_sid, "posted_at": post["posted_at"], "action": action,
                            "detail": detail, "price": "entry" if action in ("stop", "stop_when") else "",
                            "trigger": "" if trigger is None else trigger, "verdict": "",
                            "note": f"\"{text[:180]}\"", "added_by": "parser"})
        part_of[post["id"]] = target_sid
        if action == "exit" or detail in ("sl", "tp", "be"):
            closed.add(target_sid)
        decide(post, "claim" if action == "claim" else "update", target_sid)
    bc.append(p["calls"], CALL_COLS, new_calls)
    bc.append(p["updates"], bc.UPDATE_COLS, new_updates)
    bc.append(p["reviewed"], REVIEW_COLS, decisions)
    return {"signals": len(new_calls), "updates": len(new_updates), "reviewed": len(decisions)}


# ------------------------------------ paper trading ------------------------------------
def score_signal(call, bars, updates=(), start=None, flip=False, target_levels=None, ended=False):
    """One signal on one-minute bid/ask bars: result rows (one per target), [] if never filled, None if
    its window hasn't ended in the prices given. ended=True: the caller knows the window is over by the
    clock, so prices that stop early mean the market closed (a weekend), and the trade is closed at the
    last price inside its window."""
    posted = bc.utc(call["posted_at"])
    end, his_exit = posted + WINDOW, False
    exits = [bc.utc(u["posted_at"]) for u in updates if u["action"] == "exit" and bc.utc(u["posted_at"]) > posted]
    if exits and min(exits) < end:
        end, his_exit = min(exits), True
    if bars.empty or (not ended and bars.index[-1] < end - pd.Timedelta(minutes=2)):
        return None
    side = call["side"]
    sign = 1 if side == "long" else -1
    begin = posted if start is None else max(posted, start)
    after = bars[(bars.index >= begin) & (bars.index < end)]
    if after.empty:
        return []
    buy = (lambda c: f"ask_{c}") if sign > 0 else (lambda c: f"bid_{c}")    # the side we trade at
    level = bc.num(call["entry"])
    if call["entry_type"] == "limit":
        hit = after[after[buy("l")] <= level] if sign > 0 else after[after[buy("h")] >= level]
    elif call["entry_type"] == "stop":
        hit = after[after[buy("h")] >= level] if sign > 0 else after[after[buy("l")] <= level]
    else:
        hit = after
    if hit.empty:
        return []
    fill_at, o = hit.index[0], hit[buy("o")].iloc[0]
    if call["entry_type"] == "limit":
        fill = min(o, level) if sign > 0 else max(o, level)
    elif call["entry_type"] == "stop":
        fill = max(o, level) if sign > 0 else min(o, level)
    else:
        fill = o
    stop = bc.num(call["stop"])
    targets = target_levels if target_levels is not None else [float(x) for x in str(call["target"]).split("|") if x]
    if (stop - fill) * sign >= 0 or any((t - fill) * sign <= 0 for t in targets):
        return []                                           # past his stop or a target already: no trade
    moves = []
    if flip:
        side, sign = ("short" if side == "long" else "long"), -sign
        stop, targets = 2 * fill - stop, [2 * fill - t for t in targets]
    else:
        for u in updates:
            if u["action"] in ("stop", "stop_when") and bc.utc(u["posted_at"]) > posted:
                trigger = bc.num(u["trigger"]) if u["action"] == "stop_when" else None
                moves.append((bc.utc(u["posted_at"]), fill, trigger))
    exit_side = (lambda c: f"bid_{c}") if sign > 0 else (lambda c: f"ask_{c}")   # where we get out
    risk = abs(fill - stop)
    open_legs = list(range(len(targets)))
    exits_ = {}
    pending, armed, moved = sorted(moves, key=lambda m: m[0]), [], False
    path = bars[(bars.index >= fill_at) & (bars.index < end)]
    for t, b in path.iterrows():
        while pending and pending[0][0] <= t:
            _, new, trigger = pending.pop(0)
            if trigger is None:
                stop, moved = new, True
            else:
                armed.append((new, trigger))
        lo, hi, op = b[exit_side("l")], b[exit_side("h")], b[exit_side("o")]
        if (lo <= stop) if sign > 0 else (hi >= stop):
            gap = (op < stop) if sign > 0 else (op > stop)
            for i in open_legs:
                exits_[i] = (t, op if gap else stop, "moved stop" if moved else "stop")
            open_legs = []
            break
        for i in list(open_legs):
            if (hi >= targets[i]) if sign > 0 else (lo <= targets[i]):
                gap = (op > targets[i]) if sign > 0 else (op < targets[i])
                exits_[i] = (t, op if gap else targets[i], f"target {i + 1}" if len(targets) > 1 else "target")
                open_legs.remove(i)
        if not open_legs:
            break
        for new, trigger in list(armed):
            if (hi >= trigger) if sign > 0 else (lo <= trigger):
                stop, moved = new, True
                armed.remove((new, trigger))
    if open_legs:
        if path.empty:
            return []
        last_t, last = path.index[-1] + pd.Timedelta(minutes=1), path[exit_side("c")].iloc[-1]
        for i in open_legs:
            exits_[i] = (last_t, last, "his exit" if his_exit else "time")
    rows, share = [], bc.RISK_RS / len(targets)
    for i in range(len(targets)):
        t, price, outcome = exits_[i]
        r = sign * (price - fill) / risk
        rows.append({"id": call["id"], "posted_at": call["posted_at"], "kind": call["kind"],
                     "instrument": call["instrument"], "leg": f"target {i + 1}" if len(targets) > 1 else "call",
                     "side": side, "fill_at": fill_at.strftime("%Y-%m-%dT%H:%M:%SZ"), "fill": round(fill, 5),
                     "stop": round(bc.num(call["stop"]) if not flip else 2 * fill - bc.num(call["stop"]), 5),
                     "target": round(targets[i], 5), "exit_at": t.strftime("%Y-%m-%dT%H:%M:%SZ"),
                     "exit": round(price, 5), "outcome": outcome, "r": round(r, 3), "risk_rs": round(share, 2),
                     "pnl_rs": round(r * share, 2), "scored_at": pd.Timestamp.now(tz="UTC").strftime("%Y-%m-%dT%H:%M:%SZ")})
    return rows


def variants(call, bars, updates=(), ended=False):
    """The signal 15 and 30 minutes late (aiming at his targets) and reversed; one total per check."""
    base = score_signal(call, bars, updates, ended=ended)
    if base is None:
        return None
    if not base:
        return []
    posted, now = bc.utc(call["posted_at"]), pd.Timestamp.now(tz="UTC").strftime("%Y-%m-%dT%H:%M:%SZ")
    aims = [float(x) for x in str(call["target"]).split("|") if x]
    out = []
    checks = [(f"late{m}", {"start": posted + pd.Timedelta(minutes=m), "target_levels": aims}) for m in bc.LATE_MIN]
    for name, kwargs in checks + [("flip", {"flip": True})]:
        rows = score_signal(call, bars, updates, ended=ended, **kwargs)
        if rows is None:
            return None
        pnl = sum(r["pnl_rs"] for r in rows)
        out.append({"id": call["id"], "variant": name, "fill_at": rows[0]["fill_at"] if rows else "",
                    "fill": rows[0]["fill"] if rows else "", "exit_at": max(r["exit_at"] for r in rows) if rows else "",
                    "exit": "", "outcome": ", ".join(r["outcome"] for r in rows) if rows else "not filled",
                    "r": round(pnl / bc.RISK_RS, 3), "pnl_rs": round(pnl, 2), "scored_at": now})
    return out


def waiting_for_review(call, updates, reviewed):
    """A post inside the signal's 24 hours still marked "needs review" (it may be his exit or a stop move,
    and a score is never redone): the signal waits for Claude's answer. Returns the post id or ""."""
    if not len(reviewed):
        return ""
    posted = bc.utc(call["posted_at"])
    end = min([posted + WINDOW] + [bc.utc(u["posted_at"]) for u in updates
                                    if u["action"] == "exit" and bc.utc(u["posted_at"]) > posted])
    latest = reviewed.drop_duplicates("id", keep="last")
    t = pd.to_datetime(latest["posted_at"], utc=True, errors="coerce")
    open_ = latest[(latest["decision"] == "needs review") & (t > posted) & (t <= end)]
    return str(open_["id"].iloc[0]) if len(open_) else ""


def score_all(ch, bars_for=None, now=None):
    """Score every signal whose window has ended, and its checks. bars_for(instrument, start, end)."""
    p = paths(ch)
    now = now or pd.Timestamp.now(tz="UTC")
    bars_for = bars_for or dukascopy.minute_bars
    calls, results = read_both(p, "calls", CALL_COLS), read(p["results"], bc.RESULT_COLS)
    updates, reviewed = read_both(p, "updates", bc.UPDATE_COLS), read_both(p, "reviewed", REVIEW_COLS)
    have = set(read(p["variants"], bc.VARIANT_COLS)["id"].astype(str))
    done = set(results["id"].astype(str))
    rows, never, checks = [], [], []
    for _, call in calls.iterrows():
        cid = str(call["id"])
        if call["scorable"] != "yes" or (cid in done and cid in have):
            continue
        posted = bc.utc(call["posted_at"])
        if now < posted + WINDOW + pd.Timedelta(hours=1):
            continue                                        # still in its window
        ups = [u for _, u in updates[updates["call_id"].astype(str) == cid].iterrows()]
        wait = waiting_for_review(call, ups, reviewed) if cid not in done else ""
        if wait:
            print(f"  signal {cid} waits: post {wait} needs Claude's review", file=sys.stderr)
            continue
        try:
            bars = bars_for(call["instrument"], posted.floor("h"), posted + WINDOW)
        except Exception as exc:  # no prices tonight: it waits
            print(f"  ! signal {cid}: {exc}", file=sys.stderr)
            continue
        if cid not in done:
            out = score_signal(call, bars, ups, ended=True)     # its 24 hours are over by the clock
            if out is None:
                continue
            if not out:
                never.append({"id": cid, "posted_at": call["posted_at"], "kind": call["kind"],
                              "instrument": call["instrument"], "leg": "call", "side": call["side"],
                              "outcome": "not filled", "r": 0, "risk_rs": 0, "pnl_rs": 0,
                              "scored_at": now.strftime("%Y-%m-%dT%H:%M:%SZ")})
            rows += out
        if cid not in have:
            checks += variants(call, bars, ups, ended=True) or []
    bc.append(p["results"], bc.RESULT_COLS, rows + never)
    bc.append(p["variants"], bc.VARIANT_COLS, checks)
    return len(rows) + len(never)


# ------------------------------------ for the page ------------------------------------
PROMO = re.compile(r"\b(?:vip|inner\s*circle|dm\s+us|join|offer|bonus|deposit|discount|code|register|referral|"
                   r"funded|community|contact\s+us|subscribe|live\s+start|youtube|instagram)\b", re.I)


claim_verdict = bc.claim_verdict      # the same check for every channel


def summary(ch):
    """What the page shows for one signal channel."""
    p = paths(ch)
    posts = read(p["posts"], bc.POST_COLS).drop_duplicates("id", keep="first")
    posts = posts[posts["id"].astype(int) >= int(ch["start_id"])] if len(posts) else posts
    calls, res = read_both(p, "calls", CALL_COLS), read(p["results"], bc.RESULT_COLS)
    updates, reviewed = read_both(p, "updates", bc.UPDATE_COLS), read_both(p, "reviewed", REVIEW_COLS)
    var = read(p["variants"], bc.VARIANT_COLS)
    if len(res):
        res = res.assign(pnl=pd.to_numeric(res["pnl_rs"]))
    traded = res[res["outcome"] != "not filled"] if len(res) else res
    per_call = traded.groupby("id")["pnl"].sum() if len(traded) else pd.Series(dtype=float)
    updates = bc.checked_claims(updates, res)
    claims = updates[updates["action"] == "claim"] if len(updates) else updates
    scorable = calls[calls["scorable"] == "yes"] if len(calls) else calls
    latest = reviewed.drop_duplicates("id", keep="last") if len(reviewed) else reviewed   # a later line settles it
    review = latest[latest["decision"] == "needs review"] if len(latest) else latest
    deleted = read(p["deleted"], bc.DELETED_COLS)
    fixes = read(p["corrections"], ["id", "added", "source", "note"])
    done, now = set(res["id"].astype(str)) if len(res) else set(), pd.Timestamp.now(tz="UTC")
    waiting = {}
    for _, c in (calls.iterrows() if len(calls) else []):
        if str(c["id"]) not in done and c["scorable"] == "yes" and now >= bc.utc(c["posted_at"]) + WINDOW:
            ups = [u for _, u in updates[updates["call_id"].astype(str) == str(c["id"])].iterrows()] if len(updates) else []
            post = waiting_for_review(c, ups, reviewed)
            if post:
                waiting[str(c["id"])] = post
    return {"posts": len(posts), "promo": int(posts["text"].str.contains(PROMO).sum()) if len(posts) else 0,
            "calls": calls, "results": res, "updates": updates, "claims": claims, "variants": var,
            "review": review, "unread_trades": int(review["note"].str.startswith("Trade post").sum()) if len(review) else 0,
            "unlinked": int((latest["decision"] == "claim without signal").sum()) if len(latest) else 0,
            "deleted": deleted, "waiting": waiting,
            "deleted_calls": int(calls["id"].astype(str).isin(set(deleted["id"].astype(str))).sum()) if len(calls) else 0,
            "corrections": {str(i): g.to_dict("records") for i, g in fixes.groupby("id")} if len(fixes) else {},
            "book": {"value": bc.CAPITAL + float(per_call.sum()), "scored": int(res["id"].nunique()) if len(res) else 0,
                     "wins": int((per_call > 0).sum()), "losses": int((per_call <= 0).sum()),
                     "pending": len(set(scorable["id"]) - set(res["id"] if len(res) else [])), "per_call": per_call}}
