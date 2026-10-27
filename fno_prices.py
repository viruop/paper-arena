"""
fno_prices.py - downloads NSE's daily F&O price file (the "bhavcopy") and saves the Nifty
options the F&O agents need to data/fno/YYYY-MM-DD.csv, so the paper arena can use real
opening and closing prices instead of estimates.

Each night it fetches the newest trading days that don't have a file yet. Besides the two
nearest expiries it keeps every monthly expiry within about three months, for the low-VIX straddle. If NSE can't be
reached, the arena uses estimated prices for that day. After GRACE more trading days a missing
day is given up for good, so saved results never change afterwards.

Run:  python fno_prices.py
FOR LEARNING ONLY. Not investment advice. No real orders are placed.
"""

import io
import os
import sys
import time
import urllib.request
import zipfile

import pandas as pd

FOLDER = os.path.join("data", "fno")
URL = "https://nsearchives.nseindia.com/content/fo/BhavCopy_NSE_FO_0_0_0_{:%Y%m%d}_F_0000.csv.zip"
HEADERS = {"User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                          "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"),
           "Referer": "https://www.nseindia.com/", "Accept": "*/*"}
GRACE = 2            # trading days to keep retrying a missing day
KEEP_EXPIRIES = 2    # nearest expiries to keep
MONTHLY_DAYS = 100   # also keep every monthly expiry within this many days (for the low-VIX straddle)
KEEP_RANGE = 0.08    # strikes within 8% of Nifty

# Our column: NSE's column name in the UDiFF bhavcopy format used since July 2024
COLUMNS = {"symbol": "TckrSymb", "kind": "FinInstrmTp", "expiry": "XpryDt", "strike": "StrkPric",
           "type": "OptnTp", "open": "OpnPric", "high": "HghPric", "low": "LwPric", "close": "ClsPric",
           "settle": "SttlmPric", "underlying": "UndrlygPric", "oi": "OpnIntrst", "volume": "TtlTradgVol"}
KEEP = ["expiry", "strike", "type", "open", "high", "low", "close", "settle", "underlying", "oi", "volume"]


def path(day):
    return os.path.join(FOLDER, f"{pd.Timestamp(day):%Y-%m-%d}.csv")


def fetch(day):
    request = urllib.request.Request(URL.format(pd.Timestamp(day)), headers=HEADERS)
    with urllib.request.urlopen(request, timeout=60) as resp:
        data = resp.read()
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        name = next(n for n in archive.namelist() if n.lower().endswith(".csv"))
        return pd.read_csv(archive.open(name), low_memory=False)


def normalise(raw, day):
    """Keep Nifty index options: the nearest expiries and strikes near Nifty."""
    lookup = {c.strip().lower(): c for c in raw.columns}
    missing = [nse for nse in COLUMNS.values() if nse.lower() not in lookup]
    if missing:
        raise ValueError(f"NSE file is missing columns {missing}")
    df = pd.DataFrame({ours: raw[lookup[nse.lower()]] for ours, nse in COLUMNS.items()})
    df = df[(df["symbol"].astype(str).str.strip() == "NIFTY") & (df["kind"].astype(str).str.strip() == "IDO")].copy()
    df["expiry"] = pd.to_datetime(df["expiry"].astype(str).str.strip(), format="mixed", dayfirst=False).dt.normalize()
    df["type"] = df["type"].astype(str).str.strip().str.upper()
    for c in ["strike", "open", "high", "low", "close", "settle", "underlying", "oi", "volume"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df[df["expiry"] >= pd.Timestamp(day)]
    if df.empty:
        raise ValueError("no Nifty options found in the NSE file")
    spot = df["underlying"].median()
    expiries = pd.Series(sorted(df["expiry"].unique()))
    monthly = expiries.groupby(expiries.dt.to_period("M")).max()      # the last expiry in each month
    keep = set(expiries[:KEEP_EXPIRIES]) | set(monthly[monthly <= pd.Timestamp(day) + pd.Timedelta(days=MONTHLY_DAYS)])
    df = df[df["expiry"].isin(keep) & (df["strike"] - spot).abs().le(spot * KEEP_RANGE)]
    return df[KEEP].sort_values(["expiry", "strike", "type"]).reset_index(drop=True)


def load(day):
    p = path(day)
    if not os.path.exists(p):
        return None
    df = pd.read_csv(p, parse_dates=["expiry"])
    return df


def final_until(dates, start):
    """Latest day up to which every trading day since `start` has its NSE file or was given up."""
    dates = pd.DatetimeIndex(dates)
    since = dates[dates >= pd.Timestamp(start)]
    if since.empty:
        return dates[-1]
    last_ok = since[0] - pd.Timedelta(days=1)
    for i, d in enumerate(since):
        given_up = len(since) - 1 - i >= GRACE
        if os.path.exists(path(d)) or given_up:
            last_ok = d
        else:
            break
    return last_ok


def due(dates, start):
    """Trading days still worth fetching: on or after `start`, without a file, not given up."""
    dates = pd.DatetimeIndex(dates)
    since = dates[dates >= pd.Timestamp(start)]
    recent = since[-(GRACE + 1):]
    return [d for d in recent if not os.path.exists(path(d))]


def update(dates, start):
    os.makedirs(FOLDER, exist_ok=True)
    saved = []
    for day in due(dates, start):
        try:
            df = normalise(fetch(day), day)
            df.to_csv(path(day), index=False)
            saved.append(day)
            print(f"Saved NSE option prices for {day.date()} ({len(df)} contracts).")
        except Exception as exc:  # NSE unreachable, file not published yet, or format changed
            print(f"No NSE option prices for {day.date()} yet: {exc}", file=sys.stderr)
        time.sleep(1)
    return saved


def main():
    import fno_arena
    import fno_backtest as fb
    first = fno_arena.first_start()
    if first is None:
        print("The F&O agents haven't been given a start date yet; nothing to download.")
        return
    update(fb.load_data().index, first)


if __name__ == "__main__":
    main()
