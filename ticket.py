"""
ticket.py - the order ticket: site/ticket.html, a calculator for the phone.

It turns a call ("Nifty short, stop 25,050, target 24,900") into an order you could place yourself at
Zerodha: the stop and target in the prices of what you would actually trade (NIFTYBEES for Nifty, an
MCX future for gold or crude oil), the quantity that keeps the loss inside your limit, the charges
from zerodha.py, and whether the trade passes your own rules. Your rules and today's count of trades
stay in your browser; nothing is sent anywhere.

It never places an order, and it isn't advice. build_site.py writes the page each night.
"""

import json
import os

import pandas as pd

import zerodha

# What he quotes -> what you can trade. The stops used when he gives none are the record's own
# (berlin_calls.DEFAULT_STOP); the spread allowances are this arena's guesses, which you can change.
MARKETS = {
    "nifty": {"name": "Nifty", "his": "Nifty", "stop": {"day": 0.002, "days": 0.015}, "slip": 0.00015,
              "contracts": [{"code": "NIFTYBEES", "name": "NIFTYBEES", "mult": 1, "tick": 0.01, "unit": "unit",
                             "quoted": "one unit"}]},
    "gold": {"name": "Gold", "his": "gold in dollars (XAUUSD)", "quote": "XAUUSD", "stop": {"day": 0.004, "days": 0.015},
             "slip": 0.0003,
             "contracts": [{"code": c, "name": n, "mult": zerodha.MCX[c][0], "tick": 1, "unit": "lot",
                            "quoted": zerodha.MCX[c][1]}
                           for c, n in (("GOLDPETAL", "Gold Petal (1 gram)"), ("GOLDGUINEA", "Gold Guinea (8 grams)"),
                                        ("GOLDTEN", "Gold Ten (10 grams)"), ("GOLDM", "Gold Mini (100 grams)"))]},
    "crude": {"name": "Crude oil", "his": "crude oil in dollars (WTI)", "quote": "WTI", "stop": {"day": 0.01, "days": 0.03},
              "slip": 0.0003,
              "contracts": [{"code": "CRUDEOILM", "name": "Crude Oil Mini (10 barrels)", "mult": zerodha.MCX["CRUDEOILM"][0],
                             "tick": 1, "unit": "lot", "quoted": zerodha.MCX["CRUDEOILM"][1]}]},
}
MCX_MARGIN = 0.10          # share of a future's value assumed as margin when you don't type Kite's figure
RULES = {"account": 5000, "riskPct": 2, "maxLosses": 2, "maxTrades": 3, "minRR": 1.5, "maxCostPct": 25}


def rates():
    """zerodha.py's numbers, for the page's own copy of the same sums."""
    key = lambda k: f"{k[0]}:{k[1]}"
    return {"checked": zerodha.CHECKED, "source": zerodha.SOURCE, "gst": zerodha.GST, "sebi": zerodha.SEBI,
            "brokerage": zerodha.BROKERAGE, "brokerage_cap": zerodha.BROKERAGE_CAP,
            "exchange": {k: list(v) for k, v in zerodha.EXCHANGE.items()}, "stamp": zerodha.STAMP,
            "sell_tax": {key(k): v for k, v in zerodha.SELL_TAX.items()},
            "buy_tax": {key(k): v for k, v in zerodha.BUY_TAX.items()}, "dp": zerodha.DP_CHARGE,
            "mis_margin": zerodha.MIS_MARGIN["NIFTYBEES"], "mcx_margin": MCX_MARGIN,
            "auto_square_off": zerodha.AUTO_SQUARE_OFF, "exit_by": zerodha.EXIT_BY_IST,
            "square_off": zerodha.SQUARE_OFF_IST}


def hints():
    """The last saved closes, shown faintly in the empty boxes so the size of each number is clear."""
    out = {}
    for name, key in (("NIFTY50", "nifty_his"), ("NIFTYBEES", "nifty_trade"), ("GOLD", "gold_his")):
        try:
            close = pd.read_csv(os.path.join("data", "market", f"{name}.csv"))["Close"].dropna().iloc[-1]
            out[key] = round(float(close), 2)
        except Exception:
            pass
    return out


EXTRA_CSS = """
.ticket{max-width:40rem}
.ticket h2{margin-top:0}
.ticket section{margin-top:2rem}
.ticket fieldset{border:0;padding:0;margin:0 0 1.1rem;min-width:0}
.ticket legend,.ticket .field>label{display:block;font-weight:600;margin:0 0 .35rem;padding:0}
.ticket .hint{display:block;font-weight:400;color:var(--muted);font-size:.9rem;margin-top:.15rem}
.ticket .field{margin:0 0 1.1rem}
.ticket input[type=number],.ticket select{display:block;width:100%;font:inherit;padding:.6rem .7rem;min-height:3rem;
border:1px solid var(--rule);border-radius:.5rem;background:var(--surface);color:var(--ink)}
.ticket input[type=number]:focus-visible,.ticket select:focus-visible,.ticket button:focus-visible,
.ticket summary:focus-visible{outline:2px solid var(--score);outline-offset:2px}
.ticket .two{display:grid;grid-template-columns:1fr 1fr;gap:.75rem}
.ticket .seg{display:flex;gap:.5rem}
.ticket .seg label{flex:1 1 0;position:relative;margin:0;min-width:0}
.ticket .seg input{position:absolute;inset:0;width:100%;height:100%;margin:0;opacity:0;cursor:pointer}
.ticket .seg span{display:flex;align-items:center;justify-content:center;text-align:center;min-height:3rem;
padding:.4rem .5rem;border:1px solid var(--rule);border-radius:.5rem;background:var(--surface);font-weight:600;line-height:1.2}
.ticket .seg input:checked+span{background:var(--board);border-color:var(--score);color:var(--board-ink);
box-shadow:inset 0 0 0 1px var(--score)}
.ticket .seg input:focus-visible+span{outline:2px solid var(--score);outline-offset:2px}
.ticket .board{margin-top:2rem;padding:1.1rem 1rem 1.1rem}
.ticket .board h2{padding:0}
.ticket .order{font:600 1.7rem/1.2 "Barlow Condensed","Arial Narrow",system-ui,sans-serif;margin:.2rem 0 .9rem;
max-width:none;overflow-wrap:anywhere}
.ticket .board .stats div{border-left-color:var(--board-rule)}
.ticket .board .stats dt{color:var(--board-muted)}
.ticket .board p{color:var(--board-ink)}
.ticket .board .meta{color:var(--board-muted);padding:0}
.ticket .board .stats+.meta{margin-top:1rem}
.ticket button{font:inherit;font-weight:600;min-height:3rem;padding:.5rem .9rem;border-radius:.5rem;cursor:pointer;
border:1px solid var(--rule);background:var(--surface);color:var(--ink)}
.ticket .board button{background:var(--score);border-color:var(--score);color:#1E2B25;margin-top:.4rem}
.ticket .btns{display:flex;gap:.5rem;flex-wrap:wrap;margin-top:.6rem}
.ticket .verdict{font-weight:600;margin:0 0 .5rem}
.ticket .checklist li{padding:.3rem 0 .3rem 1.4rem;text-indent:-1.4rem;font-size:1rem}
.ticket .checklist .mark{width:1.4rem}
.ticket details.more{margin-top:1.25rem}
.ticket details.more p,.ticket details.more li{max-width:none}
.ticket .tally{font:600 1.25rem/1.3 "Barlow Condensed","Arial Narrow",system-ui,sans-serif;margin:0}
.ticket [hidden]{display:none}
@media (max-width:22rem){.ticket .two{grid-template-columns:1fr}}
"""

SCRIPT = r"""
(function () {
  'use strict';
  var Z = __RATES__, MARKETS = __MARKETS__, DEFAULT_RULES = __RULES__;
  var $ = function (id) { return document.getElementById(id); };

  // ---- Zerodha's charges: the same sums as zerodha.py, which follow Zerodha's own calculator ----
  function f2(x) { return parseFloat(parseFloat(x).toFixed(2)); }
  function charges(buy, sell, product, kind) {
    var brok = function (v) { return product === 'CNC' ? 0 : Math.min(f2(v * Z.brokerage), Z.brokerage_cap); };
    var turnover = f2(buy + sell), key = product + ':' + kind, o = {};
    o.brokerage = f2(brok(buy) + brok(sell));
    var tax = sell * Z.sell_tax[key] + buy * (Z.buy_tax[key] || 0);
    o.tax = product === 'MCX' ? f2(tax) : Math.round(f2(tax));
    var ex = 0;
    Z.exchange[product].forEach(function (rate) { ex += f2(turnover * rate); });
    o.exchange = f2(ex);
    o.sebi = f2(turnover * Z.sebi);
    o.stamp = Math.round(f2(buy * Z.stamp[product]));
    o.gst = f2(Z.gst * (o.brokerage + o.exchange + o.sebi));
    o.dp = (product === 'CNC' && sell > 0) ? Z.dp : 0;
    o.total = f2(o.brokerage + o.tax + o.exchange + o.sebi + o.stamp + o.gst + o.dp);
    return o;
  }

  function toTick(x, tick) { return Math.round(x / tick + 1e-9) * tick; }

  // The time in India, whatever the phone is set to: {day: 0 Sunday..6, minutes since midnight}
  function india(now) {
    var t = new Date(now.getTime() + 330 * 60000);
    return { day: t.getUTCDay(), minutes: t.getUTCHours() * 60 + t.getUTCMinutes() };
  }
  function clock(minutes) {
    var h = Math.floor(minutes / 60), m = minutes % 60;
    return ((h + 11) % 12 + 1) + ':' + (m < 10 ? '0' : '') + m + (h < 12 ? ' am' : ' pm');
  }
  function span(minutes) {
    var h = Math.floor(minutes / 60), m = minutes % 60;
    return (h ? h + (h === 1 ? ' hour ' : ' hours ') : '') + m + (m === 1 ? ' minute' : ' minutes');
  }

  // ---- the sums: everything the page shows comes from here ----
  // inp: {market, contract, side, horizon, his, stop, target, rr, trade, marginLot}; numbers or null
  // rules: {account, riskPct, maxLosses, maxTrades, minRR, maxCostPct}; tally: {trades, losses}; now: Date
  function compute(inp, rules, tally, now) {
    var m = MARKETS[inp.market];
    var c = m.contracts.filter(function (x) { return x.code === inp.contract; })[0] || m.contracts[0];
    if (!(inp.his > 0) || !(inp.trade > 0)) {
      return { need: 'Type ' + m.his + ' now, and the price of ' + c.name + ' now.' };
    }
    var future = inp.market !== 'nifty', sign = inp.side === 'long' ? 1 : -1, day = inp.horizon === 'day';
    var product = future ? 'MCX' : (day ? 'MIS' : 'CNC'), kind = future ? 'future' : 'equity_etf';
    var ratio = inp.trade / inp.his, entry = inp.trade, mult = c.mult;
    var defaultStop = !(inp.stop > 0);
    var stop = toTick(defaultStop ? entry * (1 - sign * m.stop[inp.horizon]) : inp.stop * ratio, c.tick);
    if ((stop - entry) * sign >= 0) {
      return { need: 'His stop is on the wrong side of the price for a ' + (sign > 0 ? 'buy' : 'sale') +
                     '. Check the stop, the direction, and that both prices are from the same moment.', wrong: true };
    }
    var target = null, targetFrom = '';
    if (inp.target > 0) { target = toTick(inp.target * ratio, c.tick); targetFrom = 'his level'; }
    else if (inp.rr > 0) { target = toTick(entry + sign * inp.rr * Math.abs(entry - stop), c.tick); targetFrom = 'his reward ratio'; }
    if (target !== null && (target - entry) * sign <= 0) {
      return { need: 'The price is already past his target, so the move has happened. Check the numbers.', wrong: true };
    }
    var slip = m.slip;
    var entryFill = entry * (1 + sign * slip), stopFill = stop * (1 - sign * slip);
    function outcome(n, exitFill) {                       // rupees after costs if n units or lots go out at exitFill
      var a = n * mult * entryFill, b = n * mult * exitFill;
      var fees = sign > 0 ? charges(a, b, product, kind) : charges(b, a, product, kind);
      return { net: sign * (b - a) - fees.total, fees: fees };
    }
    var limit = rules.account * rules.riskPct / 100;
    var perMove = mult * Math.abs(entryFill - stopFill);
    var marginLot = future ? (inp.marginLot > 0 ? inp.marginLot : Z.mcx_margin * entry * mult)
                           : (product === 'MIS' ? Z.mis_margin * entry : entry);
    var byRisk = Math.floor(limit / perMove + 1e-9), byMoney = Math.floor(rules.account / marginLot + 1e-9);
    var n = Math.max(0, Math.min(byRisk, byMoney));
    while (n > 0 && -outcome(n, stopFill).net > limit + 1e-9) { n -= 1; }
    var one = outcome(1, stopFill);
    var out = { market: m, contract: c, product: product, sign: sign, day: day, future: future, ratio: ratio,
                entry: entry, stop: stop, target: target, targetFrom: targetFrom, defaultStop: defaultStop,
                defaultStopPct: m.stop[inp.horizon], limit: limit, n: n, byRisk: byRisk, byMoney: byMoney,
                marginLot: marginLot, marginGuess: future && !(inp.marginLot > 0), lossOne: -one.net,
                unit: c.unit + (n === 1 ? '' : 's') };
    var checks = [];
    function check(ok, text) { checks.push({ ok: ok, text: text }); }

    if (!future && !day && sign < 0) {
      check(false, 'A short can only be held for the day in NIFTYBEES. Holding a short for days needs futures, which this account is too small for.');
    }
    if (n < 1) {
      if (byMoney < 1) {
        check(false, 'Not enough money for one ' + c.unit + ': it needs about ' + rupees(marginLot) + (out.marginGuess ? ' of margin (a guess: check Kite)' : '') + ' and the account has ' + rupees(rules.account) + '.');
      } else {
        check(false, 'Even one ' + c.unit + ' loses ' + rupees(-one.net) + ' at the stop, more than your limit of ' + rupees(limit) + ' a trade.');
      }
    } else {
      var atStop = outcome(n, stopFill), value = n * mult * entry, rawRisk = n * mult * Math.abs(entry - stop);
      out.value = value; out.margin = n * marginLot; out.atStop = atStop.net; out.fees = atStop.fees;
      out.costs = -atStop.net - rawRisk; out.costPct = out.costs / rawRisk * 100;
      check(true, 'If the stop is hit you lose ' + rupees(-atStop.net) + ', inside your limit of ' + rupees(limit) + ' a trade.');
      check(out.costPct <= rules.maxCostPct, 'Charges and the spread are ' + out.costPct.toFixed(0) + '% of the money at risk (your limit: ' + rules.maxCostPct + '%).');
      if (target !== null) {
        var atTarget = outcome(n, target);
        out.atTarget = atTarget.net; out.rrAfter = atTarget.net / -atStop.net;
        check(out.rrAfter >= rules.minRR, 'After costs the target pays ' + out.rrAfter.toFixed(1) + ' times what the stop loses (your least: ' + rules.minRR + ').');
      } else {
        check(null, 'No target given, so the reward can’t be weighed against the risk.');
      }
      if (!future && product === 'MIS' && value > rules.account) {
        check(null, 'The order is ' + (value / rules.account).toFixed(1) + ' times your money: Zerodha lends the rest for the day, and both the gain and the loss grow with it.');
      }
      if (byMoney < byRisk) {
        check(null, 'The account’s size sets the quantity here, not your loss limit.');
      }
    }
    var t = india(now), exitBy = minutesOf(Z.exit_by), open = 9 * 60 + 15;
    if (!future && day) {
      if (t.day === 0 || t.day === 6) { check(null, 'It’s the weekend in India: the market is shut, and prices will have moved by Monday.'); }
      else if (t.minutes < open) { check(null, 'The market opens at 9:15 am. Type the prices again once it has.'); }
      else if (t.minutes >= exitBy) { check(false, 'It’s ' + clock(t.minutes) + ' in India: past ' + clock(exitBy) + ', too late for a trade that has to close today.'); }
      else if (exitBy - t.minutes < 30) { check(false, 'Only ' + span(exitBy - t.minutes) + ' until ' + clock(exitBy) + ', when it has to be closed.'); }
      else { check(true, span(exitBy - t.minutes) + ' until ' + clock(exitBy) + ', when it has to be closed. Zerodha closes it itself from ' + clock(minutesOf(Z.square_off)) + ' and charges ' + rupees(Z.auto_square_off) + '.'); }
    } else if (future && day) {
      check(null, 'MCX trades until 11:30 pm (11:55 pm in the US winter). Zerodha closes intraday positions itself 10 minutes before and charges ' + rupees(Z.auto_square_off) + '.');
    }
    if (tally.losses >= rules.maxLosses) {
      check(false, tally.losses + ' losing ' + (tally.losses === 1 ? 'trade' : 'trades') + ' today: your rule says stop for the day.');
    } else if (tally.trades >= rules.maxTrades) {
      check(false, tally.trades + ' trades today: your rule allows ' + rules.maxTrades + '.');
    } else {
      check(true, 'Today so far: ' + tally.trades + (tally.trades === 1 ? ' trade, ' : ' trades, ') + tally.losses + (tally.losses === 1 ? ' loss' : ' losses') + '. Your rules allow ' + rules.maxTrades + ' trades and stop after ' + rules.maxLosses + (rules.maxLosses === 1 ? ' loss.' : ' losses.'));
    }
    out.checks = checks;
    out.failed = checks.filter(function (x) { return x.ok === false; }).length;
    return out;
  }
  function minutesOf(hhmm) { var p = hhmm.split(':'); return parseInt(p[0], 10) * 60 + parseInt(p[1], 10); }

  // ---- words and numbers ----
  function rupees(x, signed) {
    var a = Math.abs(x), digits = a < 1000 && a !== Math.round(a) ? 2 : 0;
    var text = '₹' + a.toLocaleString('en-IN', { minimumFractionDigits: digits, maximumFractionDigits: digits });
    return (x < 0 ? '−' : (signed ? '+' : '')) + text;
  }
  function price(x, tick) {
    var digits = tick < 1 ? 2 : 0;
    return '₹' + x.toLocaleString('en-IN', { minimumFractionDigits: digits, maximumFractionDigits: digits });
  }

  // ---- the browser's memory: your rules and today's count. The page works without it. ----
  function load(key, fallback) {
    try { var raw = window.localStorage.getItem(key); return raw ? JSON.parse(raw) : fallback; }
    catch (e) { return fallback; }
  }
  function save(key, value) {
    try { window.localStorage.setItem(key, JSON.stringify(value)); return true; } catch (e) { return false; }
  }
  function todayKey(now) {
    var t = new Date(now.getTime() + 330 * 60000);
    return t.getUTCFullYear() + '-' + (t.getUTCMonth() + 1) + '-' + t.getUTCDate();
  }
  function now() { return window.__now ? new Date(window.__now) : new Date(); }

  var rules = {}, tally = { day: '', trades: 0, losses: 0 };
  function readRules() {
    var saved = load('ticket-rules', {}) || {};
    Object.keys(DEFAULT_RULES).forEach(function (k) {
      rules[k] = (typeof saved[k] === 'number' && saved[k] > 0) ? saved[k] : DEFAULT_RULES[k];
      $('r-' + k).value = rules[k];
    });
  }
  function readTally() {
    var saved = load('ticket-tally', null), key = todayKey(now());
    tally = (saved && saved.day === key) ? saved : { day: key, trades: 0, losses: 0 };
  }

  function num(id) { var v = parseFloat($(id).value); return isFinite(v) ? v : null; }
  function picked(name) { var el = document.querySelector('input[name="' + name + '"]:checked'); return el ? el.value : null; }

  function inputs() {
    return { market: picked('market'), contract: $('contract').value, side: picked('side'), horizon: picked('horizon'),
             his: num('his'), stop: num('stop'), target: num('target'), rr: num('rr'), trade: num('trade'),
             marginLot: num('marginLot') };
  }

  function setMarket() {
    var key = picked('market'), m = MARKETS[key], select = $('contract');
    select.innerHTML = '';
    m.contracts.forEach(function (c) {
      var o = document.createElement('option'); o.value = c.code; o.textContent = c.name; select.appendChild(o);
    });
    $('contract-field').hidden = m.contracts.length < 2;
    $('margin-field').hidden = key === 'nifty';
    $('his-label').textContent = (key === 'nifty' ? 'Nifty now' : m.name + ' now, on his chart');
    $('his-hint').textContent = key === 'nifty' ? 'The index itself, at this moment.' : 'In dollars, at this moment (' + m.quote + ').';
    $('his').placeholder = HINTS[key + '_his'] || '';
    setContract();
  }
  function setContract() {
    var key = picked('market'), m = MARKETS[key];
    var c = m.contracts.filter(function (x) { return x.code === $('contract').value; })[0] || m.contracts[0];
    $('trade-label').textContent = c.code + ' now';
    $('trade-hint').textContent = 'Its price on Kite at this moment, in rupees' + (key === 'nifty' ? '.' : ' for ' + c.quoted + '.');
    $('trade').placeholder = HINTS[key + '_trade'] || '';
  }

  function render() {
    var r = compute(inputs(), rules, tally, now());
    var order = $('order'), stats = $('stats'), note = $('note'), list = $('checks'), verdict = $('verdict');
    stats.innerHTML = ''; list.innerHTML = ''; $('copy').hidden = true; $('copied').textContent = '';
    if (r.need) {
      order.textContent = r.wrong ? 'Check the numbers' : 'Waiting for the numbers';
      note.textContent = r.need; verdict.textContent = ''; window.__result = r;
      return;
    }
    var c = r.contract, verb = r.sign > 0 ? 'Buy' : 'Sell';
    var kindWords = r.future ? 'MCX future' + (r.day ? ', for the day' : '') : (r.product === 'MIS' ? 'for the day (MIS)' : 'to hold (CNC)');
    function stat(label, value, cls) {
      var d = document.createElement('div'), dt = document.createElement('dt'), dd = document.createElement('dd');
      dt.textContent = label; dd.textContent = value; if (cls) { dd.className = cls; }
      d.appendChild(dt); d.appendChild(dd); stats.appendChild(d);
    }
    if (r.n < 1) {
      order.textContent = 'No order: it doesn’t fit';
    } else {
      order.textContent = verb + ' ' + r.n + ' ' + (r.future ? r.unit + ' of ' : '') + c.code + ', ' + kindWords;
    }
    stat('Stop' + (r.defaultStop ? ' (none given: ' + (r.defaultStopPct * 100).toFixed(1) + '%)' : ''), price(r.stop, c.tick));
    stat('Target' + (r.targetFrom === 'his reward ratio' ? ' (from his ratio)' : ''), r.target === null ? 'none' : price(r.target, c.tick));
    if (r.n >= 1) {
      stat('Order value', rupees(r.value));
      stat(r.future ? 'Margin' + (r.marginGuess ? ' (a guess)' : '') : (r.product === 'MIS' ? 'Margin needed' : 'Money needed'), rupees(r.margin));
      stat('If the stop is hit', rupees(r.atStop, true), 'down');
      if (r.target !== null) { stat('If the target is hit', rupees(r.atTarget, true), r.atTarget >= 0 ? 'up' : 'down'); }
      stat('Charges', rupees(r.fees.total));
    } else {
      stat('One ' + c.unit + ' at the stop', rupees(-r.lossOne, true), 'down');
      stat('Your limit a trade', rupees(r.limit));
    }
    note.textContent = '1 point on his chart is ' + (r.ratio * c.mult >= 1 ? rupees(r.ratio * c.mult) : '₹' + (r.ratio * c.mult).toFixed(4)) +
      ' on one ' + c.unit + ' of ' + c.code + '. The quantity keeps the loss at the stop, after charges and a ' +
      (r.market.slip * 100).toFixed(3) + '% spread on each fill, inside ' + rupees(r.limit) + '.';
    r.checks.forEach(function (x) {
      var li = document.createElement('li'), mark = document.createElement('span');
      li.className = x.ok === true ? 'ok' : (x.ok === false ? 'no' : 'wait');
      mark.className = 'mark'; mark.textContent = x.ok === true ? '✓' : (x.ok === false ? '✗' : '·');
      mark.setAttribute('aria-hidden', 'true');
      var words = document.createElement('span'); words.className = 'visually-hidden';
      words.textContent = x.ok === true ? 'Passes: ' : (x.ok === false ? 'Fails: ' : 'Note: ');
      li.appendChild(mark); li.appendChild(words); li.appendChild(document.createTextNode(x.text));
      list.appendChild(li);
    });
    verdict.textContent = r.failed ? 'Fails ' + r.failed + (r.failed === 1 ? ' check' : ' checks') + ': it doesn’t fit your own rules.'
                                   : 'Passes your rules. That means it fits your limits, not that it will make money.';
    if (r.n >= 1) {
      r.text = verb.toUpperCase() + ' ' + r.n + ' ' + c.code + ' ' + (r.future ? 'MCX' : r.product) + ' at market, about ' + price(r.entry, c.tick) +
        '. Stop-loss ' + price(r.stop, c.tick) + '.' + (r.target === null ? '' : ' Target ' + price(r.target, c.tick) + '.') +
        (!r.future && r.day ? ' Out by ' + clock(minutesOf(Z.exit_by)) + '.' : '');
      $('copy').hidden = false;
    }
    window.__result = r;
  }

  function showTally() {
    $('tally').textContent = tally.trades + (tally.trades === 1 ? ' trade, ' : ' trades, ') + tally.losses + (tally.losses === 1 ? ' loss' : ' losses') + ' today';
  }
  function bump(what) {
    readTally();
    if (what === 'reset') { tally.trades = 0; tally.losses = 0; }
    else { tally[what] += 1; if (what === 'losses' && tally.trades < tally.losses) { tally.trades = tally.losses; } }
    $('memory').hidden = save('ticket-tally', tally);
    showTally(); render();
  }

  var HINTS = __HINTS__;
  document.addEventListener('DOMContentLoaded', function () {
    readRules(); readTally(); showTally(); setMarket();
    $('t').addEventListener('input', function (e) {
      if (e.target.name === 'market') { setMarket(); }
      if (e.target.id === 'contract') { setContract(); }
      render();
    });
    $('t').addEventListener('submit', function (e) { e.preventDefault(); });
    $('rules').addEventListener('input', function () {
      Object.keys(DEFAULT_RULES).forEach(function (k) {
        var v = parseFloat($('r-' + k).value);
        rules[k] = (isFinite(v) && v > 0) ? v : DEFAULT_RULES[k];
      });
      $('memory').hidden = save('ticket-rules', rules);
      render();
    });
    $('add-trade').addEventListener('click', function () { bump('trades'); });
    $('add-loss').addEventListener('click', function () { bump('losses'); });
    $('reset-day').addEventListener('click', function () { bump('reset'); });
    $('copy').addEventListener('click', function () {
      var text = window.__result && window.__result.text;
      if (!text) { return; }
      var done = function (ok) { $('copied').textContent = ok ? 'Copied: ' + text : text; };
      try { navigator.clipboard.writeText(text).then(function () { done(true); }, function () { done(false); }); }
      catch (e) { done(false); }
    });
    render();
  });
  window.ticket = { charges: charges, compute: compute, india: india };
}());
"""


def seg(name, options, legend):
    """A row of big either-or buttons: radio inputs, so they work with a keyboard and a screen reader."""
    items = "".join(f"<label><input type='radio' name='{name}' value='{value}'{' checked' if i == 0 else ''}>"
                    f"<span>{label}</span></label>" for i, (value, label) in enumerate(options))
    return f"<fieldset><legend>{legend}</legend><div class='seg'>{items}</div></fieldset>"


def field(fid, label, hint="", step="any", extra=""):
    return (f"<div class='field'{extra}><label for='{fid}' id='{fid}-label'>{label}</label>"
            f"<input type='number' id='{fid}' inputmode='decimal' step='{step}' min='0' autocomplete='off' "
            f"aria-describedby='{fid}-hint'><span class='hint' id='{fid}-hint'>{hint}</span></div>")


def page(css="", built=None, hint_values=None, nav=""):
    """The whole page. nav: the site's bar for the top (build_site.nav_html); without it, a link back."""
    built = built or pd.Timestamp.now(tz="Asia/Kolkata")
    top = nav or "<p class='meta'><a href='index.html'>← Paper arena</a></p>"
    script = (SCRIPT.replace("__RATES__", json.dumps(rates())).replace("__MARKETS__", json.dumps(MARKETS))
              .replace("__RULES__", json.dumps(RULES))
              .replace("__HINTS__", json.dumps(hints() if hint_values is None else hint_values)))
    rule_fields = "".join(
        f"<div class='field'><label for='r-{k}'>{label}</label><input type='number' id='r-{k}' inputmode='decimal' "
        f"step='any' min='0' autocomplete='off'><span class='hint'>{hint}</span></div>"
        for k, label, hint in (
            ("account", "Money in the account, ₹", "What is in your Zerodha account for this."),
            ("riskPct", "Most you’ll lose on one trade, % of the account", "2% of ₹5,000 is ₹100."),
            ("maxLosses", "Stop for the day after this many losing trades", ""),
            ("maxTrades", "Most trades in a day", ""),
            ("minRR", "Least the target must pay, as a multiple of the loss at the stop", "After charges."),
            ("maxCostPct", "Most that charges and the spread may take, % of the money at risk", "")))
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Order ticket · Paper arena</title>
<meta name="description" content="Turns a Nifty, gold or crude oil call into an order at Zerodha: quantity, stop, target, charges and rule checks. A calculator; it never places an order.">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Barlow:wght@400;600&family=Barlow+Condensed:wght@500;600;700&display=swap" rel="stylesheet">
<style>{css}.visually-hidden{{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap}}{EXTRA_CSS}</style>
</head>
<body>
<div class="wrap ticket">
{top}
<header>
<h1>Order ticket</h1>
<p class="lede">Turn a call into an order you could place yourself at Zerodha: the stop and target in the right prices, the quantity, the charges, and whether it passes your own rules.</p>
<p class="meta">A calculator. It never places an order, it sends nothing anywhere, and it isn’t advice.</p>
</header>
<main>
<form id="t" novalidate>
<section aria-labelledby="call-h">
<h2 id="call-h">The call</h2>
{seg("market", [(k, m["name"]) for k, m in MARKETS.items()], "What is the call on?")}
<div class="field" id="contract-field" hidden><label for="contract">Which MCX contract?</label><select id="contract"></select>
<span class="hint">The small ones need far less money. Check on Kite that the one you pick is trading.</span></div>
{seg("side", [("long", "Buy"), ("short", "Sell short")], "Which way?")}
{seg("horizon", [("day", "Today only"), ("days", "Days")], "For how long?")}
<div class="two">
{field("his", "Nifty now", "The index itself, at this moment.")}
{field("trade", "NIFTYBEES now", "Its price on Kite at this moment, in rupees.")}
</div>
<div class="two">
{field("stop", "His stop", "On his chart. Empty if he gave none.")}
{field("target", "His target", "On his chart. Empty if he gave none.")}
</div>
{field("rr", "Or his reward ratio", "For “1:2” type 2. Used only when the target is empty.")}
{field("marginLot", "Margin for one lot on Kite, ₹", "From Kite’s order window. Empty: 10% of the contract’s value is assumed.", extra=" id='margin-field' hidden")}
</section>
</form>
<section class="board" aria-labelledby="order-h">
<h2 id="order-h">The order</h2>
<p class="order" id="order" role="status">Waiting for the numbers</p>
<dl class="stats" id="stats"></dl>
<p class="meta" id="note"></p>
<button type="button" id="copy" hidden>Copy the order as text</button>
<p class="meta" id="copied" role="status"></p>
</section>
<section aria-labelledby="checks-h">
<h2 id="checks-h">Your rules</h2>
<p class="verdict" id="verdict" role="status"></p>
<ul class="checklist" id="checks"></ul>
</section>
<section aria-labelledby="today-h">
<h2 id="today-h">Today</h2>
<p class="tally" id="tally" role="status"></p>
<div class="btns"><button type="button" id="add-trade">Count a trade</button><button type="button" id="add-loss">Count a loss</button><button type="button" id="reset-day">Start today again</button></div>
<p class="meta" style="margin-top:.6rem">Tap these after you trade, so the next ticket knows when your rules say stop. The count starts again each day.</p>
<p class="meta" id="memory" hidden>This browser won’t keep your rules or today’s count (private mode, or storage is blocked). The ticket still works; type your rules again next time.</p>
</section>
<details class="more"><summary>Change your rules<span class="hint">Account size, loss limit, daily stops</span></summary>
<form id="rules" novalidate>{rule_fields}</form>
<p class="meta">Kept in this browser only. Empty or zero goes back to the starting value.</p>
</details>
<details class="more"><summary>How it works<span class="hint">The sums, and what they leave out</span></summary>
<p>You can’t buy the Nifty index, and gold in dollars on an offshore broker isn’t allowed from India. So the ticket moves his levels onto what you can trade, by the ratio of the two prices at this moment. That ratio drifts: by a few hundredths of a percent during the day for NIFTYBEES, and by more over days for MCX gold and crude, which also move with the rupee. Type both prices at the same moment, and again if you wait.</p>
<p>The quantity is the largest whose loss at the stop, after charges and the spread, stays inside your limit, and that the account can pay for. A stop is not a promise: after a gap or in a fast market the loss is bigger.</p>
<p>Charges are <a href="{zerodha.SOURCE}">Zerodha’s</a> as read on {pd.Timestamp(zerodha.CHECKED).day} {pd.Timestamp(zerodha.CHECKED):%b %Y}, worked out the way its own calculator does. Tax on any profit isn’t included.</p>
<p>A trade for today in NIFTYBEES has to be closed by {zerodha.EXIT_BY_IST.replace("15:", "3:")} pm: Nifty’s own shares stop trading at 3:15 pm, and Zerodha closes what is still open from {zerodha.SQUARE_OFF_IST.replace("15:", "3:")} pm for ₹{zerodha.AUTO_SQUARE_OFF:.0f}. A short can’t be held overnight in NIFTYBEES.</p>
<p>The spread allowances (0.015% for NIFTYBEES, 0.03% for MCX) and the 10% MCX margin are this arena’s guesses. The small MCX contracts can trade thinly: look at the bid and the ask on Kite first.</p>
</details>
</main>
<footer>
<p>For learning only. Not investment advice. This page never places an order.</p>
<p>Page built on {built.day} {built:%b %Y} at {built:%H:%M} IST.</p>
</footer>
</div>
<script>{script}</script>
</body>
</html>
"""
