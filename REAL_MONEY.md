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
