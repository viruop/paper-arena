"""
market_data.py - daily prices for the gold and multi-asset agents (asset_arena.py).

Where the prices come from, in order:
  1. data/market/<NAME>.csv, a saved copy that the nightly run keeps up to date, so a failed
     download never loses history. Old rows are kept as they are; only the last 10 days can be
     revised by a fresh download.
  2. Yahoo Finance's public daily chart data, for ETFs, gold and silver futures and the S&P 500.
     Bars for a session that hasn't closed yet are dropped. Downloads always ask for an explicit
     date span: asked for its whole history ("range=max"), Yahoo quietly sends monthly bars.
     A saved copy that isn't made of daily bars is ignored and downloaded again. Bad prices that
     jump and come straight back (see drop_spikes) are removed.
  3. For backtests only (nav_fallback=True): daily NAVs of the same ETFs from the free mutual
     fund dataset at github.com/aswinv90/indian-market-historical-data. Those NAVs stop on
     18 Sep 2026, so the nightly run never relies on them.

Run it on its own to refresh the saved copies:  python market_data.py
FOR LEARNING ONLY. Data for personal, non-commercial use.
"""

import io
import json
import os
import sys
import urllib.parse
import urllib.request

import numpy as np
import pandas as pd

CACHE_DIR = os.path.join("data", "market")
HISTORY_FROM = "2000-01-01"
REVISABLE_DAYS = 10

# name: Yahoo symbol, exchange time zone, local time after which the day's bar is final,
#       daily-NAV scheme codes (oldest fund house first), aswinv90 index file
SERIES = {
    "GOLDBEES": ("GOLDBEES.NS", "Asia/Kolkata", "16:00", (105085, 115744, 140088), None),
    "NIFTYBEES": ("NIFTYBEES.NS", "Asia/Kolkata", "16:00", (101325, 115728, 140084), None),
    "SILVERBEES": ("SILVERBEES.NS", "Asia/Kolkata", "16:00", (149758,), None),
    "NIFTY50": ("^NSEI", "Asia/Kolkata", "16:00", (), "NIFTY_50"),
    "GOLD": ("GC=F", "America/New_York", "17:30", (), None),       # COMEX gold futures, US dollars
    "SILVER": ("SI=F", "America/New_York", "17:30", (), None),     # COMEX silver futures, US dollars
    "SP500": ("^GSPC", "America/New_York", "16:30", (148381,), None),  # NAV fallback: an S&P 500 index fund in rupees
}
US_SERIES = {"GOLD", "SILVER", "SP500"}

YAHOO_HOSTS = ("query1.finance.yahoo.com", "query2.finance.yahoo.com")
DAYS_BACK = {"1mo": 40, "3mo": 100}   # calendar days asked for by the short downloads
HEADERS = {"User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                          "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"),
           "Accept": "application/json"}
INDEX_URL = "https://raw.githubusercontent.com/aswinv90/indian-market-historical-data/main/data/INDICES/{}.parquet"
NAV_URL = "https://raw.githubusercontent.com/aswinv90/indian-market-historical-data/main/data/MF/nav_part_{}.parquet"
NAV_DIR = os.environ.get("NAV_DIR")   # optional folder holding nav_part_*.parquet, for offline backtests
COLUMNS = ["Open", "High", "Low", "Close"]


# ------------------------------------ Yahoo --------------------------------------
def yahoo(symbol, period="max", tz="Asia/Kolkata", cutoff="16:00", timeout=20):
    """Daily bars from Yahoo's chart endpoint, without any session that hasn't closed yet.

    period is "max" (everything since HISTORY_FROM), "3mo" or "1mo". The span is always sent as
    explicit dates: with range=max Yahoo returns monthly bars even when daily ones are asked for."""
    end = int(pd.Timestamp.now(tz="UTC").timestamp()) + 86400
    start = (int(pd.Timestamp(HISTORY_FROM, tz="UTC").timestamp()) if period == "max"
             else end - 86400 * DAYS_BACK.get(period, 100))
    query = f"period1={start}&period2={end}&interval=1d&includePrePost=false&events=div%2Csplit"
    last_error = None
    for host in YAHOO_HOSTS:
        url = f"https://{host}/v8/finance/chart/{urllib.parse.quote(symbol, safe='')}?{query}"
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=HEADERS), timeout=timeout) as resp:
                data = json.load(resp)
            result = data["chart"]["result"][0]
            break
        except Exception as exc:  # try the other host, then give up
            last_error = exc
    else:
        raise RuntimeError(f"Yahoo has no data for {symbol}: {last_error}")
    meta = result.get("meta", {})
    if meta.get("dataGranularity", "1d") != "1d":
        raise RuntimeError(f"Yahoo sent {meta.get('dataGranularity')} bars for {symbol}, not daily ones")
    stamps = result.get("timestamp") or []
    quote = result["indicators"]["quote"][0]
    zone = meta.get("exchangeTimezoneName") or tz
    days = pd.to_datetime(stamps, unit="s", utc=True).tz_convert(zone).tz_localize(None).normalize()
    df = pd.DataFrame({c: pd.to_numeric(pd.Series(quote.get(c.lower(), [np.nan] * len(days))), errors="coerce").values
                       for c in COLUMNS}, index=days)
    df = df[df["Close"] > 0]
    df = df[~df.index.duplicated(keep="last")].sort_index()
    now = pd.Timestamp.now(tz=zone)
    if len(df) and df.index[-1] >= now.tz_localize(None).normalize() and now.strftime("%H:%M") < cutoff:
        df = df.iloc[:-1]                       # today's session is still trading
    df.index.name = "Date"
    df = df.loc[HISTORY_FROM:]
    if not looks_daily(df):
        raise RuntimeError(f"Yahoo's bars for {symbol} aren't daily")
    return drop_spikes(df)


def drop_spikes(df):
    """Remove bad prices that jump and come straight back:
      - a split-like jump of more than 40% that returns to within 3% of the price before it within
        3 sessions (Yahoo shows the Dec 2019 unit splits of GOLDBEES, 1:100, and NIFTYBEES, 1:10,
        that way for two days), and
      - a one-day move of more than 12% that is undone the next session, to within 2% (NIFTYBEES
        on 6 Oct 2010).
    Real swings, such as silver's in Jan to Mar 2026 or Nifty's in Oct 2008 and Mar 2020, don't
    come back that fast and are kept."""
    if len(df) < 3:
        return df
    c = df["Close"].to_numpy(float)
    keep = np.ones(len(c), bool)
    ref, i = c[0], 1
    while i < len(c):
        move = abs(np.log(c[i] / ref))
        back_at = None
        for jump, back, days in ((0.40, 0.03, 3), (0.12, 0.02, 1)):
            if move > np.log(1 + jump):
                back_at = next((k for k in range(1, days + 1)
                                if i + k < len(c) and abs(np.log(c[i + k] / ref)) < np.log(1 + back)), None)
                if back_at is not None:
                    break
        if back_at is not None:
            keep[i:i + back_at] = False          # the bad days
            i += back_at                         # carry on from the day the price came back
            continue
        ref, i = c[i], i + 1
    return df[keep]


def looks_daily(df):
    """True for daily bars. Monthly, weekly or quarterly bars, or a mix of those with daily ones,
    fail: many of their gaps between rows are longer than a week. Holidays never are, and a few
    missing days in a daily series don't matter."""
    if len(df) < 3:
        return True
    gaps = np.diff(df.index.values).astype("timedelta64[D]").astype(int)
    return bool(np.median(gaps) <= 4 and np.mean(gaps > 6) < 0.10)


# ------------------------------------ cache --------------------------------------
def cache_path(name):
    return os.path.join(CACHE_DIR, f"{name}.csv")


def empty():
    return pd.DataFrame({c: pd.Series(dtype=float) for c in COLUMNS}, index=pd.DatetimeIndex([], name="Date"))


def read_cache(name):
    """The saved copy, or nothing if it is missing or isn't made of daily bars (a copy saved from
    Yahoo's monthly bars is never used; the next refresh replaces it with a full daily download)."""
    path = cache_path(name)
    if not os.path.exists(path):
        return empty()
    df = pd.read_csv(path, parse_dates=["Date"], index_col="Date")
    df = df[COLUMNS].astype(float).sort_index()
    if not looks_daily(df):
        print(f"  ! {name}: the saved copy isn't daily prices; ignoring it", file=sys.stderr)
        return empty()
    return drop_spikes(df)


def merge(cached, fresh):
    """Keep saved rows; let a fresh download add new days, fill gaps and revise the last few days."""
    if cached.empty:
        return fresh
    if fresh.empty:
        return cached
    cutoff = cached.index[-1] - pd.Timedelta(days=REVISABLE_DAYS)
    old = cached[cached.index <= cutoff]
    gaps = fresh[(fresh.index <= cutoff) & ~fresh.index.isin(old.index)]
    new = fresh[fresh.index > cutoff]
    return pd.concat([old, gaps, new]).sort_index()


def refresh(name):
    """Download the newest bars for one series into its saved copy. Returns (rows, last date)."""
    symbol, tz, cutoff, _, _ = SERIES[name]
    cached = read_cache(name)
    period = "max" if cached.empty or cached.index[-1] < pd.Timestamp.now() - pd.Timedelta(days=80) else "3mo"
    merged = merge(cached, yahoo(symbol, period, tz, cutoff))
    os.makedirs(CACHE_DIR, exist_ok=True)
    out = merged.round(4)
    out.index.name = "Date"
    out.to_csv(cache_path(name))
    return len(merged), merged.index[-1]


# ------------------------------------- NAVs --------------------------------------
_NAV_PARTS = {}


def nav_part(p):
    if p not in _NAV_PARTS:
        local = os.path.join(NAV_DIR, f"nav_part_{p}.parquet") if NAV_DIR else None
        if local and os.path.exists(local):
            _NAV_PARTS[p] = pd.read_parquet(local)
        else:
            with urllib.request.urlopen(NAV_URL.format(p), timeout=180) as resp:
                _NAV_PARTS[p] = pd.read_parquet(io.BytesIO(resp.read()))
    return _NAV_PARTS[p]


def unsplit(s):
    """Undo unit splits (GOLDBEES 1:100 and NIFTYBEES 1:10 in Dec 2019): a one-day move beyond
    -37.5% or +60% is treated as a split, not a price change."""
    s = s.copy()
    ratio = s / s.shift(1)
    for day in ratio.index[(ratio < 1 / 1.6) | (ratio > 1.6)]:
        r = ratio.loc[day]
        nice = min((1 / 100, 1 / 50, 1 / 20, 1 / 10, 1 / 5, 1 / 4, 1 / 2, 2, 4, 5, 10),
                   key=lambda k: abs(np.log(r / k)))
        factor = nice if abs(np.log(r / nice)) < 0.15 else r
        s.loc[s.index < day] *= factor
    return s


def load_nav(codes):
    """One daily NAV series stitched across fund-house changes (same scheme, same units)."""
    pieces = []
    for code in codes:
        df = nav_part(code % 10)
        s = df[df["schemeCode"] == code].set_index("date")["nav"].astype(float).sort_index()
        pieces.append(s[~s.index.duplicated(keep="last")])
    s = pd.concat(pieces).sort_index()
    s = unsplit(s[~s.index.duplicated(keep="last")])
    s.index = pd.DatetimeIndex(s.index).normalize()
    return pd.DataFrame({"Open": np.nan, "High": np.nan, "Low": np.nan, "Close": s}).loc[HISTORY_FROM:]


def load_index(file):
    with urllib.request.urlopen(INDEX_URL.format(file), timeout=60) as resp:
        df = pd.read_parquet(io.BytesIO(resp.read()))
    idx = pd.DatetimeIndex(pd.to_datetime(df.index))
    if idx.tz is not None:
        idx = idx.tz_localize(None)
    df.index = idx.normalize()
    df = df[COLUMNS].astype(float)
    df = df[df["Close"] > 0]
    return df[~df.index.duplicated(keep="last")].sort_index()


# ------------------------------------ loading ------------------------------------
def load(name, nav_fallback=False):
    """Daily Open/High/Low/Close for one series. df.attrs["source"] says where it came from."""
    symbol, _, _, codes, index_file = SERIES[name]
    df, source = read_cache(name), f"Yahoo {symbol} (saved copy)"
    if index_file:                               # Nifty 50: the arena's usual source, topped up from Yahoo
        try:
            base = load_index(index_file)
            newer = df[df.index > base.index[-1]] if len(df) else df
            df, source = pd.concat([base, newer]).sort_index(), "aswinv90 index file" + (
                f" + Yahoo {symbol}" if len(newer) else "")
        except Exception as exc:
            print(f"  ! {name}: index file unavailable ({exc})", file=sys.stderr)
    if df.empty and nav_fallback and codes:
        df, source = load_nav(codes), "daily NAV (aswinv90 mutual fund data)"
    df = df[~df.index.duplicated(keep="last")].sort_index()
    df.attrs["source"] = source if len(df) else "none"
    return df


def extend_with_yahoo(s, symbol, tz="Asia/Kolkata", cutoff="16:00"):
    """Add Yahoo closes for days newer than a series' last date (used when a data source lags)."""
    try:
        fresh = yahoo(symbol, "1mo", tz, cutoff, timeout=15)["Close"]
    except Exception:
        return s
    newer = fresh[fresh.index > s.index[-1]]
    return pd.concat([s, newer]) if len(newer) else s


def main():
    for name in SERIES:
        try:
            rows, last = refresh(name)
            print(f"{name:11s} {rows:6d} days, latest {last.date()}")
        except Exception as exc:
            print(f"{name:11s} not updated: {exc}")


if __name__ == "__main__":
    main()
