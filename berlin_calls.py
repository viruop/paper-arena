"""
berlin_calls.py - the Trade Like Berlin Telegram channel, archived and paper traded.

It:
  1. saves every new post from the public channel (t.me/s/tradelikeberlin) to
     data/berlin/telegram_posts.csv, with the time Telegram shows, every 30 minutes through
     .github/workflows/telegram.yml (archive()). A post that later changes is saved again as a
     new version, so nothing he edits afterwards rewrites the record;
  and each night (main()):
  2. keeps the last 60 days of 5-minute prices (Yahoo) for every instrument his calls use, in
     data/market/intraday/;
  3. paper trades every call tagged in data/berlin/telegram_calls.csv once its time window has
     ended, and adds the result to logs/berlin_calls.csv. Results are never rewritten.

Tagging (done by Claude in chat, see the berlin-new-video skill): every post from 27 Oct 2026 on
that tells followers to take a position, or says he has taken one, is a call. Forecasts ("gold
might fall") are not. Option-premium trades and levels drawn only on chart images are listed
but can't be scored with free data.

How a call is paper traded (each call risks Rs 1,000, 1% of Rs 1 lakh):
  - "market" entries fill at the open of the first 5-minute bar that starts after the post;
    "break" entries fill when price trades through his level (at the level, or the bar's open
    if it gapped through).
  - Stop and target are his. A missing stop is filled in and stated: 0.2% for Nifty intraday,
    1.5% for positional gold. A target given only as a reward ratio (e.g. 1:2) is placed that
    many stop-distances away. With no target, the trade exits at the end of its window.
  - Windows: Nifty intraday calls end at that day's close; positional gold calls after 14 days;
    a post where he says he exited ends the trade then. If a bar touches both stop and target,
    the stop counts (we can't see the order inside 5 minutes).
  - Gold levels are spot prices (XAUUSD); they are moved onto COMEX futures by the gap between
    futures and his quoted price at the call named in price_ref.
  - Costs: 0.03% a side for Nifty futures, 0.05% for gold futures and Bitcoin, 0.015% for currencies.
  - Bitcoin calls trade BTC-USD; a missing stop is 1% intraday or 3% positional.
  - A break call whose price is already past his target when it fills is skipped: the move
    had already happened.
  - Event calls follow his NZD/CAD prep video: 33 minutes before the news, a "naked" position
    in the direction of the last 5 days (stop 0.20%, target 0.60%, risking Rs 1,000) plus a
    hedge of one buy and one sell (stops 0.15%, targets 0.45%, Rs 500 each), all closed an hour
    after the news, or when he says he exited.

FOR LEARNING ONLY. Paper trading; no real orders. Offshore forex/CFD trading isn't legal for
Indian residents, which is why the currency calls are only ever paper traded here.
"""

import csv
import html
import json
import os
import re
import sys
import urllib.parse
import urllib.request

import numpy as np
import pandas as pd

CHANNEL = "tradelikeberlin"
FOLDER = os.path.join("data", "berlin")
POSTS = os.path.join(FOLDER, "telegram_posts.csv")
CALLS = os.path.join(FOLDER, "telegram_calls.csv")
RESULTS = os.path.join("logs", "berlin_calls.csv")
UPDATES = os.path.join(FOLDER, "telegram_updates.csv")     # his later exits, stop moves and claims (add-only)
REVIEWED = os.path.join(FOLDER, "telegram_reviewed.csv")    # Claude's decision on every post it reviewed (add-only)
DELETED = os.path.join(FOLDER, "telegram_deleted.csv")      # saved posts he later deleted (add-only)
DELETED_COLS = ["id", "posted_at", "noticed_at", "text"]
VARIANTS = os.path.join("logs", "berlin_variants.csv")      # each scored call also late and reversed, and filtered
UPDATE_COLS = ["id", "call_id", "posted_at", "action", "detail", "price", "trigger", "verdict", "note", "added_by"]
VARIANT_COLS = ["id", "variant", "fill_at", "fill", "exit_at", "exit", "outcome", "r", "pnl_rs", "scored_at"]
LATE_MIN = (15, 30)
# Three filters on his Nifty level calls, written down on 20 Nov 2026 and, like an agent's rule, never changed
# (a change is a new filter with a new name). Only calls posted after FILTERS_SET test them: the earlier calls were
# known when the filters were chosen, so they are a look back. Judged at FILTER_CALLS such calls.
#   trend20: only calls in the direction of Nifty's trend: its last close before the post above its 20-day average
#            allows longs, below allows shorts. A call taken is the on-time trade; one left out counts as nothing.
#   open15:  no entry in the first 15 minutes of the session: a fill due before 9:30 am IST waits for the first
#            5-minute bar from 9:30, aiming at the on-time trade's target.
#   retest:  for a call that enters on the break of a level, sell (or buy) only when the price comes back to the
#            level after the break, at the level; no retest before the call ends means no trade.
FILTERS = ("trend20", "open15", "retest")
FILTERS_SET = "2026-11-20"
FILTER_CALLS = 40
TREND_DAYS = 20
OPEN15_UTC = "04:00"                                         # 9:30 am IST
NIFTY_DAILY = os.path.join("data", "market", "NIFTY50.csv")   # saved daily closes (market_data.py)
BARS_DIR = os.path.join("data", "market", "intraday")
POST_COLS = ["id", "posted_at", "seen_at", "edited", "reply_to", "media", "text"]
RESULT_COLS = ["id", "posted_at", "kind", "instrument", "leg", "side", "fill_at", "fill", "stop", "target",
               "exit_at", "exit", "outcome", "r", "risk_rs", "pnl_rs", "scored_at"]

RISK_RS = 1000.0
CAPITAL = 100000.0
SYMBOLS = {"NIFTY": "^NSEI", "GOLD": "GC=F", "BTC": "BTC-USD", "CRUDE": "CL=F"}   # currencies use "<PAIR>=X"
COST = {"NIFTY": 0.0003, "GOLD": 0.0005, "BTC": 0.0005, "CRUDE": 0.0005}   # a side; currencies 0.00015
DEFAULT_STOP = {("NIFTY", "intraday"): 0.002, ("GOLD", "positional"): 0.015, ("GOLD", "intraday"): 0.004,
                ("NIFTY", "positional"): 0.015, ("BTC", "intraday"): 0.01, ("BTC", "positional"): 0.03,
                ("CRUDE", "intraday"): 0.01, ("CRUDE", "positional"): 0.03}
NIFTY_CLOSE_UTC = "10:00"                               # 3:30 pm IST
HEADERS = {"User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                          "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")}
EVENT = {"lead_min": 33, "bias_days": 5, "hold_min": 60,
         "naked": (0.0020, 0.0060, 1000.0), "hedge": (0.0015, 0.0045, 500.0)}


def symbol(instrument):
    return SYMBOLS.get(instrument, f"{instrument}=X")


def cost(instrument):
    return COST.get(instrument, 0.00015)


def utc(text):
    return pd.Timestamp(text).tz_convert("UTC") if pd.Timestamp(text).tzinfo else pd.Timestamp(text, tz="UTC")


# --------------------------------- Telegram ------------------------------------
def fetch_page(before=None, timeout=30, handle=CHANNEL):
    url = f"https://t.me/s/{handle}" + (f"?before={before}" if before else "")
    with urllib.request.urlopen(urllib.request.Request(url, headers=HEADERS), timeout=timeout) as resp:
        return resp.read().decode("utf-8", "replace")


def clean(fragment):
    text = re.sub(r"<br\s*/?>", "\n", fragment)
    text = re.sub(r"<[^>]+>", "", text)
    return html.unescape(text).strip()


def parse(page, handle=CHANNEL):
    """Posts on one page of a channel's public preview: dicts with id, time, text and so on."""
    posts = []
    for block in re.split(r'<div class="tgme_widget_message_wrap', page)[1:]:
        pid = re.search(rf'data-post="{handle}/(\d+)"', block)
        when = re.search(r'<time datetime="([^"]+)"', block)
        if not pid or not when:
            continue
        reply = re.search(r'class="tgme_widget_message_reply[^"]*" href="https://t\.me/[^/]+/(\d+)"', block)
        body = re.search(r'<div class="tgme_widget_message_text js-message_text"[^>]*>(.*?)</div>', block, re.S)
        posts.append({
            "id": int(pid.group(1)),
            "posted_at": pd.Timestamp(when.group(1)).tz_convert("UTC").strftime("%Y-%m-%dT%H:%M:%SZ"),
            "edited": "yes" if re.search(r'message_meta">[^<]*edited', block) else "no",
            "reply_to": reply.group(1) if reply else "",
            # "voice" for a voice note, "yes" for a photo, video or file. Posts saved before 30 Oct 2026
            # have "no" on voice notes: a blank post saved then with "no" is usually a voice note.
            "media": ("voice" if re.search(r"tgme_widget_message_voice", block) else
                      "yes" if re.search(r"tgme_widget_message_(photo|video|roundvideo|document|audio)", block)
                      else "no"),
            "text": clean(body.group(1)) if body else "",
        })
    return posts


def read_posts(path=POSTS):
    if not os.path.exists(path):
        return pd.DataFrame(columns=POST_COLS)
    return pd.read_csv(path, dtype=str, keep_default_na=False)


def append(path, cols, rows):
    if not rows:
        return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    new = not os.path.exists(path)
    with open(path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=cols, lineterminator="\n", extrasaction="ignore")
        if new:
            writer.writeheader()
        writer.writerows(rows)


def post_gone(handle, pid, timeout=20):
    """True if the post's own page says it doesn't exist (deleted), False if it's there, None if unknown."""
    url = f"https://t.me/{handle}/{pid}?embed=1&mode=tme"
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=HEADERS), timeout=timeout) as resp:
            page = resp.read().decode("utf-8", "replace")
    except Exception:
        return None
    if "tgme_widget_message_error" in page or "Post not found" in page:
        return True
    return False if f'data-post="{handle}/{pid}"' in page else None


def note_deleted(saved, seen, deleted_path, gone):
    """Saved posts inside the range just read from the channel that no longer appear there, confirmed on the
    post's own page, are added to deleted_path once. Returns how many were added."""
    if not seen or saved.empty:
        return 0
    lo, hi = min(seen), max(seen)
    done = set(read_posts(deleted_path)["id"].astype(str)) if os.path.exists(deleted_path) else set()
    first = saved.drop_duplicates("id", keep="first").set_index("id")
    now = pd.Timestamp.now(tz="UTC").strftime("%Y-%m-%dT%H:%M:%SZ")
    rows = []
    for pid in sorted(int(i) for i in first.index):
        if lo < pid < hi and pid not in seen and str(pid) not in done and gone(pid) is True:
            r = first.loc[str(pid)]
            rows.append({"id": pid, "posted_at": r["posted_at"], "noticed_at": now, "text": r["text"][:300]})
    append(deleted_path, DELETED_COLS, rows)
    return len(rows)


def archive(start_id=77656, max_pages=15, fetch=None, handle=CHANNEL, posts_path=POSTS, deleted_path=None,
            gone=None, back_to=None):
    """Save new posts, and new versions of changed ones. Returns how many rows were added.
    Works for any public channel (channels.py passes its handle and file); Berlin is the default.
    deleted_path: also note saved posts he has deleted since (see note_deleted). back_to: read back to this
    post id (a full check of the archive); normally only the newest 40 or so posts are read again."""
    fetch = fetch or (lambda before=None: fetch_page(before, handle=handle))
    saved = read_posts(posts_path)
    latest = {}
    for _, row in saved.iterrows():
        latest[int(row["id"])] = row["text"]
    known = max(latest) if latest else start_id
    stop_at = max(back_to if back_to is not None else known - 40, start_id)
    seen, before, pages = {}, None, 0
    while pages < max_pages:
        found = parse(fetch(before), handle)
        pages += 1
        if not found:
            break
        for p in found:
            seen[p["id"]] = p
        oldest = min(p["id"] for p in found)
        if oldest <= stop_at or oldest <= start_id:
            break
        before = oldest
    now = pd.Timestamp.now(tz="UTC").strftime("%Y-%m-%dT%H:%M:%SZ")
    rows = []
    for pid in sorted(seen):
        p = seen[pid]
        if pid < start_id or (pid in latest and latest[pid] == p["text"]):
            continue
        rows.append({**p, "seen_at": now, "edited": p["edited"] if pid not in latest else "changed after saving"})
    append(posts_path, POST_COLS, rows)
    if deleted_path:
        gone = gone or (lambda pid: post_gone(handle, pid))
        found_gone = note_deleted(saved, seen, deleted_path, gone)
        if found_gone:
            print(f"{handle}: {found_gone} saved posts deleted from the channel since")
    return len(rows)


# ------------------------------- 5-minute prices --------------------------------
def yahoo_5m(sym, days=59, timeout=30):
    end = int(pd.Timestamp.now(tz="UTC").timestamp())
    start = end - 86400 * days
    query = f"period1={start}&period2={end}&interval=5m&includePrePost=false"
    last = None
    for host in ("query1.finance.yahoo.com", "query2.finance.yahoo.com"):
        url = f"https://{host}/v8/finance/chart/{urllib.parse.quote(sym, safe='')}?{query}"
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=HEADERS), timeout=timeout) as resp:
                result = json.load(resp)["chart"]["result"][0]
            break
        except Exception as exc:  # try the other host
            last = exc
    else:
        raise RuntimeError(f"no 5-minute prices for {sym}: {last}")
    q = result["indicators"]["quote"][0]
    idx = pd.to_datetime(result.get("timestamp") or [], unit="s", utc=True)
    df = pd.DataFrame({c: pd.to_numeric(pd.Series(q.get(c.lower(), [np.nan] * len(idx))), errors="coerce").values
                       for c in ("Open", "High", "Low", "Close")}, index=idx).dropna()
    df = df[~df.index.duplicated(keep="last")].sort_index()
    return df.iloc[:-1] if len(df) else df          # the newest bar may still be forming


def bars_path(sym):
    return os.path.join(BARS_DIR, re.sub(r"[^A-Za-z0-9]+", "_", sym).strip("_") + "_5m.csv")


def read_bars(sym):
    path = bars_path(sym)
    if not os.path.exists(path):
        return pd.DataFrame(columns=["Open", "High", "Low", "Close"], dtype=float)
    df = pd.read_csv(path, index_col=0)
    df.index = pd.to_datetime(df.index, utc=True)
    return df.astype(float)


REVISE_HOURS = 2       # saved bars this close to the newest saved bar can still be corrected


def update_bars(sym, keep_days=75):
    """Add the newest 5-minute bars to the saved copy. A saved bar stays as first saved, except in the
    last two hours, where the newest bar may still have been forming: Yahoo serves slightly different
    copies of older bars from one download to the next, and taking every new copy rewrote thousands of
    rows each run and could change the prices a call is judged on. Never deletes a saved bar except
    very old ones."""
    old = read_bars(sym)
    new = yahoo_5m(sym)
    if len(old):
        cutoff = old.index.max() - pd.Timedelta(hours=REVISE_HOURS)
        kept = old[(old.index <= cutoff) | ~old.index.isin(new.index)]
        added = new[(new.index > cutoff) | ~new.index.isin(old.index)]
        both = pd.concat([kept, added]).sort_index()
    else:
        both = new.sort_index()
    both = both[both.index >= pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=keep_days)]
    os.makedirs(BARS_DIR, exist_ok=True)
    both.round(5).to_csv(bars_path(sym), index_label="time")
    return len(both)


# --------------------------------- paper trading --------------------------------
def walk(bars, side, fill_at, fill, stop, target, end):
    """Follow a filled trade bar by bar. Returns (exit time, exit price, outcome)."""
    sign = 1 if side == "long" else -1
    path = bars[(bars.index >= fill_at) & (bars.index < end)]
    for t, b in path.iterrows():
        hit_stop = b["Low"] <= stop if sign > 0 else b["High"] >= stop
        hit_target = target is not None and (b["High"] >= target if sign > 0 else b["Low"] <= target)
        if hit_stop:
            gap = b["Open"] < stop if sign > 0 else b["Open"] > stop
            return t, (b["Open"] if gap else stop), "stop"
        if hit_target:
            gap = b["Open"] > target if sign > 0 else b["Open"] < target
            return t, (b["Open"] if gap else target), "target"
    if len(path) == 0:
        return None, None, "no prices"
    return path.index[-1] + pd.Timedelta(minutes=5), path["Close"].iloc[-1], "time"


def walk_managed(bars, side, fill_at, fill, stop, target, end, moves, aims=()):
    """walk() with his stop moves applied. moves: (posted time, new stop, trigger or None). A move counts
    from the first bar that starts after he posted it; one with a trigger ("breakeven when price reaches X")
    counts from the bar after price reaches X. aims: (posted time, new target), counted the same way.
    Returns (exit time, exit price, outcome)."""
    sign = 1 if side == "long" else -1
    path = bars[(bars.index >= fill_at) & (bars.index < end)]
    pending, armed, moved = sorted(moves, key=lambda m: m[0]), [], False
    goals = sorted(aims, key=lambda a: a[0])
    for t, b in path.iterrows():
        while goals and goals[0][0] <= t:
            _, target = goals.pop(0)
        while pending and pending[0][0] <= t:
            _, new, trigger = pending.pop(0)
            if trigger is None:
                stop, moved = new, True
            else:
                armed.append((new, trigger))
        hit_stop = b["Low"] <= stop if sign > 0 else b["High"] >= stop
        hit_target = target is not None and (b["High"] >= target if sign > 0 else b["Low"] <= target)
        if hit_stop:
            gap = b["Open"] < stop if sign > 0 else b["Open"] > stop
            return t, (b["Open"] if gap else stop), ("moved stop" if moved else "stop")
        if hit_target:
            gap = b["Open"] > target if sign > 0 else b["Open"] < target
            return t, (b["Open"] if gap else target), "target"
        for new, trigger in list(armed):
            if (b["High"] >= trigger) if sign > 0 else (b["Low"] <= trigger):
                stop, moved = new, True
                armed.remove((new, trigger))
    if len(path) == 0:
        return None, None, "no prices"
    return path.index[-1] + pd.Timedelta(minutes=5), path["Close"].iloc[-1], "time"


def result_row(call, leg, side, fill_at, fill, stop, target, exit_at, exit_, outcome, risk_rs, instrument):
    sign = 1 if side == "long" else -1
    risk = abs(fill - stop) / fill
    r = (sign * (exit_ / fill - 1) - 2 * cost(instrument)) / risk
    return {"id": call["id"], "posted_at": call["posted_at"], "kind": call["kind"], "instrument": instrument,
            "leg": leg, "side": side, "fill_at": fill_at.strftime("%Y-%m-%dT%H:%M:%SZ"), "fill": round(fill, 5),
            "stop": round(stop, 5), "target": "" if target is None else round(target, 5),
            "exit_at": exit_at.strftime("%Y-%m-%dT%H:%M:%SZ"), "exit": round(exit_, 5), "outcome": outcome,
            "r": round(r, 3), "risk_rs": risk_rs, "pnl_rs": round(r * risk_rs, 2),
            "scored_at": pd.Timestamp.now(tz="UTC").strftime("%Y-%m-%dT%H:%M:%SZ")}


def num(x):
    try:
        v = float(x)
        return None if np.isnan(v) else v
    except (TypeError, ValueError):
        return None


def window_end(call, posted):
    if str(call.get("exit_at", "")).strip():
        return utc(call["exit_at"])
    if call["horizon"] == "intraday" and call["instrument"] == "NIFTY":
        return pd.Timestamp(f"{posted.date()} {NIFTY_CLOSE_UTC}", tz="UTC")
    if call["horizon"] == "intraday":
        return posted + pd.Timedelta(hours=24)
    return posted + pd.Timedelta(days=14)


def level_gap(calls, ref, bars):
    """Futures minus his quoted price, for levels he gives on a spot or CFD chart. price_ref is either the id
    of the call he quoted the price in (gold: "GOLD at 4064$") or "<price>@<UTC time>" for a quote posted
    or shown at that time (crude oil: "96.13@2026-11-04T10:38:42Z")."""
    ref = str(ref or "").strip()
    m = re.fullmatch(r"(\d+(?:\.\d+)?)@(.+)", ref)
    if m:
        after = bars[bars.index >= utc(m.group(2))]
        return 0.0 if after.empty else after["Open"].iloc[0] - float(m.group(1))
    return gold_gap(calls, ref, bars) if ref else 0.0


def gold_gap(calls, ref_id, bars):
    """COMEX futures minus his quoted spot price, at the call he quoted it in."""
    ref = calls[calls["id"].astype(str) == str(ref_id)]
    if ref.empty or num(ref.iloc[0]["entry"]) is None:
        return 0.0
    after = bars[bars.index >= utc(ref.iloc[0]["posted_at"])]
    return 0.0 if after.empty else after["Open"].iloc[0] - num(ref.iloc[0]["entry"])


def score_level(call, bars, calls, updates=(), start=None, flip=False, target_level=None, close_by=None,
                no_entry_before=None, retest=False):
    """One level call: a list with one result row, [] if it never filled, None if not finished yet.
    updates: his later posts about this call from telegram_updates.csv; an exit ends it like exit_at does,
    and stop and target moves apply from when he posted them. start: the earliest fill, for the delay test (a follower
    acting late). flip: the same fill traded the other way, stop and target mirrored (his management is
    left out). target_level: a fixed target (the on-time trade's), so a late follower aims where he did.
    close_by: a UTC time of day ("09:40") by which an intraday trade must be out, for the NIFTYBEES copy
    (berlin_etf.py), which has to close before the broker does it.
    no_entry_before: a UTC time of day ("04:00"): no fill in a bar that starts earlier that day (the open15 filter).
    retest: for a break entry, fill only when a later bar comes back to the level, at the level (the retest filter).
    Without these arguments this is the original rule, unchanged."""
    posted, inst, side = utc(call["posted_at"]), call["instrument"], call["side"]
    end = window_end(call, posted)
    his_exit = bool(str(call.get("exit_at", "")).strip())
    exits = [utc(u["posted_at"]) for u in updates if u["action"] == "exit" and utc(u["posted_at"]) > posted]
    if exits and min(exits) < end:
        end, his_exit = min(exits), True
    if close_by is not None and call["horizon"] == "intraday":
        cut = pd.Timestamp(f"{posted.date()} {close_by}", tz="UTC")
        if cut < end:
            end, his_exit = cut, False
    if bars.empty or bars.index[-1] < end - pd.Timedelta(minutes=5):
        return None                                      # its window hasn't ended in the saved prices
    gap = level_gap(calls, call.get("price_ref"), bars) if inst in ("GOLD", "CRUDE") else 0.0
    sign = 1 if side == "long" else -1
    begin = posted if start is None else max(posted, start)
    after = bars[(bars.index >= begin) & (bars.index < end)]
    if no_entry_before is not None:
        after = after[after.index.strftime("%H:%M") >= no_entry_before]
    if after.empty:
        return []
    if call["entry_type"] == "break":
        level = num(call["entry"]) + gap
        hit = after[(after["Low"] <= level) if sign < 0 else (after["High"] >= level)]
        if hit.empty:
            return []
        fill_at = hit.index[0]
        o = hit["Open"].iloc[0]
        fill = min(o, level) if sign < 0 else max(o, level)
        if retest:                                        # back to the level after the break, filled at it
            later = after[after.index > fill_at]
            back = later[(later["High"] >= level) if sign < 0 else (later["Low"] <= level)]
            if back.empty:
                return []
            fill_at, o = back.index[0], back["Open"].iloc[0]
            fill = max(o, level) if sign < 0 else min(o, level)
    elif retest:
        return []                                         # only a break entry has a level to come back to
    else:
        fill_at, fill = after.index[0], after["Open"].iloc[0]
    stop = num(call["stop"])
    stop = stop + gap if stop is not None else fill * (1 - sign * DEFAULT_STOP[(inst, call["horizon"])])
    target = num(call["target"])
    if target is not None:
        target += gap
    elif num(call.get("rr")) is not None:
        target = fill + sign * num(call["rr"]) * abs(fill - stop)
    if target_level is not None:
        target = target_level
    if (stop - fill) * sign >= 0:                        # filled beyond his stop: no sensible trade
        return []
    if target is not None and (target - fill) * sign <= 0:   # the move to his target had already happened
        return []
    moves, aims = [], []
    if flip:
        side, sign = ("short" if side == "long" else "long"), -sign
        stop, target = 2 * fill - stop, (None if target is None else 2 * fill - target)
    else:
        for u in updates:
            if u["action"] == "target" and utc(u["posted_at"]) > posted and num(u["price"]) is not None:
                aims.append((utc(u["posted_at"]), num(u["price"]) + gap))     # "I'll book at X"
            if u["action"] in ("stop", "stop_when") and utc(u["posted_at"]) > posted:
                new = fill if str(u["price"]).strip().lower() == "entry" else num(u["price"])
                trigger = num(u["trigger"]) if u["action"] == "stop_when" else None
                if new is None or (u["action"] == "stop_when" and trigger is None):
                    continue
                if str(u["price"]).strip().lower() != "entry":
                    new += gap
                moves.append((utc(u["posted_at"]), new, None if trigger is None else trigger + gap))
    if moves or aims:
        exit_at, exit_, outcome = walk_managed(bars, side, fill_at, fill, stop, target, end, moves, aims)
    else:
        exit_at, exit_, outcome = walk(bars, side, fill_at, fill, stop, target, end)
    if exit_at is None:
        return []
    if outcome == "time" and his_exit:
        outcome = "his exit"
    return [result_row(call, "call", side, fill_at, fill, stop, target, exit_at, exit_, outcome, RISK_RS, inst)]


OPTION_TRADE = re.compile(r"\b(?:CE|PE|puts?|calls?|options?)\b", re.I)


def option_on_underlying(call):
    """An options trade with a direction, in a market there are prices for: it's also scored on the market."""
    return (call["kind"] == "option" and call["side"] in ("long", "short") and call["instrument"] in SYMBOLS
            and bool(OPTION_TRADE.search(str(call["note"]))))


def score_option(call, bars, calls, updates=()):
    """An options trade scored on the market it's on, in its own book: in at the next bar after the post,
    the usual default stop for that market and horizon, no target, out at the end of the window or when he
    says he exited. Option premiums themselves can't be priced with free data."""
    plain = dict(call)
    plain.update(entry_type="market", entry="", stop="", target="", rr="", price_ref="")
    rows = score_level(plain, bars, calls, updates)
    for row in rows or []:
        row["leg"] = "underlying"
    return rows


def variant_rows(call, bars, calls, updates=()):
    """The same call 15 and 30 minutes late (a follower acting late) and reversed (did his direction
    matter?). Checks only: they never change the call's own result. None if not finished yet."""
    posted, now = utc(call["posted_at"]), pd.Timestamp.now(tz="UTC").strftime("%Y-%m-%dT%H:%M:%SZ")
    base = score_level(call, bars, calls, updates)
    if base is None:
        return None
    if not base:
        return []
    aim = num(base[0]["target"])                           # where the on-time trade aimed
    checks = [(f"late{m}", {"start": posted + pd.Timedelta(minutes=m), "target_level": aim}) for m in LATE_MIN]
    checks.append(("flip", {"flip": True}))
    out = []
    for name, kwargs in checks:
        res = score_level(call, bars, calls, updates, **kwargs)
        if res is None:
            return None
        row = res[0] if res else {}
        out.append({"id": call["id"], "variant": name, "fill_at": row.get("fill_at", ""), "fill": row.get("fill", ""),
                    "exit_at": row.get("exit_at", ""), "exit": row.get("exit", ""),
                    "outcome": row.get("outcome", "not filled"), "r": row.get("r", 0), "pnl_rs": row.get("pnl_rs", 0),
                    "scored_at": now})
    return out


def nifty_closes(path=None):
    """Nifty 50's saved daily closes (data/market/NIFTY50.csv), oldest first; empty if missing."""
    path = path or NIFTY_DAILY
    if not os.path.exists(path):
        return pd.Series(dtype=float)
    df = pd.read_csv(path)
    s = pd.Series(pd.to_numeric(df["Close"], errors="coerce").values,
                  index=pd.to_datetime(df.iloc[:, 0], errors="coerce", format="ISO8601"))
    s = s[s.index.notna()].dropna()
    return s[~s.index.duplicated(keep="last")].sort_index()


def nifty_trend(closes, posted, days=TREND_DAYS):
    """"up" or "down": Nifty's last close before the post against the average of the last `days` closes;
    None without enough closes (or exactly on the average)."""
    known = closes[closes.index + pd.Timedelta(NIFTY_CLOSE_UTC + ":00") <= posted.tz_convert("UTC").tz_localize(None)]
    if len(known) < days:
        return None
    last, avg = float(known.iloc[-1]), float(known.iloc[-days:].mean())
    return "up" if last > avg else "down" if last < avg else None


def filters_for(call):
    """The filters that apply to a call: his scorable Nifty level calls only; retest needs a break entry."""
    if call["kind"] != "level" or call["instrument"] != "NIFTY" or call.get("scorable") != "yes":
        return []
    return [f for f in FILTERS if f != "retest" or call["entry_type"] == "break"]


def filter_rows(call, bars, calls, updates=(), closes=None):
    """His Nifty call through each filter that applies to it (FILTERS, written down on 20 Nov 2026).
    Checks only: they never change the call's own result. None if not finished yet (or no trend data)."""
    names = filters_for(call)
    if not names:
        return []
    base = score_level(call, bars, calls, updates)
    if base is None:
        return None
    if not base:
        return []
    now = pd.Timestamp.now(tz="UTC").strftime("%Y-%m-%dT%H:%M:%SZ")
    def row(name, res, outcome=None):
        r = res[0] if res else {}
        return {"id": call["id"], "variant": name, "fill_at": r.get("fill_at", ""), "fill": r.get("fill", ""),
                "exit_at": r.get("exit_at", ""), "exit": r.get("exit", ""),
                "outcome": outcome or r.get("outcome", "not filled"), "r": r.get("r", 0) if r else 0,
                "pnl_rs": r.get("pnl_rs", 0) if r else 0, "scored_at": now}
    out = []
    if "trend20" in names:
        trend = nifty_trend(nifty_closes() if closes is None else closes, utc(call["posted_at"]))
        if trend is None:
            return None
        out.append(row("trend20", base) if (trend == "up") == (call["side"] == "long")
                   else row("trend20", [], f"left out: against the {TREND_DAYS}-day trend ({trend})"))
    if "open15" in names:
        res = score_level(call, bars, calls, updates, no_entry_before=OPEN15_UTC, target_level=num(base[0]["target"]))
        if res is None:
            return None
        out.append(row("open15", res))
    if "retest" in names:
        res = score_level(call, bars, calls, updates, retest=True)
        if res is None:
            return None
        out.append(row("retest", res, None if res else "no retest"))
    return out


def score_event(call, bars):
    """An event call traded with the prep video's plan: naked position plus a two-sided hedge."""
    news = utc(call["event_at"])
    end = utc(call["exit_at"]) if str(call.get("exit_at", "")).strip() else news + pd.Timedelta(minutes=EVENT["hold_min"])
    if bars.empty or bars.index[-1] < end - pd.Timedelta(minutes=5):
        return None
    start = max(news - pd.Timedelta(minutes=EVENT["lead_min"]), utc(call["posted_at"]))   # never before the post
    after = bars[(bars.index >= start) & (bars.index < end)]
    before = bars[bars.index <= start - pd.offsets.BDay(EVENT["bias_days"])]
    if after.empty or before.empty:
        return []
    fill_at, fill = after.index[0], after["Open"].iloc[0]
    bias = "long" if fill > before["Close"].iloc[-1] else "short"
    rows = []
    legs = [("naked", bias, *EVENT["naked"]), ("hedge buy", "long", *EVENT["hedge"]),
            ("hedge sell", "short", *EVENT["hedge"])]
    for leg, side, stop_pct, target_pct, risk_rs in legs:
        sign = 1 if side == "long" else -1
        stop, target = fill * (1 - sign * stop_pct), fill * (1 + sign * target_pct)
        exit_at, exit_, outcome = walk(bars, side, fill_at, fill, stop, target, end)
        if exit_at is None:
            continue
        if outcome == "time" and str(call.get("exit_at", "")).strip():
            outcome = "his exit"
        rows.append(result_row(call, leg, side, fill_at, fill, stop, target, exit_at, exit_, outcome, risk_rs,
                               call["instrument"]))
    return rows


def read_calls():
    if not os.path.exists(CALLS):
        return pd.DataFrame()
    return pd.read_csv(CALLS, dtype=str, keep_default_na=False)


def read_results(path=RESULTS):
    if not os.path.exists(path):
        return pd.DataFrame(columns=RESULT_COLS)
    return pd.read_csv(path, dtype=str, keep_default_na=False)


def read_updates(path=UPDATES):
    """His later posts about tagged calls: exits, stop moves and claims (data/<channel>/telegram_updates.csv).
    Only ever added to; an exit or stop move counts only for a call that hasn't been scored yet."""
    if not os.path.exists(path):
        return pd.DataFrame(columns=UPDATE_COLS)
    return pd.read_csv(path, dtype=str, keep_default_na=False)


def read_variants(path=VARIANTS):
    if not os.path.exists(path):
        return pd.DataFrame(columns=VARIANT_COLS)
    return pd.read_csv(path, dtype=str, keep_default_na=False)


def claim_verdict(detail, outcomes):
    """Does his claim agree with the record? detail: what he claimed ("tp", "tp1", "tp2", "sl", "be",
    "activated"); outcomes: the result legs' outcomes for that call. "" when it can't be checked."""
    if not outcomes or not detail:
        return ""
    hit = [o for o in outcomes if o.startswith("target")]
    if detail == "sl":
        return "matches" if any(o in ("stop", "moved stop") for o in outcomes) else "doesn't match"
    if detail == "tp":
        return "matches" if len(hit) == len(outcomes) else "doesn't match"
    if detail.startswith("tp") and detail[2:].isdigit():
        n = int(detail[2:])
        names = {f"target {n}"} | ({"target"} if n == 1 else set())
        return "matches" if any(o in names for o in hit) else "doesn't match"
    if detail == "be":
        return "matches" if any(o == "moved stop" for o in outcomes) else "doesn't match"
    if detail == "activated":
        return "matches" if outcomes != ["not filled"] else "doesn't match"
    return ""


def checked_claims(updates, results):
    """updates with each claim's verdict: as written when Claude checked it, otherwise worked out from the
    record once the call is scored (for "TP hit", "SL hit" and the like)."""
    if not len(updates):
        return updates
    out = updates.copy()
    legs = results[results["leg"] != "underlying"] if len(results) else results   # option trades' market leg
    outcomes = legs.groupby("id")["outcome"].apply(list).to_dict() if len(legs) else {}    # has no target
    blank = (out["action"] == "claim") & (out["verdict"] == "")
    out.loc[blank, "verdict"] = [claim_verdict(d, outcomes.get(str(c), [])) for d, c in
                                 zip(out.loc[blank, "detail"], out.loc[blank, "call_id"])]
    return out


def read_log(path=REVIEWED):
    """Claude's decision log (data/berlin/telegram_reviewed.csv), or None before it existed."""
    if not os.path.exists(path):
        return None
    return pd.read_csv(path, dtype=str, keep_default_na=False)


def call_end(call, updates=()):
    """When a call's paper trade ends: its window, or his exit post if that came first."""
    posted = utc(call["posted_at"])
    if call["kind"] == "event":
        end = (utc(call["exit_at"]) if str(call.get("exit_at", "")).strip()
               else utc(call["event_at"]) + pd.Timedelta(minutes=EVENT["hold_min"]))
    else:
        end = window_end(call, posted)
    exits = [utc(u["posted_at"]) for u in updates if u["action"] == "exit" and utc(u["posted_at"]) > posted]
    return min([end] + exits)


def waiting_for_review(call, updates, posts, log):
    """Why a call isn't scored yet even though its window may be over ("" if nothing to wait for): a post he
    made before the call ended that Claude hasn't reviewed yet, or one marked "needs levels". His exits and
    stop moves are in those posts, and a score is never redone. Before the decision log existed, nothing waits."""
    if log is None or not len(log) or not len(posts):
        return ""
    end = call_end(call, updates)
    ids = posts["id"].astype(int)
    inside = posts[(ids > int(call["id"])) & (pd.to_datetime(posts["posted_at"], utc=True) <= end)]
    reviewed_upto = int(log["id"].astype(int).max())
    later = [i for i in inside["id"] if int(i) > reviewed_upto]
    if later:
        return f"post {min(later, key=int)} isn't reviewed yet"
    decision = log.drop_duplicates("id", keep="last").set_index("id")["decision"]
    pending = [i for i in inside["id"] if decision.get(i) == "needs levels"]
    return f"post {pending[0]} needs levels" if pending else ""


def updates_for(updates, call_id):
    if not len(updates):
        return []
    return [u for _, u in updates[updates["call_id"].astype(str) == str(call_id)].iterrows()]


def score_all(bars_for):
    """Score every finished call that has no result yet. bars_for(instrument) -> 5-minute bars.
    Options trades with a direction are scored on their market, as leg "underlying", in a book of their own."""
    calls = read_calls()
    if calls.empty:
        return 0
    done = set(read_results()["id"].astype(str))
    updates = read_updates()
    posts, log = read_posts().drop_duplicates("id", keep="first"), read_log()
    rows, never = [], []
    for _, call in calls.iterrows():
        if str(call["id"]) in done:
            continue
        option = call["scorable"] != "yes" and option_on_underlying(call)
        if call["scorable"] != "yes" and not option:
            continue
        ups_ = updates_for(updates, call["id"])
        wait = waiting_for_review(call, ups_, posts, log) if call_end(call, ups_) <= pd.Timestamp.now(tz="UTC") else ""
        if wait:
            print(f"  call {call['id']} waits: {wait}", file=sys.stderr)
            continue
        try:
            bars = bars_for(call["instrument"])
        except Exception as exc:  # no prices for this instrument tonight
            print(f"  ! call {call['id']}: {exc}", file=sys.stderr)
            continue
        ups = updates_for(updates, call["id"])
        if option:
            out = score_option(call, bars, calls, ups)
            if out:
                rows += out
            continue
        out = score_event(call, bars) if call["kind"] == "event" else score_level(call, bars, calls, ups)
        if out is None:
            continue
        if not out:
            never.append({"id": call["id"], "posted_at": call["posted_at"], "kind": call["kind"],
                          "instrument": call["instrument"], "leg": "call", "side": call["side"],
                          "outcome": "not filled", "r": 0, "risk_rs": 0, "pnl_rs": 0,
                          "scored_at": pd.Timestamp.now(tz="UTC").strftime("%Y-%m-%dT%H:%M:%SZ")})
        rows += out
    append(RESULTS, RESULT_COLS, rows + never)
    return len(rows) + len(never)


def score_variants(bars_for):
    """The late and reversed checks, and the filters on his Nifty calls, for every scored level call that
    doesn't have them yet. Each (call, check) is written once; a check added later is filled in for older calls."""
    calls, res, have = read_calls(), read_results(), read_variants()
    if calls.empty or not len(res):
        return 0
    done = set(zip(have["id"].astype(str), have["variant"].astype(str)))
    traded = set(res.loc[(res["kind"] == "level") & (res["outcome"] != "not filled") & (res["leg"] == "call"), "id"].astype(str))
    updates, rows, closes = read_updates(), [], None
    late = [f"late{m}" for m in LATE_MIN] + ["flip"]
    for _, call in calls.iterrows():
        cid = str(call["id"])
        if cid not in traded:
            continue
        missing = [v for v in late + filters_for(call) if (cid, v) not in done]
        if not missing:
            continue
        try:
            bars, mine = bars_for(call["instrument"]), updates_for(updates, cid)
            out = []
            if set(missing) & set(late):
                got = variant_rows(call, bars, calls, mine)
                if got is None:
                    continue
                out += got
            if set(missing) & set(FILTERS):
                closes = nifty_closes() if closes is None else closes
                got = filter_rows(call, bars, calls, mine, closes)
                if got is None:
                    continue
                out += got
        except Exception as exc:  # no prices: try again next time
            print(f"  ! checks for call {cid}: {exc}", file=sys.stderr)
            continue
        rows += [r for r in out if r["variant"] in missing]
    append(VARIANTS, VARIANT_COLS, rows)
    return len(rows)


# --------------------------------- for the page ---------------------------------
def summary():
    """Everything the page shows about the channel: books of paper results, recent calls, archive size,
    his later posts about each call, and the late and reversed checks."""
    calls, res, posts = read_calls(), read_results(), read_posts()
    deleted = read_posts(DELETED) if os.path.exists(DELETED) else pd.DataFrame(columns=DELETED_COLS)
    updates, log = read_updates(), read_log()
    first = posts.drop_duplicates("id", keep="first") if len(posts) else posts
    done, now = set(res["id"].astype(str)) if len(res) else set(), pd.Timestamp.now(tz="UTC")
    waiting = {}
    for _, c in (calls.iterrows() if len(calls) else []):
        if str(c["id"]) not in done and (c["scorable"] == "yes" or option_on_underlying(c)):
            ups = updates_for(updates, c["id"])
            why = waiting_for_review(c, ups, first, log) if call_end(c, ups) <= now else ""
            if why:
                waiting[str(c["id"])] = why
    out = {"posts": int(posts["id"].nunique()) if len(posts) else 0,
           "changed": int((posts["edited"] == "changed after saving").sum()) if len(posts) else 0,
           "calls": calls, "results": res, "books": {}, "updates": checked_claims(updates, res),
           "variants": read_variants(), "deleted": deleted, "waiting": waiting,
           "deleted_calls": int(calls["id"].astype(str).isin(set(deleted["id"].astype(str))).sum()) if len(calls) else 0}
    if len(res):
        res = res.assign(pnl=pd.to_numeric(res["pnl_rs"]), r=pd.to_numeric(res["r"]))
    options = set(c["id"] for _, c in calls.iterrows() if option_on_underlying(c)) if len(calls) else set()
    for book, kinds in (("calls", ("level",)), ("events", ("event",)), ("options", ("option",))):
        part = res[res["kind"].isin(kinds)] if len(res) else res
        traded = part[part["outcome"] != "not filled"] if len(part) else part
        per_call = traded.groupby("id")["pnl"].sum() if len(traded) else pd.Series(dtype=float)
        wanted = (options if book == "options" else
                  set(calls.loc[calls["kind"].isin(kinds) & (calls["scorable"] == "yes"), "id"]) if len(calls) else set())
        out["books"][book] = {
            "value": CAPITAL + (float(traded["pnl"].sum()) if len(traded) else 0.0),
            "scored": int(part["id"].nunique()) if len(part) else 0,
            "wins": int((per_call > 0).sum()), "losses": int((per_call <= 0).sum()),
            "pending": len(wanted - set(part["id"] if len(part) else [])),
            "per_call": per_call,
        }
    return out


def main():
    # New posts are saved every 30 minutes by .github/workflows/telegram.yml (channels.save_all()), not
    # here, so the two workflows never edit the same file at once.
    calls = read_calls()
    done = set(read_results()["id"].astype(str))
    have = read_variants()
    have = set(zip(have["id"].astype(str), have["variant"].astype(str)))
    late = [f"late{m}" for m in LATE_MIN] + ["flip"]
    wanted = [c for _, c in calls.iterrows() if (c["scorable"] == "yes" or option_on_underlying(c))
              and (str(c["id"]) not in done or (c["kind"] == "level" and
                   any((str(c["id"]), v) not in have for v in late + filters_for(c))))] if len(calls) else []
    for sym in sorted({symbol(c["instrument"]) for c in wanted}):
        try:
            print(f"{sym}: {update_bars(sym)} five-minute bars saved.")
        except Exception as exc:  # Yahoo unreachable: the saved bars are used
            print(f"{sym}: not updated ({exc})")
    bars_for = lambda inst: read_bars(symbol(inst))
    print(f"Scored {score_all(bars_for)} calls; {score_variants(bars_for)} late, reversed and filter checks.")
    try:
        import berlin_study
        berlin_study.rates(refresh=True)        # the Fed's NZD/CAD rates for the forex video's check
    except Exception as exc:  # the saved copy is used
        print(f"Fed rates not updated: {exc}")
    try:                                        # the other channels (channels.py), e.g. the signal channel
        import channels
        channels.score_all_channels()
    except Exception as exc:  # one channel failing never stops the arena
        print(f"Other channels not scored: {exc}")
    try:                                        # his Nifty calls again, on NIFTYBEES at Zerodha's charges
        import berlin_etf
        berlin_etf.main()
    except Exception as exc:  # a check on top of the record; it never stops the arena
        print(f"NIFTYBEES copy of the Nifty calls not scored: {exc}")


if __name__ == "__main__":
    main()
