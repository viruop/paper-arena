"""
dukascopy.py - one-minute bid and ask prices for spot gold, CFD indices, Bitcoin and currencies.

Signal channels trade spot gold (XAUUSD), CFD indices like NAS100 and Bitcoin with stops only a few
dollars or points away, so 5-minute futures prices (Yahoo's GC=F) are too coarse and too far from
the price they trade. Dukascopy, a Swiss bank, publishes its historical tick prices for free: one
file per instrument per hour, at

    https://datafeed.dukascopy.com/datafeed/<SYMBOL>/<YEAR>/<MONTH-1, two digits>/<DAY>/<HOUR>h_ticks.bi5

Each file is LZMA-compressed; each tick is 20 bytes, big-endian: milliseconds into the hour, ask and
bid as integers (price times a point factor), then ask and bid volumes as floats. Hours with no
trading (weekends) are empty. Times are UTC.

minute_bars() turns the ticks into one-minute bars of the bid and the ask, so a buy fills at the ask
and is stopped out by the bid, as at a broker, with the spread included. Prices are only fetched for
the hours a call needs, and nothing is saved: Dukascopy keeps years of history, so a call can always
be checked again from the source.

If prices look wrong (the decoded price isn't in the instrument's usual range) or can't be fetched,
an error is raised and the call simply waits: nothing is ever scored on doubtful prices.
"""

import lzma
import struct
import time
import urllib.error
import urllib.request

import numpy as np
import pandas as pd

URL = "https://datafeed.dukascopy.com/datafeed/{sym}/{y:04d}/{m:02d}/{d:02d}/{h:02d}h_ticks.bi5"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; paper-arena price check)"}

# Our name -> (Dukascopy symbol, point factor, plausible price range). The range catches a wrong
# point factor or a changed file format before any call is scored on it.
INSTRUMENTS = {
    "XAUUSD": ("XAUUSD", 1000, (500, 20000)),
    "XAGUSD": ("XAGUSD", 1000, (5, 500)),
    "NAS100": ("USATECHIDXUSD", 1000, (5000, 100000)),
    "US30": ("USA30IDXUSD", 1000, (10000, 150000)),
    "SPX500": ("USA500IDXUSD", 1000, (1000, 20000)),
    "BTCUSD": ("BTCUSD", 10, (1000, 1000000)),
    "ETHUSD": ("ETHUSD", 10, (50, 50000)),
    "USOIL": ("LIGHTCMDUSD", 1000, (10, 300)),
}
FX_MAJORS = ["EUR", "GBP", "AUD", "NZD", "USD", "CAD", "CHF", "JPY"]
COLS = ["bid_o", "bid_h", "bid_l", "bid_c", "ask_o", "ask_h", "ask_l", "ask_c"]


def spec(instrument):
    """(Dukascopy symbol, point factor, price range) for one of our instrument names."""
    if instrument in INSTRUMENTS:
        return INSTRUMENTS[instrument]
    if len(instrument) == 6 and instrument[:3] in FX_MAJORS and instrument[3:] in FX_MAJORS:
        jpy = "JPY" in instrument
        return instrument, (1000 if jpy else 100000), ((20, 400) if jpy else (0.2, 5))
    raise KeyError(f"no Dukascopy prices for {instrument}")


def supported(instrument):
    try:
        spec(instrument)
        return True
    except KeyError:
        return False


def decode(raw, hour_start, point):
    """Ticks from one decompressed hour file: DataFrame of bid and ask indexed by UTC time."""
    n = len(raw) // 20
    if n == 0:
        return pd.DataFrame(columns=["bid", "ask"], dtype=float)
    ticks = np.array(struct.unpack(">" + "IIIff" * n, raw[: n * 20]), dtype=float).reshape(n, 5)
    times = hour_start + pd.to_timedelta(ticks[:, 0], unit="ms")
    return pd.DataFrame({"ask": ticks[:, 1] / point, "bid": ticks[:, 2] / point}, index=times)


def fetch_hour(symbol, hour_start, point, timeout=30, retries=3, opener=None):
    """One hour of ticks. Empty for hours with no trading."""
    url = URL.format(sym=symbol, y=hour_start.year, m=hour_start.month - 1, d=hour_start.day, h=hour_start.hour)
    opener = opener or (lambda u: urllib.request.urlopen(urllib.request.Request(u, headers=HEADERS), timeout=timeout).read())
    last = None
    for attempt in range(retries):
        try:
            data = opener(url)
            return decode(lzma.decompress(data), hour_start, point) if data else decode(b"", hour_start, point)
        except urllib.error.HTTPError as exc:
            if exc.code == 404:                 # no file: no trading that hour
                return decode(b"", hour_start, point)
            last = exc
        except Exception as exc:  # timeouts, resets: try again
            last = exc
        time.sleep(1 + attempt)
    raise RuntimeError(f"Dukascopy {symbol} {hour_start:%Y-%m-%d %H}h: {last}")


def minute_bars(instrument, start, end, opener=None):
    """One-minute bid and ask bars (columns bid_o..ask_c) from start to end, UTC. Raises if the
    prices can't be fetched or look wrong."""
    symbol, point, (low, high) = spec(instrument)
    start, end = pd.Timestamp(start).tz_convert("UTC"), pd.Timestamp(end).tz_convert("UTC")
    hours = pd.date_range(start.floor("h"), end.floor("h"), freq="h")
    parts = [fetch_hour(symbol, h, point, opener=opener) for h in hours]
    ticks = pd.concat([p for p in parts if len(p)]) if any(len(p) for p in parts) else pd.DataFrame(columns=["bid", "ask"])
    if not len(ticks):
        return pd.DataFrame(columns=COLS, dtype=float)
    mid = float(np.median((ticks["bid"] + ticks["ask"]) / 2))
    if not low <= mid <= high:
        raise RuntimeError(f"Dukascopy {symbol} prices look wrong (median {mid:g}); not used")
    ticks = ticks[(ticks.index >= start.floor("min")) & (ticks.index < end)]
    bid = ticks["bid"].resample("1min").ohlc().add_prefix("bid_")
    ask = ticks["ask"].resample("1min").ohlc().add_prefix("ask_")
    bars = pd.concat([bid, ask], axis=1).dropna()
    bars.columns = [c.replace("open", "o").replace("high", "h").replace("low", "l").replace("close", "c") for c in bars.columns]
    return bars[COLS]
