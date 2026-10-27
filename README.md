# Paper arena

Six agents follow simple Nifty rules and Claude makes its own decisions, each with ₹1 lakh of virtual money, and a web page shows how they're doing. GitHub runs everything every weekday evening.

For learning only. Not investment advice. No real orders are placed.

## What's in this folder

| File | What it does |
|---|---|
| `paper_arena.py` | The arena: the agents, plus your own calls in `MANUAL_AGENTS` |
| `claude_agent.py` | The Claude agent's decision: through a routine or the Claude API (see below) |
| `decisions/claude.json` | Claude's saved decisions, with its reasons |
| `decisions/snapshots/` | The data behind each Claude decision (added automatically) |
| `logbook.py` | Adds each new day to the permanent logs |
| `fno_backtest.py` | Backtests seven Nifty futures and options strategies after costs |
| `fno_arena.py` | Paper-trades the same seven strategies |
| `fno_prices.py` | Downloads NSE's daily option prices for the F&O agents |
| `data/fno/` | The NSE option prices the F&O agents traded at (added automatically) |
| `asset_arena.py` | Six gold and multi-asset agents: gold, silver and Nifty ETFs, and MCX gold futures |
| `asset_backtest.py` | Backtests the gold and multi-asset agents against their benchmarks |
| `market_data.py` | Downloads and saves daily ETF, gold, silver and S&P 500 prices |
| `data/market/` | The saved prices (added automatically) |
| `starts.py` | Gives each newer agent its start date the first night it's seen |
| `logs/` | `daily.csv`, `trades.csv` and `starts.json` (added automatically) and your `journal.md` |
| `market_context.py` | Nifty 50 breadth and FII/DII flows, for the page and for Claude |
| `nifty50.txt` | The current Nifty 50 list, used for breadth |
| `CLAUDE.md` and `.claude/skills/` | Notes and skills that Claude Code and routines read |
| `nifty_backtest.py` | The backtest of the same rules from 2010 to today |
| `build_site.py` | Builds the web page into a `site` folder |
| `requirements.txt` | The Python packages GitHub installs |
| `.github/workflows/arena.yml` | Runs everything each weekday evening and publishes the page |

## Set it up once (about 10 minutes)

1. Sign in to GitHub with your **personal** account. You can create one for free at github.com.
2. Click **+** at the top right, then **New repository**. Name it `paper-arena`, choose **Public**, and click **Create repository**. Don't add a README; this folder already has one.
3. On the new, empty repository page, click **uploading an existing file**. Drag in everything from this unzipped folder, including the `.github` folder, and click **Commit changes**.
   - On a Mac, press **Cmd + Shift + .** in Finder to show hidden folders like `.github`.
4. Check that `.github/workflows/arena.yml` now appears in the repository. If it's missing, click **Add file → Create new file**, type `.github/workflows/arena.yml` as the name, paste in the file's contents, and click **Commit changes**.
5. Go to **Settings → Pages**. Under **Build and deployment**, set **Source** to **GitHub Actions**.
6. Go to the **Actions** tab, click **Daily paper arena** on the left, then **Run workflow**. After about two minutes you'll see a green tick.
7. Open `https://YOUR-USERNAME.github.io/paper-arena/`. The link also appears under **Settings → Pages**. Bookmark it on your phone.

The first run starts by itself when you upload the files in step 3. It fails because Pages isn't switched on until step 5. That's expected; the run in step 6 works.

## Every day

Nothing. The page updates on weekdays at about 8:30 pm IST, with a backup run at 11 pm, after the free price data updates. GitHub sometimes starts scheduled runs a little late.

## F&O arena

Seven futures and options strategies trade Nifty in a separate arena, each with ₹1 lakh of virtual money from the first trading day after its files reach the repository:

- **Futures trend:** long Nifty futures above the 200-day average, short below.
- **Intraday futures:** each morning, buy if Nifty closed above its 20-day average, else sell; 0.5% stop-loss; out by the close.
- **Intraday short straddle:** each morning, sell the at-the-money call and put; buy back at the close, or earlier if they rise 30%.
- **Weekly short strangle:** at each expiry, sell a call and a put about 2% away and hold to the next expiry.
- **Weekly iron condor:** the strangle plus protection about 4% away.
- **Weekly option buying:** at each expiry, buy the at-the-money call in an uptrend or the put in a downtrend, spending 3% of capital.
- **Low-VIX long straddle:** when India VIX is in the bottom quarter of its last 60 and 120 sessions, buy one lot of the at-the-money call and put (the nearest monthly expiry with at least 20 sessions left); sell at 1.5x or 0.5x the cost, or with 5 sessions left. One lot ties up 40–60% of the agent's money, so its swings are large.

Futures and option selling use 3x the agent's capital. Costs include brokerage, exchange charges, GST, stamp duty, slippage and STT at the rates in force on each date.

Each night `fno_prices.py` downloads NSE's daily F&O price file and saves the Nifty options the agents need to `data/fno/`, so option trades use real opening and closing prices. If NSE can't be reached, that day uses estimated prices; a day is written to the permanent logs only once its prices are final, so saved results never change. Futures trades use the Nifty 50 index itself, and intraday stop-losses are judged from the day's high and low.

`python fno_backtest.py` runs the same strategies from February 2019, when weekly Nifty options began. Free data has no past option prices, so the backtest estimates them from India VIX and shows how much results change with that estimate. Treat option results as a rough guide; the paper trading with real prices is the real test.

In SEBI's study of FY26, 87.7% of individual F&O traders lost money. Nothing here is a recommendation to trade F&O.

## Gold and multi-asset arena

Six agents built from research into the Trade Like Berlin YouTube channel and strategies shared on Reddit and X. Each has ₹1 lakh of virtual money from the first trading day after its files reach the repository, and trades instruments an Indian resident can legally use:

- **Gold breakout:** buy GOLDBEES on a close above its highest close of the previous 55 sessions; sell to cash on a close below the lowest of the previous 20.
- **Nifty-gold switch:** always hold NIFTYBEES or GOLDBEES, switching to whichever wins a 20-session breakout of their price ratio.
- **Gold/silver reversion:** hold GOLDBEES; switch to SILVERBEES when the gold/silver ratio is 2 standard deviations above its 100-session average, and back at the average.
- **Gold/silver trend:** hold GOLDBEES after the gold/silver ratio breaks above its 20-session high, SILVERBEES after it breaks below its 20-session low.
- **Gold breakdown short (control):** the channel's own gold trade with a stop added. Short gold through MCX Gold Petal futures when COMEX gold closes below its lowest low of the previous 55 sessions; buy back after a 10% fall or a close above the highest close of the previous 20.
- **3-day rule + US filter (control):** the channel's overnight rule, traded at the next close. Buy NIFTYBEES when Nifty closes above the previous 3 days' high and its 10-day average while the S&P 500 is up over 3 sessions; sell when Nifty closes below the previous 3 days' low.

Every rule acts at the close after its signal, like the other agents. Signals that use US markets only see US sessions that ended before India's close that day. ETF trades cost 0.05% a buy or sell; Gold Petal 0.05% plus a monthly roll. Idle cash earns 6%.

`market_data.py` downloads the prices from Yahoo Finance's public data each night and saves them in `data/market/`, so a failed download never loses history. `python asset_backtest.py` backtests every agent against the benchmark the research set for it, in both halves of the period, at double costs and with its variant settings; add `--nav` to fall back to daily ETF NAVs where no saved prices exist. In a backtest on ETF NAVs from 2007 to Sep 2026, none of the six passed its bar: the gold breakout trailed simply holding gold (11.1% a year against 14.2%) with only a slightly smaller worst fall, the Nifty-gold switch matched a 50/50 mix, and both channel rules did worse than cash. They paper-trade anyway, so you can watch whether that holds.

## Start dates

The original Nifty agents started on 23 Oct 2026. Newer agents get their start date from `logs/starts.json`, which the nightly run writes the first time it sees each agent: the next weekday. It is written once and never changed, so a late upload can never backdate an agent.

## When a data source misses a day

The free index dataset sometimes skips a day's update. The arena then adds Yahoo Finance's closing prices for the missing days, so the agents keep up.

## Permanent logs

Every run adds the newest days to two logs and commits them to the repository:

- `logs/daily.csv`: one row per agent per day, with its holding, value, return since start and any trade.
- `logs/trades.csv`: every trade, with Nifty 50's close that day.

Each group of agents is logged once its prices for the day are final: the Nifty agents when the close is in, the F&O agents once NSE's option prices are saved (or after two days of trying), and the gold and multi-asset agents once every ETF price is in. Rows for different groups can therefore arrive on different nights. Old rows are never rewritten, so past results can't quietly change. If a later replay of the arena disagrees with the saved rows, for example because the data source corrected an old price, the page shows a warning, and the saved log stays the official record.

Each Claude decision also gets a file in `decisions/snapshots/` with the data it was based on. Write your own evening notes in `logs/journal.md`; it has a short template.

## Breadth and institutional flows

The page also shows how many Nifty 50 stocks are above their 200-day and 50-day averages, with a one-year chart, plus the day's net FII and DII cash-market flows. Claude sees the same numbers before each decision.

Update `nifty50.txt` after each Nifty 50 rebalance (changes take effect on the last working day of March and September). NSE Indices publishes the list on niftyindices.com.

## Let Claude decide automatically (optional)

After each weekday close, Claude looks at the latest prices and indicators, breadth and flows, every rule agent's signal, its own past decisions and the day's market news. It then picks 0, half or all in Nifty 50, with its reasons and the levels that would make it change its mind. The decision is saved in `decisions/claude.json` and filled at the next close.

Choose one of the two options below, not both. If you use neither, message Claude in chat for a "Claude agent update" and paste the updated `claude.json` yourself.

### Option A: a Claude Code routine (uses a Claude plan, no API key)

You need a **personal** Claude account on the Pro plan or higher, with Claude Code on the web turned on. Don't use a work account.

1. Open claude.ai/code/routines and create a new routine.
2. Add your `paper-arena` repository, and connect GitHub if asked.
3. Prompt: `Use the claude-agent-decision skill in this repository to make today's Claude agent decision, then push it to main.`
4. Setup script: `pip install -r requirements.txt`
5. Schedule: every weekday at 9:00 pm IST, after the free price data updates at about 7:30 pm.
6. In the routine's repository settings, turn on **Allow unrestricted branch pushes**. Without it, routines can only push to branches starting with `claude/`, and the decision wouldn't reach the page.
7. Save it, then run it once by hand to check that a decision appears in `decisions/claude.json`.

Routine runs count toward your plan's usage, and the Pro plan allows a limited number of routine runs per day; one a day is well within it. If a run can't download the price data, check the network access setting of the routine's environment.

### Option B: the Claude API (paid per use)

1. Create an account with your personal email at console.anthropic.com, add a payment method, and create an API key.
2. In the Console's privacy settings, turn on web search so Claude can read the news. If you'd rather skip news, set `MAX_SEARCHES = 0` in `claude_agent.py`.
3. In your GitHub repository, go to **Settings → Secrets and variables → Actions → New repository secret**. Name it `ANTHROPIC_API_KEY`, paste the key, and click **Add secret**.

That's all. The next evening run makes the first automatic decision.

- **Cost:** one Claude call and up to 3 web searches per evening. At current prices (Claude Sonnet 5.5 at $2 per million input tokens and $10 per million output tokens, and web search at $10 per 1,000 searches) that's roughly $2–3 a month. You can see your usage in the Console.
- **Guardrails:** Claude only decides between a close and the next market open, can only choose 0, 0.5 or 1, and never touches real money. If the call fails, Claude keeps its last position.
- **To stop:** delete the secret.

## Use Claude Code for your backtests

Open this repository in Claude Code and ask, for example, "Review my latest backtest results with the backtest-review skill." The skill checks the hidden years, costs, timing, fragility and sample size, and tells you what to rerun.

For deeper backtests with Indian costs and a Nifty benchmark, you can also add marketcalls' VectorBT skills to the project. This needs Node.js; some features also need TA-Lib or OpenAlgo:

```bash
npx skills add marketcalls/vectorbt-backtesting-skills
```

## Add your own call

1. Open `paper_arena.py` on GitHub and click the pencil icon.
2. Under `"Me"` in `MANUAL_AGENTS`, add a line such as `"2026-10-26": 1.0,` using that evening's date. 0 means all cash, 0.5 means half in Nifty, 1 means fully in Nifty.
3. Click **Commit changes**. The page rebuilds within a few minutes.

Never add a call with a past date, and never change an agent's rule after the start. Both would use hindsight. To test an improved rule, add it as a new agent instead.

## Good to know

- **The page is public.** On GitHub's free plan, Pages sites are public, so anyone with the link can see it. Keep only virtual trades here, nothing personal or work-related.
- **Keep it active.** If the repository has no activity for 60 days, GitHub pauses the daily run. The nightly log commits count as activity, and you can turn the run back on from the **Actions** tab if it ever stops.
- **Keep `START` fixed** once paper trading begins.
- **Running it yourself:** `pip install -r requirements.txt`, then `python build_site.py`, and open `site/index.html`. You can also run `paper_arena.py` or `nifty_backtest.py` on their own, or paste them into Google Colab.
- **Data:** free daily index data from [indian-market-historical-data](https://github.com/aswinv90/indian-market-historical-data), licensed for personal, non-commercial use.
