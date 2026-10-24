---
name: backtest-review
description: Reviews a backtest from nifty_backtest.py, or any strategy test in this repository, for the mistakes that make results look better than they are. Use when the user shares backtest output, asks whether a strategy result can be trusted, or wants to change a strategy and test it.
---

# Backtest review

Act as a skeptical reviewer. The goal is to find out whether a result would survive real trading, not to encourage the user.

## Check, in this order

1. **Hidden years.** Was the strategy designed or tuned using only the years before `SPLIT` (or with `END = "2017-12-31"`)? If the later years were looked at while tuning, the out-of-sample result is no longer clean; say so plainly.
2. **Benchmarks.** Compare the return per year and the worst fall with both Cash only and Buy & hold over the same period. A strategy that doesn't beat cash after costs adds nothing. One that trails buy & hold must earn its place with a clearly smaller worst fall.
3. **Costs and timing.** Is `COST_PER_SIDE` at least 0.10%? Does the result survive 0.20% per side and `DELAY = 1`? Short-term strategies often fail one of these.
4. **Fragility.** Does a small parameter change, such as a 150-day instead of a 200-day average, change the result a lot? If only one value works, it's probably luck.
5. **Sample size.** Fewer than about 30 trades, or a result that depends on one or two big trades, is weak evidence.
6. **Time in the market.** A strategy that is in cash most of the time mostly earns the cash rate. Check "Time invested".
7. **Data and period.** Index prices leave out dividends, and tax isn't modelled (short-term gains are taxed more than long-term ones). Start and end dates can flatter a strategy, so try another start year.

## Report

- A one-line verdict: "Promising", "Not convincing yet" or "Likely overfitted".
- The two or three most important problems, each with the exact setting to change and rerun.
- Never suggest tuning parameters on the hidden years.
