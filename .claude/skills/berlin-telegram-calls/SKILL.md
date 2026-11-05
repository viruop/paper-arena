---
name: berlin-telegram-calls
description: Tags new Trade Like Berlin Telegram posts as calls, later updates and claims, and answers the posts the signal channel's code marked "needs review". Use for a "Berlin Telegram update" or "Telegram update", when the user asks what a channel posted, or asks how its calls are doing.
---

# Telegram calls: tag Trade Like Berlin, review the signal channel

Two channels are paper traded (`channels.py`). The 30-minute workflow saves every post of both. Their calls are read in two different ways:

- **Trade Like Berlin** writes in prose, voice notes and videos, so Claude decides which posts are calls. The nightly run (`berlin_calls.py`) paper trades them.
- **Trade with Akash Garg** posts regular signals, which `signal_calls.py` reads by itself. Claude only answers the posts it marked "needs review".

Decide from what was known when he posted (the post, the posts before it, the price at that moment), never from anything after it. Tag every qualifying post, winners and losers alike. Otherwise the record is cherry-picked.

## Trade Like Berlin

1. **Read the new posts.** Use the archive `data/berlin/telegram_posts.csv` (times in UTC, text as first saved). Review every post with an id greater than the largest id in `data/berlin/telegram_reviewed.csv`, or in `telegram_calls.csv` if the log doesn't exist yet. For posts newer than the archive, read https://t.me/s/tradelikeberlin with the user's Research Tools (`scrape_url`; add `?before=<id>` for older pages).
   - **Voice notes** (`media` is `voice`) are turned into English text by the 30-minute job, newest first, usually within the hour: read the post's row in `data/berlin/voice_notes.csv` (columns `id`, `posted_at`, `transcribed_at`, `seconds`, `model`, `text`). The speech is machine-translated from Hindi and can mishear a number, so take a level, exit or stop from it only when it's clear and fits the price at that moment, and say in the note that it came from a voice note. If there's no row yet, or a number is unclear, transcribe it yourself with the Research Tools (`transcribe_media` on the `.ogg` link from the post's `?embed=1&mode=tme` page). Rows saved before 30 Oct 2026 say `no` even for voice notes, so open a blank post from then.
   - If neither works, decide `needs levels` when the voice note falls inside an open call (it could be an exit or a stop move), otherwise `other` with "voice note, not transcribed yet". If voice notes more than two hours old have no row, say so when you hand over the files: the job's transcription may be failing.

2. **Decide what each post is**, and add one line per post to `data/berlin/telegram_reviewed.csv`. The columns are `id,posted_at,reviewed_at,decision,call_id,note`. Review every new post each night: a call is scored only once this log covers every post he made before it ended, and a post left as `needs levels` holds the scores of the calls it falls inside.
   - `decision` is one of `call`, `update`, `claim`, `other` or `needs levels`.
   - `note` is a few words on why, for example "forecast, no position", "promotion" or "caption of call 77796".
   - A later line for the same post settles it, for example once the user sends the levels for a `needs levels` post.
   - Each night, also look again at older posts whose latest line is `needs levels` or "voice note, not transcribed yet": once the transcript is in `voice_notes.csv`, settle them with a new line.

3. **Calls.** A call tells followers to take a position, or says he has taken one, in a named market. Forecasts ("gold might fall"), recaps and claims made after a move ("BINGO", "worked beautifully") are not calls. Add one row per call to `data/berlin/telegram_calls.csv` with these columns:
   - `id` and `posted_at`: from the post, in UTC.
   - `kind`:
     - `level`: Nifty, gold or Bitcoin with a direction.
     - `event`: a currency trade on scheduled news, traded with the prep video's plan. Set `event_at` to the news time in UTC.
     - `option`: option premiums, or levels shown only on a chart image. An options trade with a direction on Nifty, gold or Bitcoin is also scored on the market itself, in a separate book. For that, set `side` and name the option in the note ("22800 CE", "puts").
   - `instrument`: `NIFTY` (also for Sensex calls he takes from Nifty's chart), `GOLD`, `BTC`, `CRUDE` (crude oil, scored on NYMEX WTI futures; also for his MCX or NSE crude options), or a currency pair like `NZDCAD`.
   - `side`: the direction on the market (buying puts or selling calls is `short`).
   - `entry_type` (`market` or `break`), `entry`, `stop` and `target`: exactly as written.
   - `rr`: when he gives only a reward ratio.
   - `horizon`: `intraday` or `positional`.
   - `price_ref`: for gold, the id of his latest post quoting a gold price ("GOLD at 4064$"). It's used to move his spot levels onto COMEX futures. For crude oil (or gold, when no call row quotes the price), write his quote and its time as `<price>@<UTC time>`, for example `96.13@2026-11-04T10:38:42Z` from "CrudeOil now at 96.13$"; a price shown on his chart in a video, with the chart's clock, works too.
   - `scorable`: `yes`, or `no` for options and chart-only levels.
   - `note`: a short quote and anything filled in. Start it with `[series]` for trades in his "Scale small capital" series.
   - Leave `exit_at` empty. Exits go in the updates file.
   - Levels only in a voice note: use its transcript (step 1), and only levels that are clear.
   - Videos Telegram marks "Media is too big" can't be read: mark the post `needs levels` and ask the user for the levels or a screenshot. Calls can't be changed once added.

4. **Updates** are his later posts about a call already tagged. Add one row per call they apply to in `data/berlin/telegram_updates.csv`, with these columns: `id,call_id,posted_at,action,detail,price,trigger,verdict,note,added_by`. Set `added_by` to `claude`.
   - `exit`: he says he closed it ("Exited the position!", "closed the trade right now"). The call ends at that post.
   - `stop`: he moves the stop or says where he'll get out against the trade ("I'll cover my positional shorts at 4047$", "trail to cost"). `price` is the level as written, or `entry` for cost or breakeven. It applies from the post's time; gold levels are moved onto futures like the call's.
   - `stop_when`: the stop moves once the price reaches a level ("move to breakeven when it reaches 3996"). `price` is `entry` or a level, and `trigger` is that level.
   - `target`: he changes where he'll take profit ("I'll book at 3960"). `price` is the level as written. To tell a stop from a target, compare his level with the price when he posted: past the price on the losing side is a stop (above it for a short), on the winning side a target.
   - `claim`: he reports a result ("target achieved", "SL hit", "200% returns"). Set `detail` to `tp`, `tp1`, `tp2`, `sl`, `be` or `activated` when it is one of those; the page then checks it against the record once the call is scored. Set `verdict` (`matches` or `doesn't match`) only for claims you've checked yourself against `logs/berlin_calls.csv`, and say why in the note. Leave it blank if the claim can't be checked. Claims never change a score.
   - An instruction that covers several open calls ("my positional shorts") gets one row for each of them.
   - Only calls not yet scored are affected by exits and stop moves. A scored result is never rewritten.

5. **Corrections.** If you find a call was misread when it was tagged (a wrong level, a missed exit), add a row to `data/berlin/call_corrections.csv` (`id,added,source,note`). The note should say what the post really said and what the result would have been. The page shows it under the call; the score stays as tagged.

## Trade with Akash Garg (and any other signal channel)

The code's own files are `data/akash/telegram_calls.csv`, `telegram_updates.csv`, `telegram_reviewed.csv` and `voice_notes.csv`. Never edit them: the 30-minute workflow keeps adding to them. Claude's answers go in three files of their own in the same folder, with the same columns. Start each with its header if it doesn't exist yet.

1. Find the posts whose latest line in `telegram_reviewed.csv` plus `claude_reviewed.csv` says `needs review`. Read each one with the posts around it in `telegram_posts.csv`. The code marks every voice note `needs review`. Read its English transcript in `data/akash/voice_notes.csv`; it's machine-translated, so use a level only when it's clear, and if a number is unclear, transcribe it with the Research Tools as for Trade Like Berlin. If there's no transcript yet, leave the post for the next night: signals with it inside their 24 hours wait.
2. Decide, and add a line to `claude_reviewed.csv` with the same post `id` and `posted_at`, the decision (`signal`, `update`, `claim` or `other`), the `call_id` it belongs to, and a note starting "Read by Claude:".
   - **A signal the code couldn't read**, for example a stop or target posted more than 3 minutes later: add the call to `claude_calls.csv` with the code's columns (`kind` `signal`, `horizon` `scalp`, targets separated by `|`, levels exactly as written, `scorable` `yes` for gold, Nasdaq, Bitcoin and forex). Use only levels posted before the trade could have filled.
   - **An instruction or claim the code couldn't tie to one signal**, for example "Closing my Nas100 trade" while two signals were open: add it to `claude_updates.csv` with the right `call_id`, using the actions above.
   - **Anything else:** `other`, with the reason.
3. "TP done" or "SL hit" posts that the code marked `claim without signal` are about trades never posted in the channel. Leave them: they can't be checked.
4. Check every new signal the code read (rows in `telegram_calls.csv` newer than your last review) against its post: market, direction, entry type and every level. If it's wrong, add a row to `data/akash/call_corrections.csv` (`id,added,source,note`; source is the post's link) saying what the post said and what it should have been. The signal and its score stay as read.
5. A signal waits to be scored while a post inside its 24 hours is still `needs review`, so answer them every night.

## Hand over the files

You can't push. Send each changed file with SendUserFile, one file per card. Each caption should give its folder (`data/berlin/` or `data/akash/`) and say to replace the old file. Every upload starts a run, so results appear within minutes for calls whose window has ended.

## Rules

- Never edit or delete existing rows in any of these files, or in `telegram_posts.csv` or `logs/`. Only add rows. Never write to `voice_notes.csv`: only the 30-minute job does.
- Use the post's own time, never a later one, and only levels written in the post or the post it replies to.
- This is paper trading for learning. Don't present his calls or the results as advice.
