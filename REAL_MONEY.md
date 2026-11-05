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
