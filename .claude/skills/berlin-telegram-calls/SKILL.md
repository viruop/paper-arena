---
name: berlin-telegram-calls
description: Tags new Trade Like Berlin Telegram posts as paper-tradable calls in data/berlin/telegram_calls.csv. Use for a "Berlin Telegram update", when the user asks what the channel posted, or asks how its calls are doing.
---

# Tag new Trade Like Berlin Telegram calls

The nightly run saves every post and paper trades every tagged call (`berlin_calls.py`). Claude's job is only to decide which new posts are calls and copy their levels exactly. Tag every qualifying post, winners and losers alike, so the record isn't cherry-picked.

## Steps

1. **Read the new posts.** Prefer the saved archive `data/berlin/telegram_posts.csv` in the repository (it has the exact time Telegram showed and the text as first saved). For posts after the last nightly run, read https://t.me/s/tradelikeberlin with the user's Research Tools (`scrape_url`; times on that page are UTC; add `?before=<id>` for older pages).
2. **Find the calls.** A call is a post that tells followers to take a position, or says he has taken one, in a named market. Forecasts ("gold might fall", "expecting a stable close") are not calls. A post saying he exited ends an earlier call: put its time in that call's `exit_at`.
3. **Add one row per call** to `data/berlin/telegram_calls.csv`, never changing existing rows:
   - `id` and `posted_at` (UTC, from the post).
   - `kind`: `level` (Nifty or gold with a direction), `event` (a currency trade on scheduled news, traded with the prep video's plan; set `event_at` to the news time in UTC), or `option` (option premiums, or levels shown only on a chart image).
   - `instrument`: `NIFTY` (also for Sensex calls he says he takes from Nifty's chart), `GOLD`, `BTC`, or a currency pair like `NZDCAD`.
   - `side`, `entry_type` (`market` or `break`), `entry`, `stop`, `target` exactly as written; `rr` when he gives only a reward ratio; `horizon` (`intraday` or `positional`).
   - `price_ref`: for gold, the id of his latest post quoting a price ("GOLD at 4064$"), used to move spot levels onto COMEX futures.
   - `scorable`: `yes`, or `no` for options and chart-only levels; `note`: a short quote and anything filled in. Start the note with `[series]` for trades in his "Scale small capital" series; they also count on that video's card.
   - Levels only in a video or voice note: transcribe voice notes with the Research Tools (`transcribe_media` on the `.ogg` link in the post's `?embed=1` page). In `telegram_posts.csv`, `media` is `voice` for a voice note; rows saved before 30 Oct 2026 say `no` for voice notes, so treat a blank post from then as a possible voice note and open it. Videos Telegram marks "Media is too big" can't be read on the web: ask the user for the levels or a screenshot before adding the row, since rows can't be changed later.
4. **Hand over the file** for the user to upload to `data/berlin/`. Results appear after the next nightly run once each call's window has ended.

## Rules

- Never edit or delete existing rows in `telegram_calls.csv`, `telegram_posts.csv` or `logs/berlin_calls.csv`.
- Use the post's own time, never a later one, and only levels written in the post or the post it replies to.
- Claims made after the move ("BINGO", "worked beautifully") are not calls and change nothing.
- This is paper trading for learning; don't present his calls or the results as advice.
