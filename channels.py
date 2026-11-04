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

import berlin_calls as bc

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
    },
}


def posts_path(ch):
    return f"{ch['folder']}/telegram_posts.csv"


def save_all(fetch_for=None):
    """Save every channel's new posts, then read new signals. One channel failing doesn't stop the rest."""
    import signal_calls
    report = []
    for key, ch in CHANNELS.items():
        try:
            fetch = fetch_for(ch) if fetch_for else None
            saved = bc.archive(start_id=ch["start_id"], fetch=fetch, handle=ch["handle"], posts_path=posts_path(ch))
            line = f"{ch['name']}: {saved} new or changed posts saved"
            if ch["tagging"] == "parser":
                counts = signal_calls.parse_new(ch)
                line += f"; {counts['signals']} signals and {counts['updates']} updates read"
            report.append(line)
        except Exception as exc:  # Telegram unreachable or a page changed: try again in 30 minutes
            report.append(f"{ch['name']}: not saved ({exc})")
    print("\n".join(report))
    return report


def score_all_channels():
    """Paper trade the signal channels' finished calls (Berlin is scored by berlin_calls.main)."""
    import signal_calls
    for key, ch in CHANNELS.items():
        if ch["tagging"] != "parser":
            continue
        try:
            print(f"{ch['name']}: scored {signal_calls.score_all(ch)} signals.")
        except Exception as exc:  # e.g. Dukascopy unreachable: the calls wait for the next night
            print(f"{ch['name']}: not scored ({exc})")


if __name__ == "__main__":
    save_all()
