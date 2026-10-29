---
name: berlin-new-video
description: Turns a new Trade Like Berlin YouTube video into a tested paper-trading agent in this arena. Use when the user shares a Trade Like Berlin video link, says the channel posted a new strategy, or asks to test one of its videos.
---

# Test a new Trade Like Berlin video

The goal is a fair, mechanical test of what the video actually says, not a better strategy. Keep the creator's rule; only fill gaps the video leaves, and say exactly what was filled.

## Steps

1. **Get the transcript.** Use the user's Research Tools (`youtube_transcript`, Hindi captions are fine), not other scrapers. If YouTube blocks transcript requests, ask the user to paste the transcript or try later.
2. **Write the rule down as stated**, with timestamps: market, timeframe, entry trigger, stop, target or exit, position size, filters, and any claimed accuracy or target (for the claim check). Mark each part "stated" or "added".
3. **Fill only what's missing.** No stop given: add one that fits the rule's own logic (for example the opposite channel) and state it. Offshore forex or CFDs can't be traded legally from India, but they can be paper traded: news-event trades go through the event calls in `berlin_calls.py` (5-minute prices), and a claim about many past events can be checked like `berlin_study.py` does. Intraday-only rules: test them as calls on 5-minute prices, or a daily version in the arena.
4. **Code it as a new agent** with a new name starting with "Berlin" (the first two kept their "(control)" names because they had already started): a signal function and an `AGENTS` entry in `asset_arena.py` (ETFs, MCX futures), or a strategy in `fno_backtest.py` plus a `RULES` entry in `fno_arena.py` (Nifty futures and options). Never change an existing agent.
5. **Backtest it** with `python asset_backtest.py --nav` or `python fno_backtest.py`, then review with the `backtest-review` skill. Report the result plainly, including when the rule fails.
6. **Add an entry to `berlin.py`** keyed by the name it trades under: kind ("agent" or "events"), a short title, video title, URL, publish date, the claim, the changes, and the claimed outcome in plain words. If the claim check needs new numbers, extend `claim_check` in `asset_arena.py`.
7. **Hand over the changed files** and tell the user the agent starts paper trading on the next weekday after the upload.

## Rules

- Never edit an existing agent, `logs/starts.json`, log rows or past decisions.
- Don't present the channel's rules, or the test results, as advice.
