# Paper arena: notes for Claude

A paper-trading arena for learning. Six rule-based agents and a Claude agent each manage ₹1 lakh of virtual money in Nifty 50; seven F&O agents and six gold and multi-asset agents (two of them the Trade Like Berlin channel's rules) trade in arenas of their own, and the channel's Telegram calls are paper traded too. GitHub Actions rebuilds the web page every weekday evening. No real orders are ever placed.

## Files

- `paper_arena.py`: the agents and the arena. `START` and the existing agents' rules must never change after the start.
- `claude_agent.py`: the Claude agent's decision. Runs through the Claude API, or with `--snapshot` and `--record` from a routine or a Claude Code session.
- `decisions/claude.json`: Claude's saved decisions. Only add to it, through `claude_agent.py --record`.
- `decisions/snapshots/`: the data behind each decision, saved automatically.
- `fno_backtest.py`, `fno_arena.py`, `fno_prices.py` and `data/fno/`: the F&O backtest, the seven F&O paper agents and the NSE option prices they trade at.
- `asset_arena.py`, `asset_backtest.py`, `market_data.py` and `data/market/`: the six gold and multi-asset agents (from the Trade Like Berlin research), their backtest, and the saved ETF, gold, silver and S&P 500 prices.
- `berlin.py`: the Trade Like Berlin videos being tested, shown in their own section of the page. To add a new video, use the `berlin-new-video` skill.
- `berlin_calls.py`, `data/berlin/` and `logs/berlin_calls.csv`: the nightly Telegram archive, the tagged calls and their paper-trading results. To tag new calls, use the `berlin-telegram-calls` skill.
- `berlin_study.py`: the forex video's claim checked on every RBNZ decision since 1999.
- `starts.py` and `logs/starts.json`: the start date of every agent newer than the original Nifty ones, written once by the nightly run the first time it sees the agent.
- `logbook.py` and `logs/`: the permanent daily and trade logs, added to automatically every night. `logs/journal.md` is the user's own notes.
- `market_context.py`: Nifty 50 breadth and FII/DII flows. `nifty50.txt` holds the current Nifty 50 list.
- `nifty_backtest.py`: the 2010-to-today backtest, used for learning.
- `build_site.py`: builds `site/index.html`.

## Rules

- Never edit past decisions, snapshots, log rows, saved NSE price files, the Telegram archive or call results, and never backdate anything. Tagged calls are only added, never changed.
- Never move `START`, never edit `logs/starts.json`, and never change an F&O or gold and multi-asset agent's rule; add a new agent instead.
- Never change an existing agent's rule; add a new agent instead.
- For the daily decision, use the `claude-agent-decision` skill. For checking backtests, use the `backtest-review` skill.
