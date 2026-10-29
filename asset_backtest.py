"""
asset_backtest.py - backtests the gold and multi-asset agents before their paper record counts.

For each agent it reports return a year, worst fall, trades and time invested after costs,
against the benchmark the research report set, in both halves of the period and at double costs,
plus the variant settings the report listed (run only to check robustness, never to pick a winner).

  python asset_backtest.py            uses the saved prices in data/market (kept by the nightly run)
  python asset_backtest.py --nav      falls back to daily ETF NAVs (history to 18 Sep 2026) where no
                                      saved prices exist, e.g. on a computer that can't reach Yahoo

FOR LEARNING ONLY. Backtests flatter; the paper record is the real test.
"""

import argparse
import io
import urllib.request

import numpy as np
import pandas as pd

import asset_arena as aa

FOREX_URL = "https://raw.githubusercontent.com/aswinv90/indian-market-historical-data/main/data/MACRO/forex_rates.csv"


def pct(v, signed=False):
    return "    n/a" if v is None or (isinstance(v, float) and np.isnan(v)) else (f"{v:+7.1%}" if signed else f"{v:7.1%}")


def line(name, st, extra=""):
    print(f"  {name:38s} {pct(st['cagr'], True)} {pct(st['dd'])} {st['ratio']:6.2f} "
          f"{st.get('trades_yr', float('nan')):6.1f} {pct(st.get('invested', float('nan')))}  "
          f"Rs 1L -> {st['end'] / 1e5:6.2f}L{extra}")


def header(title):
    print(f"\n{title}")
    print(f"  {'':38s} {'a year':>7s} {'worst':>7s} {'ret/dd':>6s} {'trd/yr':>6s} {'invest':>7s}")


def report(m, name, W, s0=None, note=""):
    try:
        res = aa.evaluate(m, name, W, s0=s0)
        strict = aa.evaluate(m, name, W, cost_mult=2.0, s0=s0)
        same = aa.evaluate(m, name, W, lag=0, s0=s0)
    except (IndexError, ValueError):
        print(f"\n{name}: no price data yet")
        return None
    print(f"\n=== {name}  ({res['start'].date()} to {res['end'].date()}){note}")
    header("  after costs, trading at the next close (the arena's rule)")
    hit = res["stats"].get("hit")
    line("Agent", res["stats"], f"  first-day hit {pct(hit).strip()} of {res['stats']['entries']}"
         if name in aa.BERLIN else "")
    for bn, st in res["bench"].items():
        line(bn, st)
    for half, (st, bench) in res["halves"].items():
        print(f"  {half} (split at {res['mid'].date()}): agent {pct(st['cagr'], True)} a year, worst {pct(st['dd'])}"
              + (f", hit {pct(st['hit']).strip()}" if name.startswith("3-day") else "")
              + "; " + "; ".join(f"{bn} {pct(b['cagr'], True)}, worst {pct(b['dd'])}" for bn, b in bench.items()))
    print(f"  double costs: {pct(strict['stats']['cagr'], True)} a year | same-close fill (not tradable): "
          f"{pct(same['stats']['cagr'], True)} a year")
    verdict = "PASSES" if res["pass"] and strict["pass"] else "FAILS"
    print(f"  Pass bar (both halves, normal and double costs): {verdict}")
    return res


def arms(m, title, items):
    """Variant settings, run only to see whether the result depends on one lucky setting."""
    print(f"  Variants ({title}):")
    for label, name, W, s0 in items:
        try:
            r = aa.evaluate(m, name, W, s0=s0)
            print(f"    {label:44s} {pct(r['stats']['cagr'], True)} a year, worst {pct(r['stats']['dd'])}, "
                  f"{r['stats']['trades_yr']:.1f} trades/yr" + (f", hit {pct(r['stats']['hit']).strip()}"
                                                              if name in aa.BERLIN else "")
                  + f" ({r['start'].date()} on)")
        except (IndexError, ValueError):
            print(f"    {label:44s} no price data yet")


def usdinr():
    with urllib.request.urlopen(FOREX_URL, timeout=60) as resp:
        fx = pd.read_csv(io.BytesIO(resp.read()), parse_dates=[0], index_col=0)
    return fx.iloc[:, 0].astype(float).sort_index()


def comex_market(m):
    """The gold/silver agents' long history: COMEX gold and silver in rupees (no import duty)."""
    fx = usdinr()
    alt = aa.Market(raw=m.raw)
    for col, src in (("GOLDBEES", "GOLD"), ("SILVERBEES", "SILVER")):
        usd = m.raw[src]["Close"]
        rupees = alt.us(usd) * fx.reindex(alt.idx).ffill()
        alt.close[col] = rupees
    lasts = [m.raw[n].index[-1] for n in ("GOLD", "SILVER")]
    alt.final = min(min(lasts), m.final)
    return alt


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--nav", action="store_true", help="fall back to daily ETF NAVs where no saved prices exist")
    args = ap.parse_args()
    m = aa.Market(nav_fallback=args.nav)
    print("GOLD AND MULTI-ASSET BACKTESTS, after costs (ETFs 0.05% a side, Gold Petal 0.05% a side plus a "
          "monthly roll, idle cash earns 6%)")
    print("Data:")
    for n, src in m.sources.items():
        d = m.raw[n]
        print(f"  {n:10s} {src}" + (f", {d.index[0].date()} to {d.index[-1].date()}" if len(d) else ""))

    if all(m.raw[n].empty for n in aa.Market.INDIA):
        print("\nNo saved ETF prices yet. Run `python market_data.py` first, or add --nav to use daily ETF NAVs.")
    W = aa.strategies(m)
    begin = aa.ready(m)
    report(m, "Gold breakout", W["Gold breakout"])
    arms(m, "report's robustness arms", [
        ("20/10-session channel", "Gold breakout", aa.gold_breakout(m, 20, 10), None),
        ("55/20 channel, only above the 250-day average", "Gold breakout", aa.gold_breakout(m, 55, 20, 250), None)])

    report(m, "Nifty-gold switch", W["Nifty-gold switch"])
    arms(m, "ratio channel length", [
        ("10-session ratio channel", "Nifty-gold switch", aa.nifty_gold_switch(m, 10), None),
        ("55-session ratio channel", "Nifty-gold switch", aa.nifty_gold_switch(m, 55), None)])

    for name in ("Gold/silver reversion", "Gold/silver trend"):
        report(m, name, W[name], note="  [SILVERBEES only exists since Feb 2022]")
    if len(m.raw["GOLD"]) and len(m.raw["SILVER"]) and m.raw["SILVER"].index[0] < pd.Timestamp("2010-01-01"):
        alt = comex_market(m)
        ratio = np.log(alt.close["GOLDBEES"] / alt.close["SILVERBEES"])
        oz = np.exp(ratio)   # rupee prices per ounce cancel out the exchange rate: this is the ounce ratio
        raw_arm = []
        hold = None
        for v in oz.values:
            if not np.isnan(v):
                hold = "SILVERBEES" if v >= 80 else "GOLDBEES" if v < 50 else (hold or "GOLDBEES")
            raw_arm.append(hold)
        print("\n  Long history on COMEX gold and silver converted to rupees:")
        for label, name, Wa in (("reversion (z = 2 in, 0 out)", "Gold/silver reversion", aa.gold_silver_reversion(alt)),
                                ("trend (20-session ratio breakout)", "Gold/silver trend", aa.gold_silver_trend(alt)),
                                ("Reddit thresholds (silver at 80+, gold below 50)", "Gold/silver reversion",
                                 aa.one_hot(alt.idx, raw_arm))):
            r = aa.evaluate(alt, name, Wa)
            b = r["bench"]
            print(f"    {label:48s} {pct(r['stats']['cagr'], True)} a year, worst {pct(r['stats']['dd'])}, "
                  f"{r['stats']['trades_yr']:.1f} trades/yr; hold gold {pct(b['Hold GOLDBEES']['cagr'], True)} "
                  f"(worst {pct(b['Hold GOLDBEES']['dd'])}); passes: {'yes' if r['pass'] else 'no'}")
    else:
        print("\n  Long history for the gold/silver agents needs COMEX gold and silver (data/market/GOLD.csv and "
              "SILVER.csv from the nightly run); skipped here.")

    name = "Gold breakdown short (control)"
    has_comex = len(m.raw["GOLD"]) > 0
    first_comex = begin.get(name)
    report(m, name, W[name] if has_comex else aa.gold_breakdown_short(m, signal="GOLDBEES"), s0=first_comex,
           note="" if has_comex else "  [signals on domestic gold: no COMEX data here]")
    arms(m, "lookbacks, filters and exits; domestic-gold signals for the longest history", [
        ("domestic gold signals (GOLDBEES), 55/20", name, aa.gold_breakdown_short(m, signal="GOLDBEES"), None),
        ("domestic, 20-session breakdown", name, aa.gold_breakdown_short(m, 20, signal="GOLDBEES"), None),
        ("domestic, 70-session breakdown", name, aa.gold_breakdown_short(m, 70, signal="GOLDBEES"), None),
        ("domestic, stop only (no 10% target)", name, aa.gold_breakdown_short(m, target=9.9, signal="GOLDBEES"), None)]
        + ([("COMEX signals with the silver filter", name, aa.gold_breakdown_short(m, silver_filter=True), first_comex)]
           if len(m.raw["SILVER"]) else []))

    name = "3-day rule + US filter (control)"
    first_us = begin.get(name)
    report(m, name, W[name], s0=first_us, note=f"  [US filter from {m.sources['SP500']}]")
    arms(m, "filters", [
        ("without the US filter", name, aa.three_day_rule(m, us_filter=False), None),
        ("without the US or 10-day filters", name, aa.three_day_rule(m, us_filter=False, sma_filter=False), None)])
    n = m.nifty
    Wn = aa.three_day_rule(m, us_filter=False)
    entries = Wn.index[(Wn["NIFTYBEES"] > 0) & (Wn["NIFTYBEES"].shift(1).fillna(0) == 0)]
    gap = [(n["Open"].shift(-1).loc[d] / n["Close"].loc[d] - 1) for d in entries
           if d in n.index and not np.isnan(n["Open"].shift(-1).loc[d])]
    if gap:
        print(f"  Overnight check (no US filter, {len(gap)} signals): next morning's open was higher "
              f"{np.mean(np.array(gap) > 0):.0%} of the time, average gap {np.mean(gap):+.2%}. "
              "That gap is the channel's edge, and an arena that fills at the next close can't capture it.")

    print("\nNotes: channel rules use closing prices only. ETF NAVs stand in for market prices where Yahoo "
          "data is missing. Benchmarks are rebalanced without costs, which makes them slightly harder to beat.")


if __name__ == "__main__":
    main()
