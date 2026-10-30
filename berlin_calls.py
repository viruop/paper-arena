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
BARS_DIR = os.path.join("data", "market", "intraday")
POST_COLS = ["id", "posted_at", "seen_at", "edited", "reply_to", "media", "text"]
RESULT_COLS = ["id", "posted_at", "kind", "instrument", "leg", "side", "fill_at", "fill", "stop", "target",
               "exit_at", "exit", "outcome", "r", "risk_rs", "pnl_rs", "scored_at"]

RISK_RS = 1000.0
CAPITAL = 100000.0
SYMBOLS = {"NIFTY": "^NSEI", "GOLD": "GC=F", "BTC": "BTC-USD"}   # currencies use "<PAIR>=X"
COST = {"NIFTY": 0.0003, "GOLD": 0.0005, "BTC": 0.0005}   # a side; currencies 0.00015
DEFAULT_STOP = {("NIFTY", "intraday"): 0.002, ("GOLD", "positional"): 0.015, ("GOLD", "intraday"): 0.004,
                ("NIFTY", "positional"): 0.015, ("BTC", "intraday"): 0.01, ("BTC", "positional"): 0.03}
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
def fetch_page(before=None, timeout=30):
    url = f"https://t.me/s/{CHANNEL}" + (f"?before={before}" if before else "")
    with urllib.request.urlopen(urllib.request.Request(url, headers=HEADERS), timeout=timeout) as resp:
        return resp.read().decode("utf-8", "replace")


def clean(fragment):
    text = re.sub(r"<br\s*/?>", "\n", fragment)
    text = re.sub(r"<[^>]+>", "", text)
    return html.unescape(text).strip()


def parse(page):
    """Posts on one page of the channel's public preview: dicts with id, time, text and so on."""
    posts = []
    for block in re.split(r'<div class="tgme_widget_message_wrap', page)[1:]:
        pid = re.search(rf'data-post="{CHANNEL}/(\d+)"', block)
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
            "media": "yes" if re.search(r"tgme_widget_message_(photo|video|roundvideo|document)", block) else "no",
            "text": clean(body.group(1)) if body else "",
        })
    return posts


def read_posts():
    if not os.path.exists(POSTS):
        return pd.DataFrame(columns=POST_COLS)
    return pd.read_csv(POSTS, dtype=str, keep_default_na=False)


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


def archive(start_id=77656, max_pages=15, fetch=None):
    """Save new posts, and new versions of changed ones. Returns how many rows were added."""
    fetch = fetch or fetch_page
    saved = read_posts()
    latest = {}
    for _, row in saved.iterrows():
        latest[int(row["id"])] = row["text"]
    known = max(latest) if latest else start_id
    seen, before, pages = {}, None, 0
    while pages < max_pages:
        found = parse(fetch(before))
        pages += 1
        if not found:
            break
        for p in found:
            seen[p["id"]] = p
        oldest = min(p["id"] for p in found)
        if oldest <= max(known - 40, start_id) or oldest <= start_id:
            break
        before = oldest
    now = pd.Timestamp.now(tz="UTC").strftime("%Y-%m-%dT%H:%M:%SZ")
    rows = []
    for pid in sorted(seen):
        p = seen[pid]
        if pid < start_id or (pid in latest and latest[pid] == p["text"]):
            continue
        rows.append({**p, "seen_at": now, "edited": p["edited"] if pid not in latest else "changed after saving"})
    append(POSTS, POST_COLS, rows)
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


def update_bars(sym, keep_days=75):
    """Add the newest 5-minute bars to the saved copy; never deletes a saved bar except very old ones."""
    old = read_bars(sym)
    new = yahoo_5m(sym)
    both = pd.concat([old[~old.index.isin(new.index)], new]).sort_index()
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


def gold_gap(calls, ref_id, bars):
    """COMEX futures minus his quoted spot price, at the call he quoted it in."""
    ref = calls[calls["id"].astype(str) == str(ref_id)]
    if ref.empty or num(ref.iloc[0]["entry"]) is None:
        return 0.0
    after = bars[bars.index >= utc(ref.iloc[0]["posted_at"])]
    return 0.0 if after.empty else after["Open"].iloc[0] - num(ref.iloc[0]["entry"])


def score_level(call, bars, calls):
    """One level call: a list with one result row, [] if it never filled, None if not finished yet."""
    posted, inst, side = utc(call["posted_at"]), call["instrument"], call["side"]
    end = window_end(call, posted)
    if bars.empty or bars.index[-1] < end - pd.Timedelta(minutes=5):
        return None                                      # its window hasn't ended in the saved prices
    gap = gold_gap(calls, call.get("price_ref"), bars) if inst == "GOLD" else 0.0
    sign = 1 if side == "long" else -1
    after = bars[(bars.index >= posted) & (bars.index < end)]
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
    else:
        fill_at, fill = after.index[0], after["Open"].iloc[0]
    stop = num(call["stop"])
    stop = stop + gap if stop is not None else fill * (1 - sign * DEFAULT_STOP[(inst, call["horizon"])])
    target = num(call["target"])
    if target is not None:
        target += gap
    elif num(call.get("rr")) is not None:
        target = fill + sign * num(call["rr"]) * abs(fill - stop)
    if (stop - fill) * sign >= 0:                        # filled beyond his stop: no sensible trade
        return []
    if target is not None and (target - fill) * sign <= 0:   # the move to his target had already happened
        return []
    exit_at, exit_, outcome = walk(bars, side, fill_at, fill, stop, target, end)
    if exit_at is None:
        return []
    if outcome == "time" and str(call.get("exit_at", "")).strip():
        outcome = "his exit"
    return [result_row(call, "call", side, fill_at, fill, stop, target, exit_at, exit_, outcome, RISK_RS, inst)]


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


def read_results():
    if not os.path.exists(RESULTS):
        return pd.DataFrame(columns=RESULT_COLS)
    return pd.read_csv(RESULTS, dtype=str, keep_default_na=False)


def score_all(bars_for):
    """Score every finished call that has no result yet. bars_for(instrument) -> 5-minute bars."""
    calls = read_calls()
    if calls.empty:
        return 0
    done = set(read_results()["id"].astype(str))
    rows, never = [], []
    for _, call in calls.iterrows():
        if call["scorable"] != "yes" or str(call["id"]) in done:
            continue
        try:
            bars = bars_for(call["instrument"])
        except Exception as exc:  # no prices for this instrument tonight
            print(f"  ! call {call['id']}: {exc}", file=sys.stderr)
            continue
        out = score_event(call, bars) if call["kind"] == "event" else score_level(call, bars, calls)
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


# --------------------------------- for the page ---------------------------------
def summary():
    """Everything the page shows about the channel: books of paper results, recent calls, archive size."""
    calls, res, posts = read_calls(), read_results(), read_posts()
    out = {"posts": int(posts["id"].nunique()) if len(posts) else 0,
           "changed": int((posts["edited"] == "changed after saving").sum()) if len(posts) else 0,
           "calls": calls, "results": res, "books": {}}
    if len(res):
        res = res.assign(pnl=pd.to_numeric(res["pnl_rs"]), r=pd.to_numeric(res["r"]))
    for book, kinds in (("calls", ("level",)), ("events", ("event",))):
        part = res[res["kind"].isin(kinds)] if len(res) else res
        traded = part[part["outcome"] != "not filled"] if len(part) else part
        per_call = traded.groupby("id")["pnl"].sum() if len(traded) else pd.Series(dtype=float)
        out["books"][book] = {
            "value": CAPITAL + (float(traded["pnl"].sum()) if len(traded) else 0.0),
            "scored": int(part["id"].nunique()) if len(part) else 0,
            "wins": int((per_call > 0).sum()), "losses": int((per_call <= 0).sum()),
            "pending": int(len(set(calls.loc[calls["kind"].isin(kinds) & (calls["scorable"] == "yes"), "id"])
                               - set(part["id"] if len(part) else []))) if len(calls) else 0,
        }
    return out


def main():
    # New posts are saved every 30 minutes by .github/workflows/telegram.yml (archive()), not here,
    # so the two workflows never edit the same file at once.
    calls = read_calls()
    open_ = calls[(calls.get("scorable", pd.Series(dtype=str)) == "yes")] if len(calls) else calls
    done = set(read_results()["id"].astype(str))
    needed = sorted({symbol(i) for i, cid in zip(open_.get("instrument", []), open_.get("id", []))
                     if str(cid) not in done})
    for sym in needed:
        try:
            print(f"{sym}: {update_bars(sym)} five-minute bars saved.")
        except Exception as exc:  # Yahoo unreachable: the saved bars are used
            print(f"{sym}: not updated ({exc})")
    print(f"Scored {score_all(lambda inst: read_bars(symbol(inst)))} calls.")
    try:
        import berlin_study
        berlin_study.rates(refresh=True)        # the Fed's NZD/CAD rates for the forex video's check
    except Exception as exc:  # the saved copy is used
        print(f"Fed rates not updated: {exc}")


if __name__ == "__main__":
    main()
