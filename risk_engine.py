"""The risk engine: the checks an order has to pass before it could ever reach a broker, in plain code
that no AI can talk its way past (REAL_MONEY.md 2.3).

Nothing here places an order. The engine runs in paper ("shadow") mode: each night it takes the orders
the paper strategies would have sent, decides each one exactly as it would decide a real one, and adds
the decision to logs/risk_orders.csv. A row is written once and never changed, so the log is a record of
what the engine decided at the time, not of what it would decide today.

Rules
- The limits are the order ticket's (ticket.RULES, written down on 11 Nov 2026: a Rs 5,000 account, 2% of
  it at risk a trade, charges at most 25% of that risk, a target worth at least 1.5 times the stop after
  costs, at most 3 trades and 2 losses a day) and the engine's own (ENGINE, written down on 13 Nov 2026).
  Never loosen one to let an order through. A change of limits is a new VERSION, and every row of the log
  says which version decided it.
- An order that closes or reduces a position is always approved: no limit or halt can trap a position.
- The kill switch is the file data/real/HALT. While it exists, nothing new is approved from the date and
  time on its first line (India time; without one, from the run that finds it). Only the user creates or
  deletes it: on GitHub, "Add file" named data/real/HALT; delete the file to lift it.
- The drawdown halt trips by itself once an account is ENGINE["drawdownPct"]% below its peak and stays on.
  A person has to lift it; in paper mode nobody does, so the rest of that account's orders are refused.
"""
import argparse
import collections
import csv
import datetime as dt
import math
import os
import re
import sys

import pandas as pd

import ticket
import zerodha

VERSION = "2026-11-13"
RULES = dict(ticket.RULES)          # the order ticket's limits: one rulebook for the page and the engine
ENGINE = {
    "dayLossPct": 4.0,              # no new risk once the day's losses reach 4% of the account (two full losses)
    "drawdownPct": 10.0,            # halt, until a person lifts it, once the account is 10% below its peak
    "maxDeviationPct": 0.5,         # a limit price more than 0.5% from the last price is a typo or a stale quote
    "staleMinutes": 10,             # an intraday order needs a price at most 10 minutes old
    "staleDays": 4,                 # an end-of-day order needs a close at most 4 days old (a long weekend)
    "duplicateMinutes": 15,         # the same market and direction again within 15 minutes is a repeat
    "maxOrdersPerMinute": 5,        # far below the 10 a second that needs a registered algo (REAL_MONEY.md 8)
    "maxAllocCostPct": 1.0,         # an end-of-day order whose charges pass 1% of its value is too small to place
    "entryCutoffMinutes": 30,       # no new intraday trade with under 30 minutes left before the exit time
}
IST = "Asia/Kolkata"
HOURS = {"NSE": ("09:15", "15:30"), "MCX": ("09:00", "23:30")}
EXIT_BY = {"NSE": zerodha.EXIT_BY_IST, "MCX": "23:00"}
HALT = os.path.join("data", "real", "HALT")
LOG = os.path.join("logs", "risk_orders.csv")
DAILY = os.path.join("logs", "daily.csv")
BERLIN_ETF = os.path.join("logs", "berlin_etf.csv")
BERLIN_CALLS = os.path.join("data", "berlin", "telegram_calls.csv")
AKASH_CALLS = [os.path.join("data", "akash", f) for f in ("telegram_calls.csv", "claude_calls.csv")]
MARKET = os.path.join("data", "market")
ETF_SLIP = ticket.MARKETS["nifty"]["slip"]
MCX_SLIP = ticket.MARKETS["gold"]["slip"]
COLS = ["id", "stream", "at", "instrument", "side", "intent", "product", "price", "stop", "target", "quantity",
        "value", "risk_rs", "costs_rs", "cost_pct", "rr_after", "decision", "failed", "reason", "equity_before",
        "exit_at", "exit", "pnl_rs", "equity_after", "version", "logged_at"]
CURRENCIES = {"USD", "EUR", "GBP", "JPY", "AUD", "NZD", "CAD", "CHF", "CNH", "SGD", "HKD"}
CFDS = {"XAUUSD", "XAGUSD", "NAS100", "US30", "US500", "SPX500", "BTCUSD", "ETHUSD", "USOIL", "UKOIL", "GER40"}


# ---------------------------------------------------------------- words and numbers
def minutes(hhmm):
    h, m = str(hhmm).split(":")
    return int(h) * 60 + int(m)


def clock(m):
    if isinstance(m, str):
        m = minutes(m)
    h, mm = divmod(int(m), 60)
    return f"{(h + 11) % 12 + 1}:{mm:02d} {'am' if h < 12 else 'pm'}"


def utc(at):
    t = pd.Timestamp(at)
    return (t.tz_localize("UTC") if t.tzinfo is None else t).tz_convert("UTC")


def ist(at):
    return utc(at).tz_convert(IST)


def rs(x):
    return f"Rs {x:,.2f}" if abs(x) < 100 else f"Rs {x:,.0f}"


def to_tick(x, tick):
    """The ticket's toTick: JavaScript's Math.round, which rounds halves up (Python's round doesn't)."""
    return math.floor(x / tick + 1e-9 + 0.5) * tick


# ---------------------------------------------------------------- what can be traded
def market(instrument, product):
    """What the engine knows about an instrument for a product: {"ok": True, "exchange", "kind", "mult",
    "tick", "slip", "margin"}, or {"ok": False, "why": words}. Only what an Indian resident can trade
    through Zerodha, with prices the arena saves: the ETFs in zerodha.KIND and the MCX contracts in
    zerodha.MCX."""
    sym = str(instrument or "").upper().replace("/", "").strip()
    if sym in zerodha.KIND and product in ("MIS", "CNC"):
        return {"ok": True, "exchange": "NSE", "kind": zerodha.KIND[sym], "mult": 1, "tick": 0.01, "slip": ETF_SLIP,
                "margin": zerodha.MIS_MARGIN[sym] if product == "MIS" else 1.0, "unit": "unit"}
    if sym in zerodha.MCX and product == "MCX":
        return {"ok": True, "exchange": "MCX", "kind": "future", "mult": zerodha.MCX[sym][0], "tick": 1,
                "slip": MCX_SLIP, "margin": ticket.MCX_MARGIN, "unit": "lot"}
    return {"ok": False, "why": why_not(sym, product)}


def why_not(sym, product=""):
    if product == "OPT":
        return "options aren't in the engine yet: there are no intraday option prices to size or check an order"
    if sym in ("GOLD", "CRUDE", "SILVER") and not product:
        return (f"his {sym.lower()} levels are on a US exchange's price; the Indian route is MCX, and they "
                f"aren't mapped onto an MCX contract yet (REAL_MONEY.md 2.1)")
    if sym in zerodha.KIND or sym in zerodha.MCX:
        return f"{sym} can't be traded as {product or 'that product'}"
    if sym in CFDS:
        return f"{sym} is an offshore CFD: not allowed from India"
    if len(sym) == 6 and sym[:3] in CURRENCIES and sym[3:] in CURRENCIES:
        return f"{sym} is offshore forex: an Indian resident may trade only rupee pairs on Indian exchanges (FEMA)"
    if sym in ("CRUDE", "SILVER"):
        return (f"his {sym.lower()} levels are on a US exchange's price; the Indian route is MCX, and they "
                f"aren't mapped onto an MCX contract yet (REAL_MONEY.md 2.1)")
    if sym == "BTC":
        return "crypto: only through an Indian exchange (30% tax, 1% TDS), which the engine doesn't cover"
    if sym in ("NIFTY", "SENSEX", "BANKNIFTY"):
        return f"{sym} itself can't be bought: the engine trades NIFTYBEES"
    return (f"{sym or 'this'} isn't on the engine's list ({', '.join(sorted(zerodha.KIND))} and the MCX "
            f"contracts in zerodha.py)")


def nse_holidays():
    """NSE holidays from the event calendar (data/events/calendar.csv), as ISO dates; empty if unreadable."""
    try:
        import events
        cal = events.calendar(None)
        nse = cal[cal["market"].str.upper().str.contains("NSE") & (cal["kind"] == "holiday")]
        return frozenset(nse["date"].astype(str))
    except Exception:
        return frozenset()


def session(at, exchange, intraday_entry=False, holidays=frozenset()):
    """(ok, words): can an order go in at `at` on this exchange?"""
    t = ist(at)
    m = t.hour * 60 + t.minute
    if t.weekday() >= 5:
        return False, f"{t:%A} {t.day} {t:%b}: the market is shut"
    if exchange == "NSE" and t.date().isoformat() in holidays:
        return False, f"{t.day} {t:%b} {t.year} is an NSE holiday"
    opens, closes = HOURS[exchange]
    if m < minutes(opens) or m > minutes(closes):
        return False, f"{clock(m)} is outside {exchange}'s hours ({clock(opens)} to {clock(closes)})"
    if intraday_entry:
        last = minutes(EXIT_BY[exchange]) - ENGINE["entryCutoffMinutes"]
        if m > last:
            return False, (f"{clock(m)} is too late for a trade that has to close today: none after "
                           f"{clock(last)}")
    return True, f"{clock(m)} in India, inside {exchange}'s hours"


def halt_since(path=None, now=None):
    """When the kill switch was set, in UTC: None if data/real/HALT doesn't exist. The file's first line
    should be the date and time in India it applies from (2026-12-15 10:42); without one, from `now`."""
    path = path or HALT
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8", errors="replace") as f:
        first = f.readline().strip()
    try:
        t = pd.Timestamp(first)
        if pd.isna(t):
            raise ValueError
        return (t.tz_localize(IST) if t.tzinfo is None else t).tz_convert("UTC")
    except Exception:
        return utc(now if now is not None else pd.Timestamp.now(tz="UTC"))


# ---------------------------------------------------------------- the account
class Account:
    """One strategy's money in the engine: cash, units held, the day's tally and the drawdown halt."""

    def __init__(self, capital=None):
        self.capital = float(RULES["account"] if capital is None else capital)
        self.cash = self.capital
        self.held = {}
        self.peak = self.capital
        self.halted = ""
        self.day = None
        self.trades = self.losses = 0
        self.day_pnl = 0.0
        self.recent = []                 # (time, instrument, side) of approved orders

    def roll(self, at):
        d = ist(at).date()
        if d != self.day:
            self.day, self.trades, self.losses, self.day_pnl = d, 0, 0, 0.0

    def equity(self, prices=None):
        prices = prices or {}
        return self.cash + sum(q * prices[i] for i, q in self.held.items() if q and i in prices)

    def mark(self, equity, at):
        """Record the account's value at `at`; trips the drawdown halt. True if it tripped now."""
        self.peak = max(self.peak, equity)
        floor = self.peak * (1 - ENGINE["drawdownPct"] / 100)
        if not self.halted and equity <= floor + 1e-9:
            self.halted = (f"halted on {ist(at).day} {ist(at):%b %Y}: {rs(equity)} is "
                           f"{(1 - equity / self.peak) * 100:.1f}% below the peak of {rs(self.peak)}")
            return True
        return False


# ---------------------------------------------------------------- sizing, as the order ticket does it
def size_trade(price, stop, target, sign, info, product, account, risk_pct):
    """The order ticket's sums (ticket.py, compute()) for an order in the instrument's own prices: the
    quantity, what the stop loses and the target pays after slippage and Zerodha's charges."""
    tick, mult, slip, kind = info["tick"], info["mult"], info["slip"], info["kind"]
    stop = to_tick(stop, tick)
    target = to_tick(target, tick) if target else None
    entry_fill, stop_fill = price * (1 + sign * slip), stop * (1 - sign * slip)

    def outcome(n, exit_fill):
        a, b = n * mult * entry_fill, n * mult * exit_fill
        fees = zerodha.charges(a, b, product, kind) if sign > 0 else zerodha.charges(b, a, product, kind)
        return sign * (b - a) - fees["total"]

    limit = account * risk_pct / 100
    per_move = mult * abs(entry_fill - stop_fill)
    margin_lot = (info["margin"] * price * mult if product == "MCX"
                  else info["margin"] * price if product == "MIS" else price)
    by_risk = math.floor(limit / per_move + 1e-9) if per_move > 0 else 0
    by_money = math.floor(account / margin_lot + 1e-9)
    n = max(0, min(by_risk, by_money))
    while n > 0 and -outcome(n, stop_fill) > limit + 1e-9:
        n -= 1
    out = {"n": n, "limit": limit, "by_risk": by_risk, "by_money": by_money, "margin_lot": margin_lot,
           "stop": stop, "target": target, "entry_fill": entry_fill, "stop_fill": stop_fill,
           "loss_one": -outcome(1, stop_fill), "outcome": outcome}
    if n >= 1:
        at_stop, raw = outcome(n, stop_fill), n * mult * abs(price - stop)
        out.update(value=n * mult * price, at_stop=at_stop, raw=raw, costs=-at_stop - raw,
                   cost_pct=(-at_stop - raw) / raw * 100 if raw else float("inf"))
        if target is not None:
            out["at_target"] = outcome(n, target)
            out["rr_after"] = out["at_target"] / -at_stop if at_stop < 0 else float("inf")
    return out


# ---------------------------------------------------------------- the decision
def decide(order, acct, halt_at=None, holidays=frozenset()):
    """Decide one order for an account. `order` has id, at, instrument, side (buy/sell), intent (open, add,
    reduce, close), product (MIS, CNC, MCX or OPT), style (trade or allocation) and, as they apply, price,
    last and last_at (the latest price and its time), stop and target (a trade), weight or quantity (an
    allocation). Returns {"approved", "quantity", "checks": [(name, ok, words)], "failed", "reason", ...}.
    A check's ok is True, False (refuses the order) or None (a note)."""
    checks = []

    def check(name, ok, words):
        checks.append((name, ok, words))

    at = utc(order["at"])
    acct.roll(at)
    side = order["side"]
    sign = 1 if side == "buy" else -1
    product, style = order.get("product", ""), order.get("style", "trade")
    info = market(order.get("instrument"), product)
    out = {"quantity": 0, "value": None, "risk_rs": None, "costs_rs": None, "cost_pct": None, "rr_after": None}

    if order.get("intent") in ("close", "reduce"):
        held = acct.held.get(order["instrument"], 0)
        want = int(order.get("quantity") or held)
        qty = min(want, held)
        check("position", qty >= 1, f"sells {qty} of the {held} held" if qty >= 1 else "nothing held to sell")
        check("always allowed", None, "an order that closes or reduces a position is never refused by a limit or a halt")
        out["quantity"] = qty
        if qty >= 1 and order.get("price"):
            value = qty * float(order["price"])
            fees = zerodha.charges(0, value, product, info.get("kind", "equity_etf")) if info["ok"] else {"total": 0.0}
            out.update(value=value, costs_rs=fees["total"])
    else:
        kill = halt_at is not None and at >= halt_at
        check("kill switch", not kill, "the kill switch is on (data/real/HALT)" if kill else "off")
        check("drawdown halt", not acct.halted, acct.halted or
              f"inside the {ENGINE['drawdownPct']:g}% limit below the account's peak")
        check("market", info["ok"], info.get("why") or f"{order['instrument']} on {info['exchange']}")
        if info["ok"]:
            intraday = style == "trade" and product in ("MIS", "MCX")
            ok, words = session(at, info["exchange"], intraday_entry=intraday, holidays=holidays)
            check("session", ok, words)
            price, last = float(order["price"]), float(order["last"])
            age = at - utc(order["last_at"])
            most = (pd.Timedelta(minutes=ENGINE["staleMinutes"]) if style == "trade"
                    else pd.Timedelta(days=ENGINE["staleDays"]))
            fresh = pd.Timedelta(minutes=-1) <= age <= most
            mins = age.total_seconds() / 60
            check("fresh price", fresh, "the last price is from after the order" if age < pd.Timedelta(minutes=-1)
                  else f"the last price is {mins:,.0f} minutes old" + ("" if fresh else
                                                                     f": more than {most.total_seconds() / 60:,.0f}"))
            dev = abs(price - last) / last * 100 if last else float("inf")
            check("price check", dev <= ENGINE["maxDeviationPct"],
                  f"the order's price is {dev:.2f}% from the last price (most: {ENGINE['maxDeviationPct']:g}%)")
            if style == "trade":
                trade_checks(order, acct, info, sign, price, check, out)
            else:
                allocation_checks(order, acct, info, price, check, out)
            since = at - pd.Timedelta(minutes=ENGINE["duplicateMinutes"])
            repeat = [t for t, i, s in acct.recent if since <= t <= at and i == order["instrument"] and s == side]
            check("repeat", not repeat, "the same order went in at "
                  f"{clock(ist(repeat[-1]).hour * 60 + ist(repeat[-1]).minute)}: a repeat" if repeat else
                  f"no {side} of {order['instrument']} in the last {ENGINE['duplicateMinutes']} minutes")
            minute = [t for t, _, _ in acct.recent if at - pd.Timedelta(seconds=60) < t <= at]
            check("order rate", len(minute) < ENGINE["maxOrdersPerMinute"],
                  f"{len(minute)} orders in the last minute (most: {ENGINE['maxOrdersPerMinute']})")
    failed = [name for name, ok, _ in checks if ok is False]
    out.update(checks=checks, failed=failed, approved=not failed and out["quantity"] >= 1,
               reason=next((w for _, ok, w in checks if ok is False), ""))
    if not failed and out["quantity"] < 1:
        out["reason"] = "nothing to order"
    return out


def trade_checks(order, acct, info, sign, price, check, out):
    """A trade with a stop: the order ticket's checks, then the day's limits."""
    product = order["product"]
    stop = order.get("stop")
    if stop in (None, "") or pd.isna(stop):
        check("stop", False, "no stop: every trade needs one before it goes in")
        return
    stop = float(stop)
    if (stop - price) * sign >= 0:
        check("stop", False, f"the stop {stop:,.2f} is on the wrong side of the price {price:,.2f}")
        return
    check("stop", True, f"stop at {stop:,.2f}")
    if sign < 0 and product == "CNC":
        check("short", False, "a short can only be held for the day (MIS): no delivery shorts")
    target = order.get("target")
    target = float(target) if target not in (None, "") and not pd.isna(target) else None
    if target is not None and (target - price) * sign <= 0:
        check("target", False, f"the target {target:,.2f} is already passed at {price:,.2f}")
        target = None
    s = size_trade(price, stop, target, sign, info, product, acct.cash, RULES["riskPct"])
    if s["n"] < 1:
        if s["by_money"] < 1:
            check("size", False, f"not enough money for one {info['unit']}: it needs {rs(s['margin_lot'])} and "
                                 f"the account has {rs(acct.cash)}")
        else:
            check("size", False, f"even one {info['unit']} loses {rs(s['loss_one'])} at the stop, more than the "
                                 f"{RULES['riskPct']:g}% limit of {rs(s['limit'])}")
    else:
        out.update(quantity=s["n"], value=s["value"], risk_rs=-s["at_stop"], costs_rs=s["costs"],
                   cost_pct=s["cost_pct"])
        check("size", True, f"{s['n']} {info['unit']}{'' if s['n'] == 1 else 's'}, {rs(s['value'])}: the stop "
                            f"loses {rs(-s['at_stop'])}, inside {rs(s['limit'])}")
        check("costs", s["cost_pct"] <= RULES["maxCostPct"],
              f"charges and slippage are {s['cost_pct']:.0f}% of the money at risk (most: {RULES['maxCostPct']}%)")
        if product == "MIS" and s["value"] > acct.cash:
            check("leverage", None, f"the order is {s['value'] / acct.cash:.1f} times the account: Zerodha lends the "
                                    f"rest for the day")
        if target is not None:
            out["rr_after"] = s["rr_after"]
            check("reward", s["rr_after"] >= RULES["minRR"],
                  f"after costs the target pays {s['rr_after']:.2f} times what the stop loses (least: {RULES['minRR']})")
        else:
            check("reward", None, "no target, so the reward can't be weighed")
    check("trades today", acct.trades < RULES["maxTrades"],
          f"{acct.trades} trades today (most: {RULES['maxTrades']})")
    check("losses today", acct.losses < RULES["maxLosses"],
          f"{acct.losses} losing trades today (stop after {RULES['maxLosses']})")
    cap = acct.capital * ENGINE["dayLossPct"] / 100
    lost = max(0.0, -acct.day_pnl)
    check("day loss", lost < cap - 1e-9, f"{rs(lost)} lost today (stop at {rs(cap)}, "
                                         f"{ENGINE['dayLossPct']:g}% of the account)")


def allocation_checks(order, acct, info, price, check, out):
    """An end-of-day order towards a share of the account in one ETF: no borrowing, enough cash, and
    charges small next to the order."""
    weight = float(order.get("weight", 1.0))
    check("weight", 0 <= weight <= 1, f"{weight:.0%} of the account" + ("" if 0 <= weight <= 1 else
                                                                        ": more than 100% would borrow"))
    qty = int(order.get("quantity") or 0)
    product, kind = order["product"], info["kind"]
    while qty > 0 and qty * price + zerodha.charges(qty * price, 0, product, kind)["total"] > acct.cash + 1e-9:
        qty -= 1
    if qty < 1:
        check("money", False, f"{rs(acct.cash)} in cash doesn't buy one unit at {price:,.2f}")
        return
    value = qty * price
    fees = zerodha.charges(value, 0, product, kind)["total"]
    out.update(quantity=qty, value=value, costs_rs=fees, cost_pct=fees / value * 100)
    check("money", True, f"{qty} units, {rs(value)}, from {rs(acct.cash)} in cash")
    check("costs", fees / value * 100 <= ENGINE["maxAllocCostPct"],
          f"charges are {fees / value * 100:.2f}% of the order (most: {ENGINE['maxAllocCostPct']:g}%)")


# ---------------------------------------------------------------- the paper orders ("streams")
def read_csv(path):
    try:
        return pd.read_csv(path, dtype=str, keep_default_na=False)
    except (FileNotFoundError, pd.errors.EmptyDataError):
        return pd.DataFrame()


def num(x):
    try:
        v = float(x)
        return None if math.isnan(v) else v
    except (TypeError, ValueError):
        return None


def berlin_nifty_orders(path=None):
    """His Nifty calls as NIFTYBEES intraday trades, from the copy in logs/berlin_etf.csv (on time, calls
    book): the order goes in when the copy filled, at that price, with his stop and target on NIFTYBEES.
    Calls that never filled sent no order."""
    df = read_csv(path or BERLIN_ETF)
    if not len(df):
        return []
    df = df[(df["variant"] == "ontime") & (df["book"] == "calls") & (df["fill_at"] != "")]
    out = []
    for _, r in df.iterrows():
        out.append({"id": f"berlin-nifty:{r['id']}", "stream": "berlin-nifty", "at": utc(r["fill_at"]),
                    "instrument": "NIFTYBEES", "side": "buy" if r["side"] == "long" else "sell", "intent": "open",
                    "product": "MIS", "style": "trade", "price": num(r["fill"]), "last": num(r["fill"]),
                    "last_at": utc(r["fill_at"]), "stop": num(r["stop"]), "target": num(r["target"]),
                    "exit_at": r["exit_at"], "exit": num(r["exit"]), "outcome": r["outcome"]})
    return out


def blocked_call_orders(stream, paths, keep=lambda r: True):
    """Calls the engine can't place, as orders it refuses: one for each tagged call."""
    frames = [read_csv(p) for p in paths]
    df = pd.concat([f for f in frames if len(f)], ignore_index=True) if any(len(f) for f in frames) else pd.DataFrame()
    out = []
    for _, r in df.iterrows() if len(df) else ():
        if not keep(r) or not r.get("posted_at"):
            continue
        out.append({"id": f"{stream}:{r['id']}", "stream": stream, "at": utc(r["posted_at"]),
                    "instrument": r["instrument"], "side": {"long": "buy", "short": "sell"}.get(r.get("side", ""), "either"),
                    "intent": "open", "product": "OPT" if r.get("kind") == "option" else "",
                    "style": "trade"})
    return out


def holding_of(text):
    """An agent's holding from logs/daily.csv as (ETF, share of the account), (None, 0) for cash, or None
    when no ETF stands for it."""
    t = str(text).strip()
    if t in ("Cash", "Nothing overnight", ""):
        return (None, 0.0)
    m = re.fullmatch(r"(\d+(?:\.\d+)?)% (.+)", t)
    share, name = (float(m.group(1)) / 100, m.group(2)) if m else (1.0, t)
    etf = {"NIFTY 50": "NIFTYBEES", "NIFTYBEES": "NIFTYBEES", "GOLDBEES": "GOLDBEES", "SILVERBEES": "SILVERBEES"}.get(name)
    return (etf, share) if etf else None


def etf_closes(names, folder=None):
    folder = folder or MARKET
    out = {}
    for n in names:
        df = read_csv(os.path.join(folder, f"{n}.csv"))
        if len(df):
            out[n] = pd.Series(pd.to_numeric(df["Close"], errors="coerce").values, index=df["Date"]).dropna()
    return out


def agent_streams(path=None):
    """Which agents' holdings map onto ETFs the engine can trade: ({agent: [(date, etf, share)]}, {agent:
    why not}). F&O agents and anything holding something else are left out with the reason."""
    df = read_csv(path or DAILY)
    if not len(df):
        return {}, {}
    try:
        import fno_arena
        fno = set(fno_arena.RULES)
    except Exception:
        fno = set()
    keep, skip = {}, {}
    for agent, g in df.groupby("agent", sort=False):
        if agent in fno:
            skip[agent] = "an F&O agent: lots and margin the account doesn't have"
            continue
        held = [(d, holding_of(h)) for d, h in zip(g["date"], g["holding"])]
        bad = sorted({h for (_, x), h in zip(held, g["holding"]) if x is None})
        if bad:
            skip[agent] = f"no ETF stands for {', '.join(bad)}"
            continue
        keep[agent] = [(d, x[0], x[1]) for d, x in held]
    return keep, skip


def slug(agent):
    return "agent-" + re.sub(r"[^a-z0-9]+", "-", agent.lower()).strip("-")


# ---------------------------------------------------------------- the log
def read_log(path=None):
    df = read_csv(path or LOG)
    return {r["id"]: dict(r) for _, r in df.iterrows()} if len(df) else {}


def fmt(x, nd=2):
    if x is None or x == "" or (isinstance(x, float) and math.isnan(x)):
        return ""
    if isinstance(x, (pd.Timestamp, dt.datetime)):
        return utc(x).strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(x, float):
        return f"{x:.{nd}f}"
    return str(x)


def row_for(order, d, equity_before, now):
    return {"id": order["id"], "stream": order["stream"], "at": fmt(order["at"]), "instrument": order.get("instrument", ""),
            "side": order.get("side", ""), "intent": order.get("intent", ""), "product": order.get("product", ""),
            "price": fmt(order.get("price")), "stop": fmt(order.get("stop")), "target": fmt(order.get("target")),
            "quantity": str(d["quantity"]), "value": fmt(d.get("value")), "risk_rs": fmt(d.get("risk_rs")),
            "costs_rs": fmt(d.get("costs_rs")), "cost_pct": fmt(d.get("cost_pct"), 1), "rr_after": fmt(d.get("rr_after")),
            "decision": "approved" if d["approved"] else "refused", "failed": ";".join(d["failed"]),
            "reason": d["reason"], "equity_before": fmt(equity_before), "exit_at": "", "exit": "", "pnl_rs": "",
            "equity_after": "", "version": VERSION, "logged_at": fmt(now)}


def halt_row(stream, at, acct, equity, now):
    return {"id": f"{stream}:halt", "stream": stream, "at": fmt(at), "instrument": "", "side": "", "intent": "halt",
            "product": "", "price": "", "stop": "", "target": "", "quantity": "0", "value": "", "risk_rs": "",
            "costs_rs": "", "cost_pct": "", "rr_after": "", "decision": "halt", "failed": "drawdown halt",
            "reason": acct.halted, "equity_before": fmt(equity), "exit_at": "", "exit": "", "pnl_rs": "",
            "equity_after": fmt(equity), "version": VERSION, "logged_at": fmt(now)}


def replay(acct, row, prices=None):
    """Apply a logged row to an account, so the next decision starts where the log left off."""
    at = utc(row["at"])
    acct.roll(at)
    if row["decision"] == "halt":
        acct.halted = acct.halted or row["reason"]
        return
    if row["decision"] != "approved":
        return
    qty, inst = int(float(row["quantity"] or 0)), row["instrument"]
    acct.recent.append((at, inst, row["side"]))
    if row["intent"] in ("open", "add") and row["exit_at"] == "" and row["pnl_rs"] == "":     # an ETF bought to hold
        acct.cash -= float(row["value"] or 0) + float(row["costs_rs"] or 0)
        acct.held[inst] = acct.held.get(inst, 0) + qty
    elif row["intent"] in ("close", "reduce"):
        acct.cash += float(row["value"] or 0) - float(row["costs_rs"] or 0)
        acct.held[inst] = acct.held.get(inst, 0) - qty
    else:                                                                                       # a trade, opened and closed
        pnl = float(row["pnl_rs"] or 0)
        acct.cash += pnl
        acct.trades += 1
        acct.losses += pnl < 0
        acct.day_pnl += pnl
        acct.mark(acct.cash, at)


def settle_trade(order, d, acct):
    """What an approved trade made, with the engine's quantity: out at his exit, the stop or the target."""
    info = market(order["instrument"], order["product"])
    sign = 1 if order["side"] == "buy" else -1
    s = size_trade(order["price"], order["stop"], order.get("target"), sign, info, order["product"], acct.cash, RULES["riskPct"])
    n = d["quantity"]
    exit_ = float(order["exit"])
    fill = exit_ if order.get("outcome") == "target" else exit_ * (1 - sign * info["slip"])
    pnl = s["outcome"](n, fill)
    return round(pnl, 2)


def run(now=None, log_path=None, write=True):
    """Decide every paper order not yet in the log, in time order within each account, and add the new
    rows. Rows already logged are replayed, never redone. Returns the new rows."""
    now = utc(now if now is not None else pd.Timestamp.now(tz="UTC"))
    log_path = log_path or LOG
    logged = read_log(log_path)
    halt_at = halt_since(now=now)
    holidays = nse_holidays()
    new, waiting = [], {}

    def apply(stream_orders, acct):
        """Logged rows and new orders of one account, oldest first."""
        ids = {o["id"] for o in stream_orders}
        extra = [r for i, r in logged.items() if r["stream"] == stream_orders[0]["stream"] and i not in ids
                 and r["decision"] != "halt"] if stream_orders else []
        items = [(o["at"], 0, o["id"], o) for o in stream_orders] + [(utc(r["at"]), 0, r["id"], r) for r in extra]
        for _, _, oid, o in sorted(items, key=lambda x: (x[0], x[2])):
            if oid in logged:
                replay(acct, logged[oid])
                continue
            eq = acct.equity()
            d = decide(o, acct, halt_at, holidays)
            row = row_for(o, d, eq, now)
            if d["approved"] and o["style"] == "trade":
                if o.get("exit") is None:
                    break                                    # its result isn't known yet: later orders wait
                pnl = settle_trade(o, d, acct)
                row.update(exit_at=fmt(utc(o["exit_at"])) if o.get("exit_at") else "", exit=fmt(o["exit"]),
                           pnl_rs=fmt(pnl), equity_after=fmt(acct.cash + pnl))
            new.append(row)
            replay(acct, row)
            if acct.halted and f"{o['stream']}:halt" not in logged and not any(r["id"] == f"{o['stream']}:halt" for r in new):
                new.append(halt_row(o["stream"], o["at"], acct, acct.cash, now))

    # 1. His Nifty calls on NIFTYBEES
    orders = berlin_nifty_orders()
    if orders:
        apply(orders, Account())
    # 2. The ETF agents, one account each
    agents, _ = agent_streams()
    closes = etf_closes(["NIFTYBEES", "GOLDBEES", "SILVERBEES"])
    for agent, days in agents.items():
        stream = slug(agent)
        acct = Account()
        halted_logged = f"{stream}:halt" in logged
        prev = (None, 0.0)
        for date, etf, share in days:
            prices = {k: float(v.get(date)) for k, v in closes.items() if date in v.index}
            at = pd.Timestamp(f"{date} 15:29").tz_localize(IST).tz_convert("UTC")
            todo = []
            if (etf, share) != prev:
                for held, q in list(acct.held.items()):
                    if q and (held != etf):
                        todo.append({"intent": "close", "instrument": held, "side": "sell", "quantity": q})
                if etf:
                    todo.append({"intent": "target", "instrument": etf, "share": share})
            for t in todo:
                p = prices.get(t["instrument"])
                o = {"stream": stream, "at": at, "product": "CNC", "style": "allocation", "price": p, "last": p,
                     "last_at": at, "instrument": t["instrument"]}
                if t["intent"] == "close":
                    o.update(id=f"{stream}:{date}:sell-{t['instrument']}", side="sell", intent="close", quantity=t["quantity"])
                else:
                    have = acct.held.get(etf, 0)
                    if p is not None:
                        want = math.floor(share * acct.equity(prices) / p + 1e-9)
                        if want == have:
                            continue
                        if want > have:
                            o.update(id=f"{stream}:{date}:buy-{etf}", side="buy", intent="add" if have else "open",
                                     weight=share, quantity=want - have)
                        else:
                            o.update(id=f"{stream}:{date}:sell-{etf}", side="sell", intent="reduce", quantity=have - want)
                if p is None or any(prices.get(i) is None for i in acct.held if acct.held[i]):
                    waiting[stream] = f"waiting for the {t['instrument']} close of {date}"
                    break                                    # no close saved yet: this account waits for it
                if o["id"] in logged:
                    replay(acct, logged[o["id"]])
                    continue
                eq = acct.equity(prices)
                d = decide(o, acct, halt_at, holidays)
                row = row_for(o, d, eq, now)
                if d["approved"]:
                    row["equity_after"] = fmt(eq - (d.get("costs_rs") or 0))
                new.append(row)
                replay(acct, row)
            if stream in waiting:
                break
            prev = (etf, share)
            if halted_logged and not acct.halted and at >= utc(logged[f"{stream}:halt"]["at"]):
                acct.halted = logged[f"{stream}:halt"]["reason"]
            if prices:
                eq = acct.equity(prices)
                if acct.mark(eq, at) and not halted_logged and not any(r["id"] == f"{stream}:halt" for r in new):
                    new.append(halt_row(stream, at, acct, eq, now))
    # 3. Calls the engine can't place
    for stream, paths, keep in (
            ("berlin-other", [BERLIN_CALLS], lambda r: not (r.get("instrument") == "NIFTY" and r.get("kind") == "level")),
            ("akash", AKASH_CALLS, lambda r: True)):
        for o in sorted(blocked_call_orders(stream, paths, keep), key=lambda o: (o["at"], o["id"])):
            if o["id"] in logged or any(r["id"] == o["id"] for r in new):
                continue
            d = decide(o, Account(), halt_at, holidays)
            new.append(row_for(o, d, None, now))
    run.waiting = waiting
    if write and new:
        exists = os.path.exists(log_path) and os.path.getsize(log_path) > 0
        os.makedirs(os.path.dirname(log_path) or ".", exist_ok=True)
        with open(log_path, "a", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=COLS, lineterminator="\n")
            if not exists:
                w.writeheader()
            w.writerows(new)
    return new


# ---------------------------------------------------------------- what the page shows
STREAM_NAMES = {"berlin-nifty": "His Nifty calls on NIFTYBEES (intraday)", "berlin-other": "His other calls",
                "akash": "Akash's signals"}


def summary(log_path=None):
    """Per account: orders, approved, refused, the main reasons, the result on the account and whether it
    is halted; plus the kill switch. None when there's no log yet."""
    df = read_csv(log_path or LOG)
    if not len(df):
        return None
    agents, skipped = agent_streams()
    names = dict(STREAM_NAMES, **{slug(a): a for a in list(agents) + list(skipped)})
    closes = etf_closes(["NIFTYBEES", "GOLDBEES", "SILVERBEES"])
    latest = {k: float(v.iloc[-1]) for k, v in closes.items() if len(v)}
    out = []
    for stream, g in df.groupby("stream", sort=False):
        orders = g[g["decision"] != "halt"]
        refused = orders[orders["decision"] == "refused"]
        reasons = collections.Counter(r.split(";")[0] for r in refused["failed"] if r)
        acct = Account()
        for _, r in g.iterrows():
            replay(acct, dict(r))
        trades = orders[(orders["decision"] == "approved") & (orders["pnl_rs"] != "")]
        value = acct.equity(latest)
        out.append({"stream": stream, "name": names.get(stream, stream), "orders": len(orders),
                    "approved": int((orders["decision"] == "approved").sum()), "refused": len(refused),
                    "reasons": reasons.most_common(), "first_reason": refused["reason"].iloc[0] if len(refused) else "",
                    "trades": len(trades), "pnl": float(pd.to_numeric(trades["pnl_rs"]).sum()) if len(trades) else 0.0,
                    "value": value if stream not in ("berlin-other", "akash") else None,
                    "halted": acct.halted, "last": orders["at"].max() if len(orders) else "",
                    "placeable": stream not in ("berlin-other", "akash"),
                    "style": "blocked" if stream in ("berlin-other", "akash") else
                             "allocation" if stream.startswith("agent-") else "trade"})
    return {"streams": out, "kill": halt_since(), "skipped": skipped, "version": VERSION, "rules": RULES,
            "engine": ENGINE, "rows": len(df)}


# ---------------------------------------------------------------- command line
def main(argv=None):
    p = argparse.ArgumentParser(description="The paper arena's risk engine (paper only: it never places an order).")
    p.add_argument("--check", nargs=3, metavar=("INSTRUMENT", "SIDE", "PRICE"),
                   help="decide one order now, e.g. --check NIFTYBEES buy 288.20 --stop 287.60 --target 289.50")
    p.add_argument("--stop", type=float)
    p.add_argument("--target", type=float)
    p.add_argument("--product", default="MIS")
    p.add_argument("--account", type=float, default=RULES["account"])
    p.add_argument("--at", help="time in India (default: now)")
    a = p.parse_args(argv)
    if a.check:
        inst, side, price = a.check
        at = (pd.Timestamp(a.at).tz_localize(IST) if a.at else pd.Timestamp.now(tz=IST)).tz_convert("UTC")
        order = {"id": "check", "at": at, "instrument": inst.upper(), "side": side.lower(), "intent": "open",
                 "product": a.product.upper(), "style": "trade", "price": float(price), "last": float(price),
                 "last_at": at, "stop": a.stop, "target": a.target}
        d = decide(order, Account(a.account), halt_since(), nse_holidays())
        for name, ok, words in d["checks"]:
            print(f"  {'ok  ' if ok else 'NO  ' if ok is False else 'note'}  {name}: {words}")
        print(f"{'APPROVED' if d['approved'] else 'REFUSED'}: {d['quantity']} units" + (f" ({d['reason']})" if d["reason"] else ""))
        return 0 if d["approved"] else 1
    new = run()
    s = summary()
    print(f"risk engine {VERSION}: {len(new)} new decisions; kill switch {'ON' if s and s['kill'] is not None else 'off'}")
    for x in (s or {}).get("streams", []):
        print(f"  {x['name']}: {x['orders']} orders, {x['approved']} approved, {x['refused']} refused"
              + (f"; {x['reasons'][0][0]} most often" if x["reasons"] else "") + (f"; {x['halted']}" if x["halted"] else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
