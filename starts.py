"""
starts.py - when each newer agent starts paper trading.

The first nightly run that sees a new agent writes its start date to logs/starts.json: the
next weekday after that run. The date is written once and never changed, so an agent can never
start before the day it was added, however late its files are uploaded. (The original Nifty
agents keep their fixed START in paper_arena.py.)
"""

import datetime as dt
import json
import os

import pandas as pd

FILE = os.path.join("logs", "starts.json")
IST = dt.timezone(dt.timedelta(hours=5, minutes=30))


def load():
    if not os.path.exists(FILE):
        return {}
    with open(FILE, encoding="utf-8") as f:
        return json.load(f)


def register(names, now=None):
    """Give each agent not seen before a start date: the next weekday after today (IST)."""
    saved = load()
    today = (now or dt.datetime.now(IST)).date()
    first = (pd.Timestamp(today) + pd.offsets.BDay(1)).date().isoformat()
    added = [n for n in names if n not in saved]
    if added:
        saved.update({n: first for n in added})
        os.makedirs(os.path.dirname(FILE), exist_ok=True)
        with open(FILE, "w", encoding="utf-8") as f:
            json.dump(dict(sorted(saved.items(), key=lambda kv: (kv[1], kv[0]))), f, indent=2, ensure_ascii=False)
            f.write("\n")
    return added


def start_of(name):
    """The planned first trading day, or None if the agent hasn't been registered yet."""
    day = load().get(name)
    return pd.Timestamp(day) if day else None
