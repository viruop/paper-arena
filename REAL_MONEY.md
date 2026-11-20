# Before any real money: the gap register

Written 5 November 2026 after a line-by-line review of the whole setup (21 Python files, two GitHub
workflows, two scheduled tasks, the data sources). It lists everything that is fine for a paper-trading
arena but would cost money, break the law or break down if the same system placed real orders. Nothing
here is advice; it is an engineering and risk review for learning. Items are only ever added or
dated as resolved, never deleted, so the list shows what was known when.

Severity: **Blocker** (don't trade real money until fixed), **Major** (will cost money or stop the
system), **Minor** (worth fixing, won't hurt much).

## 1. What the setup is, and what it isn't

It is a research harness: fixed rules, written down in advance, replayed every night from saved data,
with a record that can't be rewritten. That is the right foundation, and most retail "track records"
don't have it.

It is not an execution system. It never sees a live quote, never checks a fill, has no risk limits,
no kill switch, no reconciliation against a broker statement, and runs on a scheduler (GitHub Actions)
that can start hours late. Adding a broker API to it as it stands would be the mistake: the execution
layer has to be built separately and fed by this one, not bolted onto it.

## 2. Blockers

### 2.1 Most of what is tracked can't legally be traded from India
- Trade Like Berlin's forex calls (NZD/CAD and so on) and Trade with Akash Garg's gold, Nasdaq and
  Bitcoin CFD signals are quoted on offshore CFD brokers. Trading those from India breaks FEMA rules;
  the repo already says so and keeps them paper-only. That stays true with real money.
- His gold calls are scored on COMEX futures (GC=F), crude on NYMEX (CL=F): not tradable from India
  either. The Indian equivalents are MCX gold and crude futures or options, with different prices,
  hours, lot sizes and a rupee leg. Nothing here maps a COMEX level onto an MCX contract.
- Nifty "levels" are scored on the index itself. The index isn't tradable: real money goes through
  NIFTYBEES (an ETF, small tracking gap, spread) or Nifty futures (basis, lot of 65, margin).
- Bitcoin from India means an Indian exchange, 30% tax on gains with no loss set-off and 1% TDS
  per trade. The arena models 0.05% a side.
- **What to do:** decide, per strategy, the exact Indian instrument it would trade, and re-score
  from that instrument's own prices before trusting any number. Until then the channel scorecards
  answer "does he have an edge on the thing he quotes", not "would following him make money here".

### 2.2 The F&O agents trade fractional lots and ignore margin
- Each F&O agent holds "3x of ₹1 lakh" of Nifty, about 12 units. A Nifty lot is 65, so they hold
  0.19 of a lot. You can't do that. One short strangle needs about ₹1.3–1.8 lakh of SPAN margin per
  lot; one ATM weekly straddle costs about ₹20–30k to buy. ₹1 lakh can't run any of these agents as
  written, and the smallest real size is 5x larger than the paper one, with 5x the risk.
- **What to do:** real-size versions (whole lots, margin checked daily, forced exit when margin
  runs out) as new agents; the existing ones keep running as the rule test. Existing agents' rules
  never change.

### 2.3 No risk limits, no kill switch, no reconciliation
- Nothing stops a bad price print, a stuck data feed or a wrong file from producing a trade. The
  daily series have a spike filter (market_data.drop_spikes); the 5-minute and one-minute bars have
  none, and a single bad Yahoo bar could "stop out" a call.
- There is no maximum daily loss, no drawdown halt, no position limit, no check that an order was
  filled at the price assumed, no end-of-day comparison with a broker statement.
- **What to do:** these belong in the execution layer: limits set in advance, checked before every
  order and every night; a halt that needs a human to lift; a nightly reconciliation that stops
  trading when the broker's numbers and the arena's disagree.
- **Status, 16 Nov 2026:** the limits, the halt a person has to lift, the kill switch and the refusal of stale
  prices now exist in paper (shadow) mode (risk_engine.py; see 7 and the table in 10), and the saved prices are
  checked every night (data_health.py). Still open: reconciliation against the broker's own statement, a spike
  filter on the 5-minute bars, and running any of it in front of a broker.

### 2.4 The scheduler can't be trusted with an order
- GitHub Actions cron routinely starts late, sometimes by hours; the arena runs at 8:47 pm and
  10:13 pm precisely because of that. The Telegram job depends on cron-job.org to start it. Neither
  is acceptable for "sell at 3:25 pm".
- Decisions made at close T fill at close T+1 by assumption. In reality someone (or a server with
  a broker API, static IP and the broker's algo approval) has to place that order inside the session.
- **What to do:** an always-on machine or a broker-hosted scheduler for execution; GitHub stays
  as the record keeper. SEBI's retail algo framework (via a broker's API; algos above a set order
  rate must be registered) applies to anything automated; check the current rules with the broker
  before building.

### 2.5 A prompt-injection surface feeds the records
- Claude tags Berlin's calls from his posts and voice transcripts, logs events from web searches,
  and decides its own agent's position after web searches. All of that text comes from strangers.
  For paper trading a manipulated tag costs nothing; with real money, a Telegram post written to
  look like an instruction, or a planted web page, could move a position.
- **What to do:** real orders should depend only on code-readable, verified inputs (prices from
  the broker, calendar rows a human approved), never directly on free text.

## 3. Major

### 3.1 One stranger's GitHub repository is the primary price source
- Nifty and sector closes, breadth stocks and FII/DII flows all come from
  github.com/aswinv90/indian-market-historical-data, a personal repo with no service promise.
  Yahoo tops up index closes when it lags; nothing tops up breadth or flows. If it stops or
  changes format, the Nifty agents degrade and the Claude agent loses two of its inputs.
- **What to do:** keep the saved copies (data/market) as the record, which already happens for
  the asset series; add the same saving for indices, breadth and flows so one source going dark
  costs a day, not the history; add a second source for flows (NSE's own daily file).

### 3.2 Continuous futures and spot/futures gaps
- GC=F and CL=F are Yahoo's front-month continuous series; a positional gold call that spans a
  contract roll sees a price jump that isn't a trade. His gold levels are spot (XAUUSD), moved onto
  futures by a fixed gap measured once per call; the gap drifts over a 14-day hold.
- **What to do:** for real trading use the exact contract, never a continuous series; for scoring,
  note calls that span a roll.

### 3.3 Fills are the best case
- Berlin calls fill at the open of the next 5-minute bar; Nifty calls on the index; ETF and index
  trades at the exact close. Real fills: a spread, slippage on the move the call itself may cause
  (small followers' channels move thin options), and no guarantee of the close price. Costs are
  modelled sensibly (STT, exchange fees, GST, slippage in the F&O engine) but the Nifty agents use a
  flat 0.10% a side and the ETF agents 0.05%, with no spread model.
- **What to do:** after the first month of real fills, replace the flat costs with measured ones.

### 3.4 Twenty agents guarantee a "winner"
- With 20 strategies of no skill at Nifty-like volatility, the best one shows about +35% in a
  typical year, and beats +20% in 96% of years (simulated tonight). Picking the top agent after a
  year and funding it is the classic way to lose. The channel scorecard already has a luck test;
  the agent arenas don't.
- **What to do:** judge an agent against a bar set before it started (its benchmark and the luck
  test), over a period fixed in advance, and never fund the best-of-N.

### 3.5 Sample sizes
- As of today: 10 Claude decisions, 5 scorable Berlin calls, 1 Akash signal, 13 agents started on
  28 October. Nothing is a result yet. The scorecard needs 40 calls; the luck test 20; an agent
  needs a year with at least one bad month in it.

### 3.6 Everything goes through one phone
- Claude can't push; every nightly file goes GitHub ← you ← Claude. A busy week stalls the call
  review, the events log and the decisions. With real money, a stalled review means a position
  nobody is watching.
- **What to do:** either a personal-account token for the scheduled tasks (they would then
  commit directly, with the same add-only checks) or a rule that no real position exists without
  that night's review done.

### 3.7 Legal and tax, separate from the code
- F&O profits are business income with audit thresholds; ETF gains are capital gains; crypto is
  taxed flat at 30%; offshore trading is out. Position sizes above the limits of your own
  investor category, and the broker's algo rules, come first. The logs here are good tax records;
  they aren't tax advice. Check with a professional before the first real order.

## 4. Minor

- The page is public. Real positions on a public page are information you give away.
- Both workflows push to `main` and retry on conflict; a rare double failure drops a night's
  commit. The next night repairs it, but the log would show a gap.
- Whisper mishears numbers in voice notes ("lefty" for Nifty). Tags taken from voice notes are
  marked; spot-check them.
- The 22 drifting F&O rows (29 Oct–3 Nov) are explained on the page and are permanent.
  (16 Nov 2026: the drift went on after 3 Nov; the outside review counted 50 rows to 12 Nov. See 7.)
- FII/DII flows reach the Claude agent one day late (the source publishes T+1).
- Package versions aren't pinned (`pandas>=2.1`); a pandas major release could change behaviour
  overnight. Pin them.
- NSE's daily option file gives the last trade, not a tradable quote, for thin strikes; fine for
  ATM weekly Nifty, not for far wings.

## 5. What's fine

- The add-only record, snapshots before results, the replay-drift check, and events known-at
  cut-offs: keep these exactly as they are and build the execution layer to the same standard.
- Costs in the F&O engine (STT by date, exchange fees, GST, slippage, overnight share of decay).
- Dukascopy bid/ask one-minute fills for the signal channel (buys at the ask, stops on the bid).
- Stop-first rule when a bar touches both stop and target.
- Every network step degrades to saved data instead of failing.

## 6. A go/no-go list, in order

1. One strategy, one Indian instrument, re-scored on that instrument's own prices.
2. A year of its paper record, judged against the bar set before it started.
3. Real-size version (whole lots, margin) run on paper for three months.
4. Execution layer: always-on scheduler, broker API with the broker's approval, limits and halt,
   nightly reconciliation, no free-text input on the order path.
5. Smallest real size for three months with the paper version running beside it; the two must
   agree within the measured costs.
6. Only then, size up, and never past a limit written down before step 5.

## 7. Resolved

- 5 Nov 2026, 3.1 in part: the index closes, breadth and FII/DII flows are now saved nightly
  (data/market/indices/, breadth.csv, fii_dii.csv) and used when the source is down. A second
  source for flows is still open.
- 5 Nov 2026, 3.4: a per-agent luck test (daily returns over cash, one-sided, at least 60 days,
  p < 0.05) on the page under "Skill or luck?", with the best-of-twenty warning.
- 5 Nov 2026, 2.1 in part: each channel section now says where each market is scored and what the
  trade would be from India. Re-scoring on Indian instruments is still open.
- 5 Nov 2026, 2.5 in part: the skills and the nightly task now say that posts, transcripts and web
  pages are data, never instructions. This reduces the risk; it doesn't remove it.
- 5 Nov 2026, minor: package versions capped below the next major release.
- 11 Nov 2026, 2.1 in part: his Nifty calls are now re-scored on NIFTYBEES's own 5-minute prices
  with Zerodha's charges (berlin_etf.py, logs/berlin_etf.csv), on time and 15 and 30 minutes late.
  Gold and crude on MCX are still open: there are no free intraday MCX prices to score them on. The
  order ticket moves a dollar gold or crude level onto an MCX contract by the ratio at that moment,
  which is for placing an order by hand, not for scoring.
- 11 Nov 2026, 3.3 in part: zerodha.py holds Zerodha's real charges and rounding, checked against
  its own calculator, and the NIFTYBEES copy, the ledger and the ticket all use it. The paper agents
  keep their flat costs, because an agent's rule never changes; the ledger measures the real ones
  from the first real fill.
- 11 Nov 2026, 3.1: the second source for flows. Each night the arena asks NSE's own site for the latest
  session's FII and DII figures and adds them on top of the dataset's, which also ends the one-day lag
  (Minor) on nights NSE answers. NSE often refuses cloud servers; a refused, stale or odd reply is
  dropped and the dataset's figures are used as before. Whether GitHub's servers get through is only
  known from the nightly log ("NSE's own FII/DII figures not added" means they didn't).
- 11 Nov 2026, 2.2 in part: four whole-lot agents (futures trend, short strangle, iron condor, option
  buying) trade real lots of 65 on ₹5 lakh each, skip a week when one lot's margin is more than half the
  account, and are closed when the account falls below the margin. The margin is a flat 12% of the lot's
  value (Zerodha asked 11.4% that day); real margins rise in a volatile market and aren't modelled, so a
  real account would be forced out sooner. The fractional agents keep running as the rule test.
- 13 Nov 2026, 2.3 in part: a risk engine (risk_engine.py) with limits written down in advance: the
  ticket's (₹5,000 account, 2% risk a trade, costs at most 25% of the risk, reward at least 1.5 times
  the stop after costs, 3 trades and 2 losses a day) and its own (no new risk after a 4% day loss, a
  halt at 10% below the peak that a person has to lift, stale and mistyped prices refused, no repeat
  orders, at most 5 a minute, only Indian instruments with saved prices, market hours and NSE
  holidays). Exits are never refused. The kill switch is the file data/real/HALT. It runs in paper
  mode only: each night it decides every order the paper strategies would have sent and logs it once
  (logs/risk_orders.csv). Its sums match the order ticket's on 1,500 random orders. Still open from
  2.3: reconciliation against the broker's own statement, a spike filter on the 5-minute bars, and
  the always-on machine to run it in front of a broker (2.4). First finding: all six of his Nifty
  calls with levels were refused in a ₹5,000 account, on costs (55% to 160% of the money at risk).
- 11 Nov 2026, 2.3 in part: the real-money ledger (real_money.py, data/real/orders.csv) compares
  the real account with the paper agent every night, from rows typed in from contract notes. It is
  a check by hand, not a reconciliation against the broker's own statement, and the ticket's loss
  limit and daily stop are reminders, not limits a machine enforces.

- 16 Nov 2026, minor (package versions): pinned exactly, pandas 3.1.1, numpy 2.5.5, matplotlib 3.11.2 and
  pyarrow 22.0.0 (the versions the nightly run was installing), in requirements.txt and the Telegram
  workflow. Each run records the Python, pandas and numpy it used in logs/runs.csv.
- 16 Nov 2026, 3.1 and 2.3 in part: nightly data checks (data_health.py). Every saved price file is checked for
  freshness against the NSE calendar (each market after its own close), missing NSE sessions, duplicate or
  unordered dates, zero prices, highs below lows and unusual moves, and Nifty 50 from Yahoo and from the index
  dataset must agree within 0.05%. Each file gets a version (12 characters of its SHA-256). Shown under "Data
  checks" on the page and as a warning on the GitHub run. A failed check warns; it doesn't stop the run, since
  the arenas never add a day without its price and the risk engine refuses a stale one. First findings: Brent
  fell 10.9% on 2 Nov in the saved series (a futures roll or a real move, to check), and the flows dataset has
  three sessions missing (latest 19 Oct).
- 16 Nov 2026, 2.4 in part: each run records when it started against its schedule (logs/runs.csv), and the
  page shows the last runs, so a late or missed run is visible. GitHub stays unfit for placing an order.
- 16 Nov 2026, replay drift (Minor): each day saved from now on records what it was built from
  (logs/provenance.csv): its prices (for the F&O agents, NSE's option file or estimates), a version of those
  price files and the code's commit. The page lists every saved row tonight's replay values differently, with
  that record. Its old note gave one cause for every difference (estimated option prices), which nothing
  recorded; a difference can also come from a price revised or arriving late at its source, or from a change in
  the code. Rows saved before 16 Nov have no record of what they used.
- 16 Nov 2026, 3.4 and 3.5 in part: the page labels every board group, backtest and the risk engine by how
  its numbers were made (backtest with model prices, backtest with real prices, paper, whole lots, shadow
  mode; broker sandbox and live have nothing), and shows each strategy's worst fall and number of trades next
  to its return. The challenger's section says it isn't an independent check.
- 20 Nov 2026, G18 (tests in the repository, section 11): the checks that had only been run in Claude's sessions
  are now in tests/ (13 files), and GitHub runs them whenever code is uploaded (.github/workflows/tests.yml), each
  on a fresh copy of the repository so they never change a real file. They cover the risk engine (every limit,
  its sums against the order ticket's on 1,500 random orders, the add-only log), the order ticket in a browser,
  Zerodha's charges against its calculator, the NIFTYBEES copy, the real-money ledger (the public-file check
  included), Berlin's record and filters, the signal channel, the event files, the FII/DII flows, the data
  checks and provenance, the Claude agent's decision window and that Claude never reads the challenger, and the
  built pages at phone width. They read the growing logs as they stood at a fixed time, or frozen copies in
  tests/data/, and still passed with the clock moved to January and June 2027, so a new night's rows or a later
  date can't break them. Copies of the code broken on purpose (a risk limit, a charge, a filter time, a data-check
  threshold, the confidence levels, the challenger's isolation, the public-file check) each failed them. A failed
  test shows on the Actions tab; it doesn't stop the nightly run. Not covered: the agents' rules themselves,
  saving posts from Telegram's live site, voice-note transcription and the workflows.

## 8. Broker: Zerodha (added 6 Nov 2026)

The trading account moved from Upstox to Zerodha. What Zerodha's API means for step 4 of the go/no-go
list, from its support pages on 6 Nov 2026. Nothing here needs buying before step 4.

- **Orders through the API:** Kite Connect's Personal plan is free and covers orders, GTTs and the
  portfolio, with no live or historical prices. Live quotes and historical candles need the Connect
  plan, ₹500 a month per app; from October 2026, a month with ₹2,000 or more of brokerage earns ₹500
  of credits towards the next month.
- **Static IP:** since 1 April 2026, API orders must come from a whitelisted static IP (one or two
  addresses, changed at most once a calendar week). Other calls (positions, order book, market data)
  work from any address. GitHub Actions has no fixed address: one more reason (2.4) the execution
  layer needs its own machine.
- **Daily login:** the access token expires every morning before the open, so someone logs in with
  two-factor authentication each trading day. Keep it that way: storing the password and TOTP secret
  on a server so it can log itself in would put the real account's keys next to the paper arena's.
- **Limits and order types:** at most 10 orders a second per account without registering the algo
  with the exchange; market orders must carry a market-protection value (0 is rejected); MCX orders
  go through the API with Day validity.
- **Data for the arena:** not from Zerodha, since a nightly job would need that daily login. NSE's
  free daily files (already used by the F&O agents) and MCX's daily bhavcopy are the route for
  re-scoring on Indian instruments (2.1).
- **Kite MCP** (mcp.kite.trade) lets an AI assistant read holdings, positions and margins, and place
  GTT orders but no others. Fine for portfolio reviews; never on the order path (2.5).
- Sources: https://support.zerodha.com/category/trading-and-markets/kite-web-and-mobile/kite-api/articles/what-are-the-charges-for-kite-apis,
  https://support.zerodha.com/category/trading-and-markets/general-kite/kite-api/articles/static-ip,
  https://support.zerodha.com/category/trading-and-markets/general-kite/kite-api/articles/kite-connect-api-faqs,
  https://support.zerodha.com/category/trading-and-markets/general-kite/others-kite/articles/connect-zerodha-ai-assistant

## 9. Small real money, by hand (added 11 Nov 2026)

The plan is a small account at Zerodha from mid-December 2026, every order placed by hand. This is
what now exists for that, and what the first numbers say. None of it is an execution layer (2.3,
2.4): a person reads the page and taps the order.

- **What exists:** the order ticket (ticket.py) for sizing an order and checking it against rules
  written down beforehand; the ledger for writing down what was actually done; the Real money
  section for comparing it with the paper agent given the same money.
- **What the NIFTYBEES copy shows so far** (11 Nov 2026, his first 6 Nifty calls with levels, 5 of
  which traded, ₹10,000 a call): the price moves added up to +₹12, the spread and slippage took ₹13
  and Zerodha's charges ₹49, leaving −₹50. Costs were 67% of the money risked to the stops. An
  intraday round trip in NIFTYBEES costs about 0.13% at this size, against his usual stop of 0.2%,
  so a call has to be right by a wide margin before it pays. Five trades prove nothing about his
  calls; the cost arithmetic doesn't depend on them.
- **Tracking:** NIFTYBEES wanders 0.15% to 0.5% around Nifty within a day. A level 0.2% away can
  trigger on one and not the other: on 3 Nov a breakdown level that Nifty missed by 4 points
  triggered on NIFTYBEES and was stopped out.
- **Sizes that don't exist:** at ₹5,000 with 2% risked a trade (₹100), Gold Petal at about ₹14,800
  a gram with his usual 1.5% stop loses about ₹243 a lot, so no gold trade fits; Gold Mini and Crude Oil Mini need far
  more margin than the account holds. The ticket says so case by case.
- **The fixed charge:** every sale from the demat account costs ₹15.34 whatever its size: 0.31% of
  a ₹5,000 sale. The ETF agents trade a few times a year, so that is bearable; anything that trades
  weekly at this size is not.
- **The two option-buying agents added today** (in and out of the money) are rule tests like the
  other fractional F&O agents. The four whole-lot agents added the same day are the first at real size:
  on ₹5 lakh, one lot is already 3.3 times the account.
- **Closing times changed in 2026:** since 3 August the shares in Nifty stop continuous trading at
  3:15 pm for a closing auction, so the index stands still from 3:15 to 3:30 pm and then jumps to
  the auction's close. Zerodha closes open intraday positions itself at 3:12 pm in F&O shares and
  3:25 pm in other shares and ETFs, for ₹59 an order. This arena's rule for an intraday NIFTYBEES
  trade is out by 3:10 pm.
- **The ledger is public** (see Minor): it shows what was bought and sold and for how much.
- Sources, read on 11 Nov 2026: https://zerodha.com/charges/,
  https://zerodha.com/brokerage-calculator/ (its script, for the rounding),
  https://support.zerodha.com/category/account-opening/resident-individual/ri-charges/articles/stt-etfs,
  https://zerodha.com/marketintel/bulletin/249809/latest-intraday-leverages-mis-bo-co,
  https://support.zerodha.com/category/trading-and-markets/trading-faqs/general/articles/closing-auction-session,
  https://support.zerodha.com/category/trading-and-markets/trading-faqs/general/articles/short-sell-shares-in-eq-and-f-o-segments

## 10. What each control is, and how far it has been tested (added 16 Nov 2026)

Status, from weakest: **not built**; **built** (code exists, never run against orders); **shadow-tested** (runs
every night on the orders the paper strategies would have sent; nothing sent); **broker-tested** (run against a
broker's test system); **live** (in front of real orders). Nothing is broker-tested or live. The tests named
below were run in Claude's sessions; they aren't in the repository yet. Since 20 Nov 2026 they are, in tests/,
and GitHub runs them whenever code is uploaded (7).

| Control | Where | Status |
|---|---|---|
| Risk a trade (2% of a ₹5,000 account), costs at most 25% of the risk, reward at least 1.5 times the stop after costs, 3 trades and 2 losses a day | risk_engine.py (ticket.RULES) | Shadow-tested since 13 Nov (logs/risk_orders.csv); its sums match the order ticket's on 1,500 random orders |
| No new risk after a 4% day loss; a halt 10% below the peak that a person lifts | risk_engine.py (ENGINE) | Shadow-tested |
| Kill switch (the file data/real/HALT) | risk_engine.py | Built and tested in sessions; never switched on |
| Stale or mistyped prices refused; no repeats; at most 5 orders a minute; market hours and NSE holidays | risk_engine.py | Shadow-tested |
| Exits never refused | risk_engine.py | Shadow-tested |
| Saved results never rewritten | logbook.py, logs/ | Live for the record (every night since 23 Oct) |
| What each saved day was built from | logs/provenance.csv | Built 16 Nov |
| Data checks before a result is trusted | data_health.py | Built 16 Nov; warns, doesn't block |
| Run start against schedule | logs/runs.csv | Built 16 Nov |
| Pinned package versions | requirements.txt | Built 16 Nov |
| Code tests | tests/, .github/workflows/tests.yml | Built 20 Nov: 13 test files on every code upload; copies of the code broken on purpose fail them |
| Reconciliation against the broker's statement | none | Not built (the ledger is checked by hand) |
| Broker-side stops and limits | none | Not built |
| An always-on machine to run orders | none | Not built (2.4) |
| Secrets | GitHub secrets only | No broker credentials exist anywhere; an API key would be a GitHub secret, never a file |

## 11. Outside review of 16 Nov 2026: where each point stands

An engineering review of the public repository (G1 to G18) reached the same verdict as this register: a good
research platform, not ready for real money. Where each point stands:

| Point | Where it stands |
|---|---|
| G1 Sample size | Luck test (60 days) and confidence score since 5 and 11 Nov; worst fall and trades on the board since 16 Nov. Rolling and regime figures wait for data: no strategy has 60 days yet. |
| G2 Model option prices | The F&O backtest is labelled "Backtest, model prices"; the paper agents use NSE's closing prices (the page counts the days with estimates). Bid and ask and the order of a stop and a target inside a day need data that isn't free: open. |
| G3 Executable F&O | Whole-lot agents with margin since 11 Nov (7); costs by date (5). Partial fills and rejections: open, needed at real size. |
| G4 Survivorship | Written in research_tests.py and the README; no agent uses it. The Nifty 50 list as it was each year isn't free: open. |
| G5 Replay against saved | Done 16 Nov (7). |
| G6 Data quality | Done 16 Nov (7); a second source for Nifty 50 only. |
| G7 Gold contracts | His gold is scored on COMEX; the risk engine refuses gold and crude orders (no MCX prices). MCX re-scoring: open (2.1). |
| G8 Claude as allocator | By design; every decision saves its snapshot, model and time. No AI output can skip the risk engine (go/no-go 4). |
| G9 Challenger independence | Labelled 16 Nov. A challenger that doesn't see Claude's answer, or another model, would be a new agent: open (needs an API key or another model). |
| G10 Many strategies | The luck test is for one strategy named in advance, with the best-of-N warning (3.4); no agent is ever deleted. |
| G11 Risk engine is paper only | Labelled "Shadow mode". Failing closed and broker-side limits matter only in front of a broker (go/no-go 4). |
| G12 Live execution | Not built, by design (go/no-go 4). |
| G13 Scheduler | Run times recorded 16 Nov (7); still unfit for orders (2.4). |
| G14 Untrusted inputs | Rules since 5 Nov (2.5); posts, transcripts and deletions saved separately. |
| G15 Telegram scoring | The ten-check scorecard since 4 Nov: 40 calls, costs, late and reversed, levels coverage, claims, deletions. |
| G16 This register | Sections 10 and 11. |
| G17 Public ledger | No real order recorded yet (data/real/orders.csv doesn't exist). Decide before the first one whether it stays public (Minor). |
| G18 Reproducibility | Pinned 16 Nov; versions per run in logs/runs.csv. Tests in the repository: done 20 Nov (7). |
