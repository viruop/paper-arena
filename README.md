# Paper arena

Rule-following agents, Claude, F&O strategies, gold and multi-asset agents, the Trade Like Berlin channel's strategies and the calls of two Telegram channels each trade ₹1 lakh of virtual money, and one web page shows which of them make money. GitHub runs everything every weekday evening.

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
| `asset_arena.py` | Six gold and multi-asset agents (two of them the Trade Like Berlin channel's rules): gold, silver and Nifty ETFs, and MCX gold futures |
| `berlin.py` | The Trade Like Berlin videos being tested: claim, changes and the name each trades under |
| `berlin_calls.py` | Paper trades Trade Like Berlin's Telegram calls, his options trades on the market itself, and each call 15 and 30 minutes late and reversed |
| `channels.py` | The Telegram channels: saves every channel's posts every 30 minutes (to add a channel, add it here) |
| `voice_notes.py` | Turns the channels' voice notes into English text every 30 minutes, with Whisper, a free open-source speech model |
| `signal_calls.py` | Reads a signal channel's posts into signals by fixed rules, and paper trades them on one-minute prices |
| `dukascopy.py` | Downloads one-minute bid and ask prices for gold, forex, indices and Bitcoin from Dukascopy's free data feed |
| `scorecard.py` | "Worth following?": the same ten checks for every channel, written down on 4 Nov 2026 |
| `berlin_study.py` | Checks the forex video's claim on every RBNZ rate decision since 1999 |
| `data/berlin/` | Trade Like Berlin's Telegram archive, the tagged calls, his later posts about them, corrections, the decision log, the posts he deleted and his voice notes as text |
| `data/akash/` | Trade with Akash Garg's Telegram archive, the signals read from it, his later posts, the decision log, corrections, the posts he deleted and his voice notes as text |
| `data/dukascopy_check.json` | Whether last night's check could read Dukascopy's one-minute prices (added automatically) |
| `asset_backtest.py` | Backtests the gold and multi-asset agents against their benchmarks |
| `market_data.py` | Downloads and saves daily ETF, gold, silver, S&P 500, Brent crude and dollar-rupee prices |
| `data/market/` | The saved prices (added automatically) |
| `starts.py` | Gives each newer agent its start date the first night it's seen |
| `logs/` | `daily.csv`, `trades.csv` and `starts.json` (added automatically) and your `journal.md` |
| `market_context.py` | Nifty 50 breadth and FII/DII flows, for the page and for Claude |
| `events.py` | Market events: what's scheduled, what happened and how markets moved around it, for the page and for Claude |
| `data/events/` | The event calendar (`calendar.csv`) and the log of what happened (`log.csv`), added to by Claude each night |
| `nifty50.txt` | The current Nifty 50 list, used for breadth |
| `CLAUDE.md` and `.claude/skills/` | Notes and skills that Claude Code and routines read |
| `REAL_MONEY.md` | The gap register: everything that is fine for paper trading but not for real money, and the order to fix it in |
| `nifty_backtest.py` | The backtest of the same rules from 2010 to today |
| `build_site.py` | Builds the web page into a `site` folder |
| `requirements.txt` | The Python packages GitHub installs |
| `.github/workflows/arena.yml` | Runs everything each weekday evening and publishes the page |
| `.github/workflows/telegram.yml` | Saves new posts from every Telegram channel every 30 minutes, reads the signal channel's new signals and transcribes new voice notes |

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

Nothing, apart from Claude's decision if you make it in chat (say "Claude agent update"). The page updates on weekdays at about 8:45 pm IST, with a backup run at about 10:15 pm. The runs are set a few minutes off the hour because GitHub often starts runs set for the hour hours late.

The page starts with **Every strategy**: one board with each strategy's value and return since it started, grouped by arena. Below it are Claude's latest call, **Market events** and the Trade Like Berlin section; everything else (rules, charts, trades, backtests, logs) is folded under **Details**.

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

Each night `fno_prices.py` tries to download NSE's daily F&O price file and save the Nifty options the agents need to `data/fno/`, so option trades use real opening and closing prices. If NSE can't be reached (it often blocks cloud servers), that day uses prices estimated from India VIX, and it's logged only after 10 pm, so a run started by an upload during the day can't lock in estimates before NSE has published its file. Either way the agents log every night, like the other agents, and a logged day never changes. The page says how many days used real prices. Futures trades use the Nifty 50 index itself, and intraday stop-losses are judged from the day's high and low.

`python fno_backtest.py` runs the same strategies from February 2019, when weekly Nifty options began. Free data has no past option prices, so the backtest estimates them from India VIX and shows how much results change with that estimate. Treat option results as a rough guide; the paper trading with real prices is the real test.

In SEBI's study of FY26, 87.7% of individual F&O traders lost money. Nothing here is a recommendation to trade F&O.

## Trade Like Berlin

The page has a section for the [Trade Like Berlin](https://www.youtube.com/@tradelikeberlin_) YouTube channel and its [Telegram channel](https://t.me/tradelikeberlin). Each video gets a card: the claim, what had to change to test it legally and mechanically, where it stands, and whether the claim holds.

- **Gold breakdown short** ("GOLD IS PREPARING FOR SOMETHING BIG", 22 Oct 2026), traded as the agent "Gold breakdown short (control)": short gold through MCX Gold Petal futures when COMEX gold closes below its lowest low of the previous 55 sessions; buy back after a 10% fall or a close above the highest close of the previous 20. The video gives no stop, so one is added.
- **3-day rule** ("BTST TRADE RULES", 26 Oct 2025), traded as "3-day rule + US filter (control)": buy NIFTYBEES when Nifty closes above the previous 3 days' high and its 10-day average while the S&P 500 is up over 3 sessions; sell when Nifty closes below the previous 3 days' low.
- **Forex news-event plan** ("THE FOREX TRADE OPPORTUNITY", 25 Oct 2026): trade a rate decision in the direction of the last 4-5 days, with a two-sided hedge. Offshore forex isn't legal for Indian residents, so this is only ever paper traded: each event he announces is traded on 5-minute prices with the video's stops and targets. `berlin_study.py` also checks the direction claim ("6 out of 10") on 209 RBNZ decisions since 1999: the move followed the last 5 days 50% of the time, no better than ordinary days, though decision days do move about twice as much.

**Telegram.** Every 30 minutes, day and night, a small workflow (`.github/workflows/telegram.yml`) saves every new post from his public channel to `data/berlin/telegram_posts.csv`, with the time Telegram shows. A post he edits later is saved again, so the record can't be rewritten. A post he deletes after it was saved stays in the archive and is listed in `telegram_deleted.csv` (the newest posts are checked on every run, all of them once a day); a deleted call is marked on the page. His voice notes are turned into English text by the same workflow (`voice_notes.py`, usually within the hour): Whisper small, a free open-source speech model, runs on GitHub's machine and translates his Hindi into `data/berlin/voice_notes.csv`, so the nightly review reads a voice note like any other post. A machine transcript can mishear a number, so a level is taken from one only when it's clear, and the call's note says it came from a voice note. A scheduled Claude task reads the new posts at 11:07 pm on weekdays and sends you the files to upload (ask Claude any time: "Berlin Telegram update"):

- `telegram_calls.csv`: posts that tell followers to take a position, or say he has taken one, tagged as calls.
- `telegram_updates.csv`: his later posts about a call. An exit post ends the call, and a stop move ("cover my shorts at 4047$", "move to cost") applies from the post's time. "Target achieved" or "SL hit" claims are checked against the record and marked as matching it or not. Claims never change a score.
- `telegram_reviewed.csv`: the decision log, one line per post Claude read: call, update, claim or other, and why.

Every call is paper traded by fixed rules: it risks ₹1,000, fills at the next 5-minute bar after the post (or when price crosses his level), and uses his stop and target. Markets: Nifty, gold (COMEX futures), Bitcoin, crude oil (NYMEX WTI futures) and currency pairs; his gold and crude levels are quoted on spot or CFD charts, so they're moved onto futures by the gap at a price he quoted. A call is scored only once Claude has reviewed every post he made before it ended (the decision log), so a later exit or stop move can't be missed: a score is never redone. A missing stop is set at 0.2% for Nifty or 1.5% for gold, and said so. Results go to `logs/berlin_calls.csv` and are never rewritten. Each call is also traded 15 and 30 minutes late (aiming at the same target) and reversed, in `logs/berlin_variants.csv`: if a call only works for someone who acts the same minute, or works just as well the other way, its levels carry no edge. Option-premium trades can't be priced with free data, so when he gives a direction, they're scored on the market itself (Nifty or gold) in a separate book. Levels drawn only on chart images aren't scored. If we misread a call, a note goes in `data/berlin/call_corrections.csv`, and the page shows it under the call; the score stays as tagged.

**New strategy video?** Send Claude the link. The steps are in `.claude/skills/berlin-new-video/SKILL.md`: a new agent with a new name and an entry in `berlin.py`. Existing agents never change.

## Trade with Akash Garg (a signal channel)

[Trade with Akash Garg](https://t.me/tradewithakashgarg) posts gold, Nasdaq 100 and Bitcoin signals with exact levels, such as "GOLD BUY NOW / STOPS :- 3990.6 / TARGET :- 3997.209". Because the format is regular, plain code reads them, so no AI and no uploads are needed for the normal case:

1. Every 30 minutes the Telegram workflow saves his new posts to `data/akash/telegram_posts.csv`, starting with the newest post on 4 Nov 2026. Older posts are never added: he could have deleted his losing calls before then.
2. `signal_calls.py` reads each post once it is 10 minutes old (so a stop and target posted a minute after the signal belong to it) and writes one line per post to the decision log `data/akash/telegram_reviewed.csv`. Signals go to `telegram_calls.csv`, his later instructions ("move to breakeven", "closing full") and claims ("TP done", "SL HIT") to `telegram_updates.csv`. A trade post without a clear stop and target, an instruction that can't be tied to one signal, or a voice note (its English transcript goes to `data/akash/voice_notes.csv`) is marked "needs review" and never guessed.
3. Each night, once a signal's 24 hours are over, it is paper traded on Dukascopy's one-minute bid and ask prices. A "now" signal fills at the next minute's price (the ask for a buy, the bid for a sell); limit and stop orders fill when the price reaches his level. Each signal risks ₹1,000, split equally over his targets. If one minute touches both his stop and a target, the stop counts. A breakeven move puts the stop at the entry from the minute after he posts it; an exit closes what's left. Results go to `logs/akash_calls.csv`, and the late and reversed checks to `logs/akash_variants.csv`.
4. The nightly Claude task reads the posts marked "needs review" and sends its answers as `claude_calls.csv`, `claude_updates.csv` and `claude_reviewed.csv` for `data/akash/`. These are separate files because the 30-minute workflow keeps adding to the others: uploading over them could wipe rows it added in the meantime. A signal with a "needs review" post inside its 24 hours waits for that answer before it's scored. The task also checks each new signal the code read against its post, and notes any misreading in `data/akash/call_corrections.csv`; the page shows it under the signal, and the score stays as read.
5. Each night the arena reads one hour of gold from Dukascopy and writes whether it worked to `data/dukascopy_check.json`; the page says if the price feed is down, and finished signals wait for it.

His "TP done" and "SL HIT" posts are checked against the record. His results posts about trades that were never posted in the channel ("Inner circle report", "VIP profits") can't be checked and are only counted. Trading forex or gold CFDs through offshore brokers isn't permitted for Indian residents, so these signals are only ever paper traded here.

## Worth following?

Each channel is judged by the same ten checks, written down on 4 Nov 2026 (`scorecard.py`) and never changed, so the bar can't move to fit the results:

1. **Enough calls:** at least 40 scored. Until then the page says "too early to judge".
2. **Makes money after costs**, at ₹1,000 risk per call.
3. **In both halves:** the first and second half of its calls each make money.
4. **Not two lucky calls:** still in profit without its two best calls.
5. **Survives a 15-minute delay:** still in profit when every call is taken 15 minutes late.
6. **His direction matters:** the same trades reversed do worse.
7. **Enough calls can be checked:** at least 60% of his trade calls have levels free data can score.
8. **His claims match the record:** at least 80% of his checkable "target hit" or "SL hit" posts agree with it.
9. **Not luck:** a channel with no edge would make this much profit less than 1 time in 20 (needs at least 20 calls). In a simulation of 4,000 channels with no edge, about 1 in 8 passed checks 2–6 after 40 calls; with this check, about 1 in 30.
10. **His calls stay up:** none of his calls was deleted from the channel after it was saved here.

A scheduled Claude task sends you each channel's checks every Saturday morning.

## Gold and multi-asset arena

Six agents built from research into the Trade Like Berlin YouTube channel and strategies shared on Reddit and X. Each has ₹1 lakh of virtual money from the first trading day after its files reach the repository, and trades instruments an Indian resident can legally use:

- **Gold breakout:** buy GOLDBEES on a close above its highest close of the previous 55 sessions; sell to cash on a close below the lowest of the previous 20.
- **Nifty-gold switch:** always hold NIFTYBEES or GOLDBEES, switching to whichever wins a 20-session breakout of their price ratio.
- **Gold/silver reversion:** hold GOLDBEES; switch to SILVERBEES when the gold/silver ratio is 2 standard deviations above its 100-session average, and back at the average.
- **Gold/silver trend:** hold GOLDBEES after the gold/silver ratio breaks above its 20-session high, SILVERBEES after it breaks below its 20-session low.
- **Gold breakdown short (control):** the channel's own gold trade with a stop added. Short gold through MCX Gold Petal futures when COMEX gold closes below its lowest low of the previous 55 sessions; buy back after a 10% fall or a close above the highest close of the previous 20.
- **3-day rule + US filter (control):** the channel's overnight rule, traded at the next close. Buy NIFTYBEES when Nifty closes above the previous 3 days' high and its 10-day average while the S&P 500 is up over 3 sessions; sell when Nifty closes below the previous 3 days' low.

Every rule acts at the close after its signal, like the other agents. Signals that use US markets only see US sessions that ended before India's close that day. ETF trades cost 0.05% a buy or sell; Gold Petal 0.05% plus a monthly roll. Idle cash earns 6%.

`market_data.py` downloads the prices from Yahoo Finance's public data each night and saves them in `data/market/`, so a failed download never loses history. `python asset_backtest.py` backtests every agent against the benchmark the research set for it, in both halves of the period, at double costs and with its variant settings; add `--nav` to fall back to daily ETF NAVs where no saved prices exist. On Yahoo's daily prices from 2009, none of the six passes its bar: the gold breakout trailed simply holding gold (10.6% a year against 13.0%), the Nifty-gold switch lost to a 50/50 mix in the first half, and both channel rules did worse than cash. They paper-trade anyway, so you can watch whether that holds.

## Start dates

The original Nifty agents started on 23 Oct 2026. Newer agents get their start date from `logs/starts.json`, which the nightly run writes the first time it sees each agent: the next weekday. It is written once and never changed, so a late upload can never backdate an agent.

## When a data source misses a day

The free index dataset sometimes skips a day's update. The arena then adds Yahoo Finance's closing prices for the missing days, so the agents keep up.

## Permanent logs

Every run adds the newest days to two logs and commits them to the repository:

- `logs/daily.csv`: one row per agent per day, with its holding, value, return since start and any trade.
- `logs/trades.csv`: every trade, with Nifty 50's close that day.

Each group of agents is logged once its prices for the day are final: the Nifty agents when the close is in, the F&O agents the same night, and the gold and multi-asset agents once every ETF price is in. Rows for different groups can therefore arrive on different nights. Old rows are never rewritten, so past results can't quietly change. If a later replay of the arena disagrees with the saved rows, for example because the data source corrected an old price, the page shows a warning, and the saved log stays the official record.

Each Claude decision also gets a file in `decisions/snapshots/` with the data it was based on. Write your own evening notes in `logs/journal.md`; it has a short template.

## Breadth and institutional flows

The page also shows how many Nifty 50 stocks are above their 200-day and 50-day averages, with a one-year chart, plus the day's net FII and DII cash-market flows. Claude sees the same numbers before each decision.

Update `nifty50.txt` after each Nifty 50 rebalance (changes take effect on the last working day of March and September). NSE Indices publishes the list on niftyindices.com.

## Market events

Markets move on events: a rate decision, a jobs report, or a surprise such as the US midterm result that sent Brent down about 9% and Nifty up 2.4% in early November 2026. Two files keep track of them, and both are only ever added to:

- `data/events/calendar.csv`: what's scheduled, with the time in IST and a link to the source. It covers RBI and Fed decisions, US jobs and inflation reports, India's inflation and GDP figures, the Budget, elections, and NSE holidays and special sessions such as Diwali's Muhurat trading.
- `data/events/log.csv`: what happened, scheduled or not, with the time it first became public and a link. A correction is a new row with the same id; nothing is edited or deleted.

The Telegram scheduled task adds to both every weekday night, using Claude's web search (the `market-events` skill). The page's **Market events** section lists the next two weeks and the last 45 days, with how Nifty, gold, Brent, the rupee and the S&P 500 moved from their last close before each event to their first close after it. One event proves little, since other news on the same day is mixed in; over months, the log shows which kinds of events really move Nifty. Claude sees the same list before each decision, but only the rows that existed when it decided, and the exchange holidays and special sessions in the calendar decide when its decision window closes. Check the files with `python events.py --check`.

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
- **Data:** free daily index data from [indian-market-historical-data](https://github.com/aswinv90/indian-market-historical-data), licensed for personal, non-commercial use. ETF, gold, silver, S&P 500 and 5-minute prices come from Yahoo Finance's public data, and the signal channel's one-minute prices from Dukascopy's free data feed, both for personal use.
