"""
berlin_study.py - checks the Trade Like Berlin forex video's claim on 27 years of rate decisions.

The video ("THE FOREX TRADE OPPORTUNITY", 25 Oct 2026) trades NZD/CAD on the Reserve Bank of New
Zealand's decisions: take the direction of the last 4 to 5 days, expect a one-way move of about
0.45-0.65%, and be right "6 out of 10" times.

This study uses the US Federal Reserve's daily noon New York exchange rates (H.10, free at
github.com/datasets/exchange-rates). The RBNZ announces at 9 am or 2 pm New Zealand time, which
is the evening before in New York, so each decision falls between two noon fixings:
  bias  = the last 5 fixings' change before the decision
  move  = the change from the fixing before the decision to the one after it
A hit is a move in the bias direction. The same test on every other day is the control: if
decision days aren't better than ordinary days, the claim adds nothing. Daily data can't see
his 0.15-0.20% stops; the event trades in berlin_calls.py check those with 5-minute prices.

  python berlin_study.py     prints the study
"""

import io
import os
import urllib.request

import numpy as np
import pandas as pd

H10_URL = "https://raw.githubusercontent.com/datasets/exchange-rates/main/data/daily.csv"
CACHE = os.path.join("data", "market", "NZDCAD_fed.csv")
LOOKBACK, BIG = 5, 0.0045

# Every Official Cash Rate decision since the OCR began, from rbnz.govt.nz (date, OCR %, scheduled, note).
# Add new decisions at the end as they happen.
RBNZ = """1999-03-17,4.5,yes,
1999-04-21,4.5,yes,
1999-05-19,4.5,yes,
1999-06-30,4.5,yes,
1999-08-18,4.5,yes,
1999-09-29,4.5,yes,
1999-11-17,5.0,yes,
2000-01-19,5.25,yes,
2000-03-15,5.75,yes,
2000-04-19,6.0,yes,
2000-05-17,6.5,yes,
2000-07-05,6.5,yes,
2000-08-16,6.5,yes,
2000-10-04,6.5,yes,
2000-12-06,6.5,yes,
2001-01-24,6.5,yes,
2001-03-14,6.25,yes,
2001-04-19,6.0,yes,
2001-05-16,5.75,yes,
2001-07-04,5.75,yes,
2001-08-15,5.75,yes,
2001-09-19,5.25,no,emergency cut after the 11 Sep attacks
2001-10-03,5.25,yes,
2001-11-14,4.75,yes,
2002-01-23,4.75,yes,
2002-03-20,5.0,yes,
2002-04-17,5.25,yes,
2002-05-15,5.5,yes,
2002-07-03,5.75,yes,
2002-08-14,5.75,yes,
2002-10-02,5.75,yes,
2002-11-20,5.75,yes,
2003-01-23,5.75,yes,
2003-03-06,5.75,yes,
2003-04-24,5.5,yes,
2003-06-05,5.25,yes,
2003-07-24,5.0,yes,
2003-09-04,5.0,yes,
2003-10-23,5.0,yes,
2003-12-04,5.0,yes,
2004-01-29,5.25,yes,
2004-03-11,5.25,yes,
2004-04-29,5.5,yes,
2004-06-10,5.75,yes,
2004-07-29,6.0,yes,
2004-09-09,6.25,yes,
2004-10-28,6.5,yes,
2004-12-09,6.5,yes,
2005-01-27,6.5,yes,
2005-03-10,6.75,yes,
2005-04-28,6.75,yes,
2005-06-09,6.75,yes,
2005-07-28,6.75,yes,
2005-09-15,6.75,yes,
2005-10-27,7.0,yes,
2005-12-08,7.25,yes,
2006-01-26,7.25,yes,
2006-03-09,7.25,yes,
2006-04-27,7.25,yes,
2006-06-08,7.25,yes,
2006-07-27,7.25,yes,
2006-09-14,7.25,yes,
2006-10-26,7.25,yes,
2006-12-07,7.25,yes,
2007-01-25,7.25,yes,
2007-03-08,7.5,yes,
2007-04-26,7.75,yes,
2007-06-07,8.0,yes,
2007-07-26,8.25,yes,
2007-09-13,8.25,yes,
2007-10-25,8.25,yes,
2007-12-06,8.25,yes,
2008-01-24,8.25,yes,
2008-03-06,8.25,yes,
2008-04-24,8.25,yes,
2008-06-05,8.25,yes,
2008-07-24,8.0,yes,
2008-09-11,7.5,yes,
2008-10-23,6.5,yes,
2008-12-04,5.0,yes,
2009-01-29,3.5,yes,
2009-03-12,3.0,yes,
2009-04-30,2.5,yes,
2009-06-11,2.5,yes,
2009-07-30,2.5,yes,
2009-09-10,2.5,yes,
2009-10-29,2.5,yes,
2009-12-10,2.5,yes,
2010-01-28,2.5,yes,
2010-03-11,2.5,yes,
2010-04-29,2.5,yes,
2010-06-10,2.75,yes,
2010-07-29,3.0,yes,
2010-09-16,3.0,yes,
2010-10-28,3.0,yes,
2010-12-09,3.0,yes,
2011-01-27,3.0,yes,
2011-03-10,2.5,yes,
2011-04-28,2.5,yes,
2011-06-09,2.5,yes,
2011-07-28,2.5,yes,
2011-09-15,2.5,yes,
2011-10-27,2.5,yes,
2011-12-08,2.5,yes,
2012-01-26,2.5,yes,
2012-03-08,2.5,yes,
2012-04-26,2.5,yes,
2012-06-14,2.5,yes,
2012-07-26,2.5,yes,
2012-09-13,2.5,yes,
2012-10-25,2.5,yes,
2012-12-06,2.5,yes,
2013-01-31,2.5,yes,
2013-03-14,2.5,yes,
2013-04-24,2.5,yes,
2013-06-13,2.5,yes,
2013-07-25,2.5,yes,
2013-09-12,2.5,yes,
2013-10-31,2.5,yes,
2013-12-12,2.5,yes,
2014-01-30,2.5,yes,
2014-03-13,2.75,yes,
2014-04-24,3.0,yes,
2014-06-12,3.25,yes,
2014-07-24,3.5,yes,
2014-09-11,3.5,yes,
2014-10-30,3.5,yes,
2014-12-11,3.5,yes,
2015-01-29,3.5,yes,
2015-03-12,3.5,yes,
2015-04-30,3.5,yes,
2015-06-11,3.25,yes,
2015-07-23,3.0,yes,
2015-09-10,2.75,yes,
2015-10-29,2.75,yes,
2015-12-10,2.5,yes,
2016-01-28,2.5,yes,
2016-03-10,2.25,yes,
2016-04-28,2.25,yes,
2016-06-09,2.25,yes,
2016-08-11,2.0,yes,
2016-09-22,2.0,yes,
2016-11-10,1.75,yes,
2017-02-09,1.75,yes,
2017-03-23,1.75,yes,
2017-05-11,1.75,yes,
2017-06-22,1.75,yes,
2017-08-10,1.75,yes,
2017-09-28,1.75,yes,
2017-11-09,1.75,yes,
2018-02-08,1.75,yes,
2018-03-22,1.75,yes,
2018-05-10,1.75,yes,
2018-06-28,1.75,yes,
2018-08-09,1.75,yes,
2018-09-27,1.75,yes,
2018-11-08,1.75,yes,
2019-02-13,1.75,yes,
2019-03-27,1.75,yes,
2019-05-08,1.5,yes,
2019-06-26,1.5,yes,
2019-08-07,1.0,yes,
2019-09-25,1.0,yes,
2019-11-13,1.0,yes,
2020-02-12,1.0,yes,
2020-03-16,0.25,no,emergency cut (Covid)
2020-03-23,0.25,no,bond-buying announcement (Covid)
2020-04-07,0.25,no,bond-buying change (Covid)
2020-05-13,0.25,yes,
2020-06-24,0.25,yes,
2020-08-12,0.25,yes,
2020-09-23,0.25,yes,
2020-11-11,0.25,yes,
2021-02-24,0.25,yes,
2021-04-14,0.25,yes,
2021-05-26,0.25,yes,
2021-07-14,0.25,yes,
2021-08-18,0.25,yes,
2021-10-06,0.5,yes,
2021-11-24,0.75,yes,
2022-02-23,1.0,yes,
2022-04-13,1.5,yes,
2022-05-25,2.0,yes,
2022-07-13,2.5,yes,
2022-08-17,3.0,yes,
2022-10-05,3.5,yes,
2022-11-23,4.25,yes,
2023-02-22,4.75,yes,
2023-04-05,5.25,yes,
2023-05-24,5.5,yes,
2023-07-12,5.5,yes,
2023-08-16,5.5,yes,
2023-10-04,5.5,yes,
2023-11-29,5.5,yes,
2024-02-28,5.5,yes,
2024-04-10,5.5,yes,
2024-05-22,5.5,yes,
2024-07-10,5.5,yes,
2024-08-14,5.25,yes,
2024-10-09,4.75,yes,
2024-11-27,4.25,yes,
2025-02-19,3.75,yes,
2025-04-09,3.5,yes,
2025-05-28,3.25,yes,
2025-07-09,3.25,yes,
2025-08-20,3.0,yes,
2025-10-08,2.5,yes,
2025-11-26,2.25,yes,
2026-02-18,2.25,yes,
2026-04-08,2.25,yes,
2026-05-27,2.25,yes,
2026-07-08,2.5,yes,
2026-09-02,2.75,yes,
2026-10-28,,yes,the decision from the Trade Like Berlin video
"""


def download():
    with urllib.request.urlopen(H10_URL, timeout=120) as resp:
        df = pd.read_csv(io.BytesIO(resp.read()), parse_dates=["Date"])
    wide = df.pivot_table(index="Date", columns="Country", values="Exchange rate")
    return (wide["Canada"] / wide["New Zealand"]).dropna().rename("NZDCAD")   # CAD per USD / NZD per USD


def rates(refresh=True):
    """NZD/CAD at noon New York, saved in data/market so a failed download never loses history."""
    saved = pd.read_csv(CACHE, parse_dates=["Date"], index_col="Date")["NZDCAD"] if os.path.exists(CACHE) else None
    if refresh:
        try:
            fresh = download()
            s = fresh if saved is None else pd.concat([saved[~saved.index.isin(fresh.index)], fresh]).sort_index()
            os.makedirs(os.path.dirname(CACHE), exist_ok=True)
            s.round(6).to_frame().to_csv(CACHE, index_label="Date")
            return s
        except Exception as exc:  # use the saved copy
            print(f"  ! Fed exchange rates not updated: {exc}")
    if saved is None:
        raise RuntimeError("no NZD/CAD rates saved yet")
    return saved


def decisions():
    d = pd.read_csv(io.StringIO(RBNZ), names=["date", "ocr", "scheduled", "note"], dtype=str, keep_default_na=False)
    d["date"] = pd.to_datetime(d["date"])
    return d


def event_rows(s, days, lookback=LOOKBACK):
    rows = []
    idx = s.index
    for day in days:
        before = idx[idx <= day - pd.Timedelta(days=1)]
        after = idx[idx >= day]
        if len(before) <= lookback or after.empty or (after[0] - before[-1]).days > 4:
            continue
        pre, post = s.loc[before[-1]], s.loc[after[0]]
        bias = np.sign(pre / s.loc[before[-1 - lookback]] - 1)
        if bias == 0:
            continue
        move = post / pre - 1
        rows.append({"date": day, "bias": "up" if bias > 0 else "down", "move": move,
                     "hit": bool(np.sign(move) == bias), "big": bool(move * bias >= BIG)})
    return pd.DataFrame(rows)


def control(s, exclude, lookback=LOOKBACK):
    r = s.pct_change()
    bias = np.sign(s / s.shift(lookback) - 1).shift(1)
    ok = bias.notna() & (bias != 0) & r.notna() & ~s.index.isin(exclude)
    hit = (np.sign(r[ok]) == bias[ok]).mean()
    return hit, (r[ok] * bias[ok] >= BIG).mean(), r[ok].abs().median()


def study(s=None):
    s = rates() if s is None else s
    d = decisions()
    past = d[(d["scheduled"] == "yes") & (d["date"] < pd.Timestamp("2026-10-25"))]["date"]
    ev = event_rows(s, past)
    near = set()
    for day in ev["date"]:
        near |= {x for x in s.index if 0 <= (x - day).days <= 1}
    hit, big, med = control(s, sorted(near))
    mid = len(ev) // 2
    halves = {f"{ev['date'].iloc[a].year}-{ev['date'].iloc[b - 1].year}": ev.iloc[a:b]["hit"].mean()
              for a, b in ((0, mid), (mid, len(ev)))}
    variants = {k: event_rows(s, past, k)["hit"].mean() for k in (3, 4, 6)}
    se = np.sqrt(0.25 / len(ev))
    call = event_rows(s, [pd.Timestamp("2026-10-28")])
    return {"n": len(ev), "first": ev["date"].iloc[0], "last": ev["date"].iloc[-1], "hit": ev["hit"].mean(),
            "big": ev["big"].mean(), "median_move": ev["move"].abs().median(), "control_hit": hit,
            "control_big": big, "control_median": med, "halves": halves, "variants": variants,
            "z": (ev["hit"].mean() - 0.5) / se, "rates_until": s.index[-1],
            "call": None if call.empty else call.iloc[0].to_dict()}


def main():
    r = study()
    print(f"RBNZ decisions {r['first'].date()} to {r['last'].date()}: {r['n']} with Fed noon rates for NZD/CAD")
    print(f"  move followed the last 5 days' direction: {r['hit']:.0%} (claimed 60%); ordinary days {r['control_hit']:.0%}")
    print(f"  moved 0.45%+ the bias way: {r['big']:.0%}; ordinary days {r['control_big']:.0%}")
    print(f"  median size of the move: {r['median_move']:.2%}; ordinary days {r['control_median']:.2%}")
    print(f"  halves: {', '.join(f'{k} {v:.0%}' for k, v in r['halves'].items())}; "
          f"other lookbacks: {', '.join(f'{k} days {v:.0%}' for k, v in r['variants'].items())}; z = {r['z']:.1f}")
    until = r["rates_until"].date()
    print(f"  28 Oct 2026: {r['call'] if r['call'] else f'waiting for Fed data (rates to {until})'}")


if __name__ == "__main__":
    main()
