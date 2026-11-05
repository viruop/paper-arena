"""
market_context.py - extra market context for the page and for Claude's decisions:

  * Breadth: the share of Nifty 50 stocks closing above their 200-day and 50-day averages.
    Nifty can hold up while most of its stocks are falling, or the other way round;
    breadth shows how many stocks are actually taking part in a move.
  * Institutional flows: daily net buying or selling by FIIs and DIIs in the cash market.

Data: the same free dataset as the arena (personal, non-commercial use).
The Nifty 50 list lives in nifty50.txt. Update it after each March and September rebalance.

FOR LEARNING ONLY. Not investment advice.
"""

import io
import os
import urllib.parse
import urllib.request

import pandas as pd

import paper_arena as pa

STOCK_URL = ("https://raw.githubusercontent.com/aswinv90/indian-market-historical-data/"
             "main/data/NSE/{}_NS.parquet")
FLOWS_URL = ("https://raw.githubusercontent.com/aswinv90/indian-market-historical-data/"
             "main/data/FLOWS/fii_dii_cash.parquet")
NIFTY50_FILE = "nifty50.txt"
HISTORY_DAYS = 260   # about a year of breadth history for the chart
SAVED_BREADTH = os.path.join("data", "market", "breadth.csv")   # kept by the nightly run; used when the source is down
SAVED_FLOWS = os.path.join("data", "market", "fii_dii.csv")
REVISABLE_DAYS = 10


def nifty50_symbols():
    with open(NIFTY50_FILE, encoding="utf-8") as f:
        return [line.strip() for line in f if line.strip() and not line.startswith("#")]


def _read_parquet(url):
    with urllib.request.urlopen(url, timeout=60) as resp:
        return pd.read_parquet(io.BytesIO(resp.read()))


def stock_close(symbol):
    if pa.DATA_SOURCE == "yfinance":
        import yfinance as yf
        df = yf.Ticker(f"{symbol}.NS").history(period="3y", auto_adjust=True)
    elif pa.DATA_SOURCE == "csv":
        df = pd.read_csv(os.path.join(pa.CSV_FOLDER, "NSE", f"{symbol}.csv"), parse_dates=["Date"],
                         index_col="Date")
    else:
        df = _read_parquet(STOCK_URL.format(urllib.parse.quote(symbol)))
    idx = pd.DatetimeIndex(pd.to_datetime(df.index))
    if idx.tz is not None:
        idx = idx.tz_localize(None)
    s = pd.Series(df["Close"].astype(float).values, index=idx.normalize())
    s = s[~s.index.duplicated(keep="last")].sort_index()
    return s[s > 0].dropna()   # the newest row can be incomplete until the data finishes updating


def breadth():
    """Share of Nifty 50 stocks above their 200-day and 50-day averages, as a daily series."""
    closes, missing = {}, []
    for sym in nifty50_symbols():
        try:
            closes[sym] = stock_close(sym)
        except Exception:
            missing.append(sym)
    if len(closes) < 40:
        raise RuntimeError(f"too few stocks loaded ({len(closes)}); missing: {', '.join(missing)}")
    prices = pd.DataFrame(closes).sort_index()
    prices = prices[prices.notna().sum(axis=1) >= 0.9 * len(closes)]   # days with nearly all stocks
    out = pd.DataFrame(index=prices.index)
    for n in (200, 50):
        avg = prices.rolling(n, min_periods=n).mean()
        valid = avg.notna() & prices.notna()
        above = ((prices > avg) & valid).sum(axis=1).astype(float)
        counted = valid.sum(axis=1).astype(float)
        out[f"above_{n}"] = above / counted.where(counted > 0)
    out = out.dropna().tail(HISTORY_DAYS)
    out["count"] = prices.loc[out.index].notna().sum(axis=1).astype(int)
    _save(SAVED_BREADTH, out)
    return _breadth_dict(out, missing)


def _breadth_dict(out, missing, saved=False):
    latest = out.index[-1]
    return {
        "date": latest,
        "above_200": float(out["above_200"].iloc[-1]),
        "above_50": float(out["above_50"].iloc[-1]),
        "count": int(out["count"].iloc[-1]),
        "missing": missing,
        "series": out[["above_200", "above_50"]],
        "saved": saved,
    }


def _save(path, df):
    """Keep a saved copy: old rows stay, new days are added and only the last REVISABLE_DAYS revised.
    Never fails the run."""
    try:
        old = _read_saved(path)
        if len(old):
            cutoff = old.index[-1] - pd.Timedelta(days=REVISABLE_DAYS)
            kept = old[(old.index <= cutoff) | ~old.index.isin(df.index)]
            df = pd.concat([kept, df[(df.index > cutoff) | ~df.index.isin(old.index)]]).sort_index()
            df = df[~df.index.duplicated(keep="last")]
        os.makedirs(os.path.dirname(path), exist_ok=True)
        out = df.copy()
        out.index.name = "Date"
        out.round(6).to_csv(path)
    except Exception as exc:
        print(f"  ! couldn't update {path} ({exc})")


def _read_saved(path):
    if not os.path.exists(path):
        return pd.DataFrame()
    df = pd.read_csv(path, parse_dates=["Date"], index_col="Date").sort_index()
    return df[~df.index.duplicated(keep="last")]


def saved_breadth():
    out = _read_saved(SAVED_BREADTH)
    if out.empty:
        raise RuntimeError("no saved breadth either")
    return _breadth_dict(out.tail(HISTORY_DAYS), [], saved=True)


def flows(days=10):
    """Daily FII and DII net cash-market buying (+) or selling (-), in rupees crore."""
    df = _read_parquet(FLOWS_URL)
    df["Date"] = pd.to_datetime(df["Date"])
    df = df.set_index("Date").sort_index()[["FII_Net_Cr", "DII_Net_Cr"]]
    _save(SAVED_FLOWS, df.tail(HISTORY_DAYS))
    return df.tail(days)


def saved_flows(days=10):
    df = _read_saved(SAVED_FLOWS)
    if df.empty:
        raise RuntimeError("no saved flows either")
    df = df[["FII_Net_Cr", "DII_Net_Cr"]].tail(days)
    df.attrs["saved"] = True
    return df


def context():
    """Everything above, never failing: a part that can't be loaded comes back as None."""
    out = {"breadth": None, "flows": None}
    try:
        out["breadth"] = breadth()
    except Exception as err:
        print(f"  ! breadth unavailable: {err}")
        try:
            out["breadth"] = saved_breadth()
            print(f"    using the saved copy to {out['breadth']['date']:%d %b %Y}")
        except Exception as err2:
            print(f"    {err2}")
    try:
        out["flows"] = flows()
    except Exception as err:
        print(f"  ! FII/DII flows unavailable: {err}")
        try:
            out["flows"] = saved_flows()
            print(f"    using the saved copy to {out['flows'].index[-1]:%d %b %Y}")
        except Exception as err2:
            print(f"    {err2}")
    return out


def describe(ctx):
    """Plain-text lines for Claude's snapshot."""
    lines = []
    b = ctx.get("breadth")
    if b:
        lines.append(f"Breadth on {b['date']:%d %b}: {b['above_200']:.0%} of Nifty 50 stocks are above their "
                     f"200-day average and {b['above_50']:.0%} above their 50-day average "
                     f"({b['count']} stocks with data).")
        s = b["series"]
        if len(s) > 21:
            lines.append(f"  A month ago: {s['above_200'].iloc[-22]:.0%} above the 200-day, "
                         f"{s['above_50'].iloc[-22]:.0%} above the 50-day.")
    f = ctx.get("flows")
    if f is not None and len(f):
        last = f.iloc[-1]
        lines.append(f"Institutional flows on {f.index[-1]:%d %b} (Rs crore, cash market): FII {last['FII_Net_Cr']:+,.0f}, "
                     f"DII {last['DII_Net_Cr']:+,.0f}. Last 5 sessions: FII {f['FII_Net_Cr'].tail(5).sum():+,.0f}, "
                     f"DII {f['DII_Net_Cr'].tail(5).sum():+,.0f}.")
    return lines


if __name__ == "__main__":
    for line in describe(context()):
        print(line)
