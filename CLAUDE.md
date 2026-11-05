# Paper arena: notes for Claude

A paper-trading arena for learning. Six rule-based agents and a Claude agent each manage ₹1 lakh of virtual money in Nifty 50; seven F&O agents and six gold and multi-asset agents (two of them the Trade Like Berlin channel's rules) trade in arenas of their own, and two Telegram channels' calls are paper traded too (Trade Like Berlin, tagged by Claude, and Trade with Akash Garg, read by code). GitHub Actions rebuilds the web page every weekday evening. No real orders are ever placed.

## Files

- `paper_arena.py`: the agents and the arena. `START` and the existing agents' rules must never change after the start.
- `claude_agent.py`: the Claude agent's decision. Runs through the Claude API, or with `--snapshot` and `--record` from a routine or a Claude Code session.
- `decisions/claude.json`: Claude's saved decisions. Only add to it, through `claude_agent.py --record`.
- `decisions/snapshots/`: the data behind each decision, saved automatically.
- `fno_backtest.py`, `fno_arena.py`, `fno_prices.py` and `data/fno/`: the F&O backtest, the seven F&O paper agents and the NSE option prices they trade at.
- `asset_arena.py`, `asset_backtest.py`, `market_data.py` and `data/market/`: the six gold and multi-asset agents (from the Trade Like Berlin research), their backtest, and the saved ETF, gold, silver and S&P 500 prices.
- `berlin.py`: the Trade Like Berlin videos being tested, shown in their own section of the page. To add a new video, use the `berlin-new-video` skill.
- `channels.py`: the Telegram channels. `.github/workflows/telegram.yml` runs it every 30 minutes to save each channel's new posts to `data/<channel>/telegram_posts.csv`. To add a channel, add an entry there, starting from the newest post on the day it's added.
- `voice_notes.py`: run by the same workflow after the posts are saved. It turns each channel's new voice notes into English text (Whisper small, translated from Hindi, newest first) in `data/<channel>/voice_notes.csv`. Only that job writes the file. A machine transcript can mishear a number: take a level from one only when it's clear, and say so in the note.
- `berlin_calls.py`, `data/berlin/` and `logs/berlin_calls.csv`: Trade Like Berlin's tagged calls (`telegram_calls.csv`), his later posts about them (`telegram_updates.csv`: exits, stop moves, claims), Claude's decision on each post (`telegram_reviewed.csv`), corrections (`call_corrections.csv`) and the results. `logs/berlin_variants.csv` holds each call 15 and 30 minutes late and reversed. To tag new posts, use the `berlin-telegram-calls` skill.
- `signal_calls.py`, `dukascopy.py`, `data/akash/` and `logs/akash_calls.csv`: Trade with Akash Garg's signals, read by code every 30 minutes (decision log `telegram_reviewed.csv`) and scored nightly on Dukascopy one-minute bid and ask prices. Claude answers the posts marked "needs review" in `claude_calls.csv`, `claude_updates.csv` and `claude_reviewed.csv`, never in the code's own files (see the `berlin-telegram-calls` skill).
- `scorecard.py`: "Worth following?", the same ten checks for every channel, written down on 4 Nov 2026. Never change its thresholds.
- `data/<channel>/telegram_deleted.csv`: saved posts he deleted later, noticed by the 30-minute job. `data/dukascopy_check.json`: whether the nightly run could read Dukascopy's prices.
- `berlin_study.py`: the forex video's claim checked on every RBNZ decision since 1999.
- `starts.py` and `logs/starts.json`: the start date of every agent newer than the original Nifty ones, written once by the nightly run the first time it sees the agent.
- `logbook.py` and `logs/`: the permanent daily and trade logs, added to automatically every night. `logs/journal.md` is the user's own notes.
- `market_context.py`: Nifty 50 breadth and FII/DII flows. `nifty50.txt` holds the current Nifty 50 list.
- `events.py` and `data/events/`: the event calendar (`calendar.csv`) and the log of what happened (`log.csv`), shown on the page and in the Claude agent's snapshot, with each market's move around each event. The calendar's NSE holidays and special sessions set when a Claude decision is still allowed. To add events, use the `market-events` skill; check the files with `python events.py --check`.
- `nifty_backtest.py`: the 2010-to-today backtest, used for learning.
- `build_site.py`: builds `site/index.html`.
- `REAL_MONEY.md`: the gap register for real money (blockers, majors, minors, the go/no-go order). Add to it or date items resolved; never delete.

## Rules

- Never edit past decisions, snapshots, log rows, saved NSE price files, the Telegram archives, call results or event rows, and never backdate anything. Tagged calls, updates, decision logs, corrections and the deleted-posts lists are only added to, never changed. A correction is a note; it never changes a score.
- A Berlin call is scored only after the decision log covers every post he made before it ended, and a signal only after no post in its 24 hours is still "needs review": review new posts every night.
- Never move `START`, never edit `logs/starts.json`, and never change an F&O or gold and multi-asset agent's rule; add a new agent instead.
- Never change an existing agent's rule; add a new agent instead.
- For the daily decision, use the `claude-agent-decision` skill. For checking backtests, use the `backtest-review` skill.
