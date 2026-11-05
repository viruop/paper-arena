"""
channels.py - the Telegram channels this arena saves and paper trades.

  - save_all() runs every 30 minutes (.github/workflows/telegram.yml): it saves every channel's new
    posts, as first seen, to data/<channel>/telegram_posts.csv, then lets signal_calls.py read the
    signal channels' new posts into calls automatically.
  - score_all_channels() runs each night from berlin_calls.main(): it paper trades the signal
    channels' finished calls. Trade Like Berlin's calls are scored by berlin_calls.py itself.

"tagging" says who turns posts into calls: "claude" (read by Claude, see the berlin-telegram-calls
skill, because his calls are written in prose, voice notes and videos) or "parser" (regular signals
read by code in signal_calls.py).

To add a channel: give it a new key, folder and results file, and start it from the newest post on
the day it is added. Never start earlier: posts deleted before then can't be seen any more, so an
earlier start would show only the calls he chose to leave up.
"""

import json
import os

import pandas as pd

import berlin_calls as bc

PRICE_CHECK = os.path.join("data", "dukascopy_check.json")     # is the one-minute price feed reachable?

CHANNELS = {
    "berlin": {
        "name": "Trade Like Berlin", "handle": "tradelikeberlin", "url": "https://t.me/tradelikeberlin",
        "since": "2026-10-27", "start_id": 77656, "folder": "data/berlin", "results": "logs/berlin_calls.csv",
        "tagging": "claude",
    },
    "akash": {
        "name": "Trade with Akash Garg", "handle": "tradewithakashgarg", "url": "https://t.me/tradewithakashgarg",
        "since": "2026-11-04", "start_id": 18992, "folder": "data/akash", "results": "logs/akash_calls.csv",
        "tagging": "parser",
        "scope": "This record covers only the signals he posts on this public Telegram channel. He also trades "
                 "live on his YouTube streams and in a paid group (\"Inner Circle\"), and says the live trades "
                 "aren't posted anywhere else, so his Telegram signals are one slice of his trading, not all of it.",
    },
}


def posts_path(ch):
    return f"{ch['folder']}/telegram_posts.csv"


def deleted_path(ch):
    return f"{ch['folder']}/telegram_deleted.csv"


def save_all(fetch_for=None, gone_for=None, now=None):
    """Save every channel's new posts, note saved posts he has deleted, then read new signals. Once a day
    (the first run after midnight UTC) the whole archive is read again, so older deletions are noticed too.
    One channel failing doesn't stop the rest."""
    import signal_calls
    now = now or pd.Timestamp.now(tz="UTC")
    full = now.hour == 0 and now.minute < 30
    report = []
    for key, ch in CHANNELS.items():
        try:
            fetch = fetch_for(ch) if fetch_for else None
            gone = gone_for(ch) if gone_for else None
            saved = bc.archive(start_id=ch["start_id"], fetch=fetch, handle=ch["handle"], posts_path=posts_path(ch),
                               deleted_path=deleted_path(ch), gone=gone, back_to=ch["start_id"] if full else None,
                               max_pages=60 if full else 15)
            line = f"{ch['name']}: {saved} new or changed posts saved"
            if ch["tagging"] == "parser":
                counts = signal_calls.parse_new(ch)
                line += f"; {counts['signals']} signals and {counts['updates']} updates read"
            report.append(line)
        except Exception as exc:  # Telegram unreachable or a page changed: try again in 30 minutes
            report.append(f"{ch['name']}: not saved ({exc})")
    print("\n".join(report))
    return report


def check_prices(path=PRICE_CHECK, now=None):
    """Read one hour of gold from Dukascopy and note whether it worked, so a broken price feed shows up
    before a signal needs it (on the page, and in the weekly scheduled task)."""
    import dukascopy
    now = now or pd.Timestamp.now(tz="UTC")
    day = now.normalize() - pd.Timedelta(days=1)
    while day.weekday() >= 5:                           # the last weekday: gold doesn't trade at weekends
        day -= pd.Timedelta(days=1)
    start = day + pd.Timedelta(hours=12)
    status = {"checked_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "hour": start.strftime("%Y-%m-%dT%H:%MZ")}
    try:
        bars = dukascopy.minute_bars("XAUUSD", start, start + pd.Timedelta(hours=1))
        status.update(ok=bool(len(bars)), minutes=int(len(bars)),
                      last_bid=round(float(bars["bid_c"].iloc[-1]), 3) if len(bars) else None)
    except Exception as exc:
        status.update(ok=False, error=str(exc)[:200])
    with open(path, "w", encoding="utf-8") as f:
        json.dump(status, f, indent=1)
    print(f"Dukascopy prices: {'working' if status['ok'] else 'not reachable'} ({status.get('error', '')})")
    return status


def score_all_channels():
    """Paper trade the signal channels' finished calls (Berlin is scored by berlin_calls.main)."""
    import signal_calls
    try:
        check_prices()
    except Exception as exc:  # the check itself must never stop the scoring
        print(f"Dukascopy check failed: {exc}")
    for key, ch in CHANNELS.items():
        if ch["tagging"] != "parser":
            continue
        try:
            print(f"{ch['name']}: scored {signal_calls.score_all(ch)} signals.")
        except Exception as exc:  # e.g. Dukascopy unreachable: the calls wait for the next night
            print(f"{ch['name']}: not scored ({exc})")


if __name__ == "__main__":
    save_all()
