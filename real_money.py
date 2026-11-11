"""
real_money.py - the real-money ledger: orders you placed yourself at Zerodha, next to the paper agent
they follow.

Nothing in this repository places an order. When you trade for real, each order, deposit, withdrawal
and fee is written down in data/real/orders.csv (Claude adds the row with the real-money-log skill,
from what you tell it or from the contract note). This file checks the ledger, works out what the
account is worth each day from the saved prices, and compares it with the paper agent given the same
money on the same days. The gap between the two is what real trading costs over the paper model:
whole units, real charges, idle cash, a worse price, an order placed late or not at all.

The file is only ever added to. A wrong row is corrected by a later row with the same id; a row is
cancelled by a later row with the same id and the action "void".

Columns: id, date, action, symbol, quantity, price, amount, charges, product, agent, note, added_at
  action    deposit, withdraw, buy, sell, fee (money Zerodha takes that isn't part of one order, such
            as the yearly account charge or a square-off charge) or void
  date      the day it happened in India, YYYY-MM-DD
  quantity, price   for a buy or a sale: whole units (lots for a future) and the average price
  amount    for a deposit, a withdrawal or a fee: rupees
  charges   everything charged on that order, from the contract note. Left empty, it is estimated
            with zerodha.py and shown as an estimate.
  product   CNC (delivery, the default), MIS (intraday) or MCX (a commodity future)
  agent     the paper agent this money follows. On a deposit it decides what the account is compared with.
  added_at  when the row was written (UTC)

Everything in this repository is public, this file included: never put a client id, PAN, bank or
contact detail in it.

Run:  python real_money.py                       the account today
      python real_money.py --check               check the ledger; exits with 1 if something is wrong
      python real_money.py --check --base DIR    also check that rows were only added to DIR's copy
      python real_money.py --add deposit 5000 --agent "Nifty-gold switch"
      python real_money.py --add buy GOLDBEES 40 121.35 --charges 1.87 --agent "Nifty-gold switch"
      python real_money.py --add void --id 3 --note "typed twice"
FOR LEARNING ONLY. Not investment advice. This file never places an order.
"""

import argparse
import csv
import datetime as dt
import os
import re
import sys

import pandas as pd

import zerodha

FILE = os.path.join("data", "real", "orders.csv")
COLS = ["id", "date", "action", "symbol", "quantity", "price", "amount", "charges", "product", "agent", "note",
        "added_at"]
ACTIONS = ("deposit", "withdraw", "buy", "sell", "fee", "void")
PRODUCTS = ("CNC", "MIS", "MCX")
DAILY = os.path.join("logs", "daily.csv")              # the paper agents' saved daily values
PRICE_DIR = os.path.join("data", "market")             # saved daily closes: NIFTYBEES, GOLDBEES, SILVERBEES
CALENDAR = "NIFTYBEES"                                 # its saved days are NSE's trading days
IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
PRIVATE = re.compile(r"\b[A-Z]{5}[0-9]{4}[A-Z]\b|\d{9,}|[\w.+-]+@[\w-]+\.\w+")   # a PAN, a long number, an email


def today():
    return dt.datetime.now(IST).date()


def read(path=FILE):
    if not os.path.exists(path):
        return pd.DataFrame(columns=COLS)
    return pd.read_csv(path, dtype=str, keep_default_na=False)


def number(x):
    try:
        v = float(str(x).replace(",", ""))
        return v if v == v and abs(v) != float("inf") else None
    except (TypeError, ValueError):
        return None


def whole(x):
    v = number(x)
    return int(v) if v is not None and v == int(v) else None


def settled(df):
    """The rows that count: the last row for each id, without the cancelled ones, in date order."""
    if not len(df):
        return df
    last = df.drop_duplicates("id", keep="last")
    last = last[last["action"] != "void"].copy()
    last["_n"] = last["id"].map(lambda i: whole(i) or 0)
    return last.sort_values(["date", "_n"], kind="stable").drop(columns="_n")


def product_of(row):
    return row["product"] or "CNC"


def multiplier(row):
    return zerodha.MCX[row["symbol"]][0] if product_of(row) == "MCX" else 1


def order_charges(row):
    """(rupees charged on a buy or a sale, whether that's an estimate)."""
    given = number(row["charges"])
    if given is not None:
        return given, False
    value = number(row["quantity"]) * number(row["price"]) * multiplier(row)
    product = product_of(row)
    buy, sell = (value, 0) if row["action"] == "buy" else (0, value)
    return zerodha.cost(buy, sell, product, zerodha.kind_of(row["symbol"], product)), True


# ------------------------------------ the account ---------------------------------
def trade(p, signed, price):
    """Add a buy (signed > 0) or a sale to one position {units, avg}. Returns the profit per unit of
    quoted price on whatever part of the position it closed."""
    units, closed_pnl = p["units"], 0.0
    if units and (units > 0) != (signed > 0):                    # closes some or all of it
        closed = min(abs(signed), abs(units))
        closed_pnl = (price - p["avg"]) * closed * (1 if units > 0 else -1)
        p["units"] = units + signed
        if abs(signed) > abs(units):
            p["avg"] = price                                     # went through zero: the rest is a new position
        elif p["units"] == 0:
            p["avg"] = 0.0
    else:                                                        # opens or adds
        p["avg"] = (p["avg"] * abs(units) + price * abs(signed)) / (abs(units) + abs(signed))
        p["units"] = units + signed
    return closed_pnl


def replay(df):
    """Walk the ledger in date order. Returns one snapshot per ledger day, oldest first:
    {date, cash, put_in, charges, realised, estimated, positions: {symbol: {units, avg, future, mult, last}}}."""
    state = {"cash": 0.0, "put_in": 0.0, "charges": 0.0, "realised": 0.0, "estimated": 0}
    positions, days = {}, []
    rows = settled(df)
    for date, part in rows.groupby("date", sort=True):
        for _, r in part.iterrows():
            a = r["action"]
            if a in ("deposit", "withdraw"):
                sign = 1 if a == "deposit" else -1
                state["cash"] += sign * number(r["amount"])
                state["put_in"] += sign * number(r["amount"])
            elif a == "fee":
                state["cash"] -= number(r["amount"])
                state["charges"] += number(r["amount"])
            else:
                qty, price, mult = whole(r["quantity"]), number(r["price"]), multiplier(r)
                fees, estimate = order_charges(r)
                state["cash"] -= fees
                state["charges"] += fees
                state["estimated"] += int(estimate)
                p = positions.setdefault(r["symbol"], {"units": 0, "avg": 0.0, "future": product_of(r) == "MCX",
                                                       "mult": mult, "last": price})
                signed = qty if a == "buy" else -qty
                gain = trade(p, signed, price) * mult
                p["last"] = price
                state["realised"] += gain
                if p["future"]:
                    state["cash"] += gain                        # a future moves only its profit or loss
                else:
                    state["cash"] -= signed * price              # shares and ETFs are paid for in full
        days.append({"date": pd.Timestamp(date), **state,
                     "positions": {s: dict(p) for s, p in positions.items() if p["units"]}})
    return days


def closes(symbol):
    """Saved daily closes for a symbol (data/market/<SYMBOL>.csv), or None if there aren't any."""
    path = os.path.join(PRICE_DIR, f"{symbol}.csv")
    if not os.path.exists(path):
        return None
    try:
        df = pd.read_csv(path, index_col=0, parse_dates=True)
        return df["Close"].dropna().sort_index()
    except Exception:
        return None


def paper_values(path=DAILY):
    """Each paper agent's saved daily value (logs/daily.csv): a table of dates by agent."""
    if not os.path.exists(path):
        return pd.DataFrame()
    log = pd.read_csv(path, usecols=["date", "agent", "value"])
    log["date"] = pd.to_datetime(log["date"])
    return log.pivot_table(index="date", columns="agent", values="value", aggfunc="last").sort_index()


def paper_curve(rows, days, paper):
    """What the same deposits and withdrawals would be worth in the paper agents named on them: each one
    joins its agent at that day's close (the agent's next saved day if there isn't one yet). Money with no
    agent, or an agent without saved values, is carried at its own amount. Returns (series, notes)."""
    held, flat, notes = [], [], []                       # held: (agent, date it joined, units of the agent's value)
    for _, r in rows[rows["action"].isin(("deposit", "withdraw"))].iterrows():
        sign = 1 if r["action"] == "deposit" else -1
        amount, day, agent = sign * number(r["amount"]), pd.Timestamp(r["date"]), r["agent"]
        if agent and agent in paper.columns and paper[agent].notna().any():
            series = paper[agent].dropna()
            after = series[series.index >= day]
            if len(after):
                held.append((agent, after.index[0], amount / after.iloc[0], day, amount))
                continue
            flat.append((day, amount))                   # its agent has no value for that day yet
            continue
        if agent:
            notes.append(f"No saved paper values for “{agent}”, so that money is compared at its own amount.")
        flat.append((day, amount))
    out = []
    for d in days:
        total = sum(a for day, a in flat if day <= d)
        for agent, joined, units, day, amount in held:
            if day > d:
                continue
            if joined > d:
                total += amount                          # deposited, the agent's close not in yet
            else:
                total += units * paper[agent].dropna().loc[:d].iloc[-1]
        out.append(total)
    return pd.Series(out, index=days, dtype=float), sorted(set(notes))


def summary(path=FILE):
    """Everything the page and the command line show about the real account."""
    df = read(path)
    rows = settled(df)
    out = {"started": bool(len(rows)), "rows": rows, "warnings": []}
    if not len(rows):
        return out
    snaps = replay(df)
    first = snaps[0]["date"]
    calendar = closes(CALENDAR)
    price_days = calendar.index[calendar.index >= first] if calendar is not None else pd.DatetimeIndex([])
    days = pd.DatetimeIndex(sorted(set(price_days) | {s["date"] for s in snaps}))
    series = {s: closes(s) for snap in snaps for s in snap["positions"]}

    def price(symbol, day, p):
        saved = series.get(symbol)
        if saved is not None and not p["future"]:
            upto = saved.loc[:day]
            if len(upto):
                return float(upto.iloc[-1]), True
        return p["last"], False

    def worth(snap, day):
        total = snap["cash"]
        for s, p in snap["positions"].items():
            px, _ = price(s, day, p)
            total += (px - p["avg"]) * p["units"] * p["mult"] if p["future"] else px * p["units"]
        return total

    values, put_in, i = [], [], 0
    for d in days:
        while i + 1 < len(snaps) and snaps[i + 1]["date"] <= d:
            i += 1
        values.append(worth(snaps[i], d))
        put_in.append(snaps[i]["put_in"])
    last, asof = snaps[-1], days[-1]
    paper, notes = paper_curve(rows, days, paper_values())
    out["warnings"] += notes
    holdings = []
    for s, p in sorted(last["positions"].items()):
        px, priced = price(s, asof, p)
        gain = (px - p["avg"]) * p["units"] * p["mult"]
        holdings.append({"symbol": s, "units": p["units"], "avg": p["avg"], "price": px, "priced": priced,
                         "future": p["future"], "value": gain if p["future"] else px * p["units"], "gain": gain})
        if not priced:
            out["warnings"].append(f"No saved prices for {s}: it is valued at your last trade price.")
    agents = rows.loc[rows["action"] == "deposit"].groupby("agent")["amount"].apply(lambda a: sum(number(x) for x in a))
    out.update(first=first, asof=asof, priced_to=calendar.index[-1] if calendar is not None and len(calendar) else None,
               put_in=last["put_in"], value=values[-1], cash=last["cash"],
               pnl=values[-1] - last["put_in"], charges=last["charges"], estimated=last["estimated"],
               realised=last["realised"], holdings=holdings, paper=float(paper.iloc[-1]),
               followed={a: v for a, v in agents.items() if a},
               series=pd.DataFrame({"value": values, "put_in": put_in, "paper": paper.values}, index=days))
    out["pnl_pct"] = out["pnl"] / last["put_in"] if last["put_in"] > 0 else 0.0
    return out


# ------------------------------------- checking -----------------------------------
def check(path=FILE, base=None):
    """Problems with the ledger, as sentences. An empty list means it looks fine."""
    rows, days = problems_in(path, base)
    return rows + days


def problems_in(path=FILE, base=None):
    """(problems with a row or the file, problems with a day's totals). The second kind, more sold than
    held or more spent than the account had by the end of a day, is also what half of an intraday trade
    looks like before its other half is written down."""
    problems = []
    if not os.path.exists(path):
        return [f"{path} doesn't exist"], []
    with open(path, encoding="utf-8", newline="") as f:
        lines = f.read().splitlines()
    if not lines or lines[0].split(",") != COLS:
        return [f"the first line must be exactly: {','.join(COLS)}"], []
    if base:
        old_path = os.path.join(base, os.path.basename(path)) if os.path.isdir(base) else base
        if os.path.exists(old_path):
            with open(old_path, encoding="utf-8", newline="") as f:
                old = f.read().splitlines()
            if lines[:len(old)] != old:
                problems.append("rows were changed or removed: the ledger is only ever added to")
    try:
        df = read(path)
    except Exception as exc:
        return problems + [f"the file can't be read as a table: {exc}"], []
    seen, last_added = set(), None
    for n, r in enumerate(df.to_dict("records"), start=2):
        where = f"line {n}"
        if whole(r["id"]) is None or whole(r["id"]) < 1:
            problems.append(f"{where}: id must be a whole number from 1")
            continue
        where = f"line {n} (id {r['id']})"
        try:
            day = dt.date.fromisoformat(r["date"])
            if day > today():
                problems.append(f"{where}: the date {r['date']} is in the future")
        except ValueError:
            problems.append(f"{where}: the date must look like 2026-12-15")
        try:
            added = pd.Timestamp(r["added_at"])
            if added.tzinfo is None:
                raise ValueError
            if last_added is not None and added < last_added:
                problems.append(f"{where}: added_at is earlier than the row above it")
            last_added = added
        except (ValueError, TypeError):
            problems.append(f"{where}: added_at must be a UTC time like 2026-12-15T10:05:00Z")
        a = r["action"]
        if a not in ACTIONS:
            problems.append(f"{where}: action must be one of {', '.join(ACTIONS)}")
            continue
        if a == "void":
            if r["id"] not in seen:
                problems.append(f"{where}: there is no earlier row with id {r['id']} to cancel")
        elif a in ("buy", "sell"):
            if not re.fullmatch(r"[A-Z0-9&-]+", r["symbol"]):
                problems.append(f"{where}: symbol must be the exchange's code in capitals, such as GOLDBEES")
            if whole(r["quantity"]) is None or whole(r["quantity"]) < 1:
                problems.append(f"{where}: quantity must be a whole number of units")
            if number(r["price"]) is None or number(r["price"]) <= 0:
                problems.append(f"{where}: price must be the average price per unit")
            if r["amount"]:
                problems.append(f"{where}: a buy or a sale has no amount: it is quantity times price")
            if r["charges"] and (number(r["charges"]) is None or number(r["charges"]) < 0):
                problems.append(f"{where}: charges must be rupees, or empty to estimate them")
            if product_of(r) not in PRODUCTS:
                problems.append(f"{where}: product must be {', '.join(PRODUCTS)} or empty (CNC)")
            elif product_of(r) == "MCX" and r["symbol"] not in zerodha.MCX:
                problems.append(f"{where}: {r['symbol']} isn't an MCX contract zerodha.py knows "
                                f"({', '.join(zerodha.MCX)})")
        else:
            if number(r["amount"]) is None or number(r["amount"]) <= 0:
                problems.append(f"{where}: amount must be rupees, more than 0")
            if r["symbol"] or r["quantity"] or r["price"]:
                problems.append(f"{where}: a {a} has only an amount")
        if PRIVATE.search(r["note"]) or PRIVATE.search(r["agent"]):
            problems.append(f"{where}: the note looks like it holds a PAN, an account, order or phone number, or "
                            f"an email address. This file is public: leave those out")
        seen.add(r["id"])
    if problems:
        return problems, []
    totals = []
    for snap in replay(df):
        day = f"{snap['date'].date()}"
        if snap["cash"] < -1:
            totals.append(f"on {day} the orders spend ₹{-snap['cash']:,.2f} more than the account held: "
                          f"a deposit is missing, or a quantity or price is wrong")
        for s, p in snap["positions"].items():
            if p["units"] < 0 and not p["future"]:
                totals.append(f"on {day} more {s} was sold than the account held ({-p['units']} units short at "
                              f"the end of the day): shares and ETFs can only be short within a day")
    return problems, totals


# -------------------------------------- adding ------------------------------------
def add(args, path=FILE):
    """Add one row, after checking that the ledger is still sound with it. Returns (the row, a warning
    or ""), or raises. A correction (--id) keeps the date, agent and product of the row it corrects
    unless they are given again. Half of an intraday (MIS) trade is saved with a warning that the day
    isn't square yet; anything else that doesn't add up is refused."""
    if os.path.exists(path):
        broken, uneven = problems_in(path)
        if broken:
            raise ValueError("the ledger has problems already: " + "; ".join(broken))
    df = read(path)
    ids = [whole(i) for i in df["id"]] if len(df) else []
    if args.id and args.id not in ids:
        raise ValueError(f"there is no row with id {args.id} to correct")
    was = df[df["id"] == str(args.id)].iloc[-1] if args.id else {}
    row = {c: "" for c in COLS}
    row.update(id=str(args.id if args.id else max(ids, default=0) + 1),
               date=args.date or was.get("date") or today().isoformat(), action=args.action,
               agent=args.agent if args.agent is not None else was.get("agent", ""), note=args.note or "",
               added_at=pd.Timestamp.now(tz="UTC").strftime("%Y-%m-%dT%H:%M:%SZ"))
    values = list(args.values)
    if args.action in ("buy", "sell"):
        if len(values) != 3:
            raise ValueError(f"{args.action} needs a symbol, a quantity and a price")
        row.update(symbol=values[0].upper(), quantity=values[1], price=values[2],
                   product=args.product or was.get("product") or "CNC",
                   charges="" if args.charges is None else str(args.charges))
    elif args.action == "void":
        if not args.id or values:
            raise ValueError("void needs --id, the row to cancel, and nothing else")
        row["agent"] = ""
    else:
        if len(values) != 1:
            raise ValueError(f"{args.action} needs an amount in rupees")
        row["amount"] = values[0]
    os.makedirs(os.path.dirname(path), exist_ok=True)
    existed = os.path.exists(path)
    before = open(path, encoding="utf-8").read() if existed else None
    with open(path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=COLS, lineterminator="\n")
        if not existed:
            writer.writeheader()
        writer.writerow(row)
    broken, uneven = problems_in(path)
    intraday = lambda r: r.get("action") in ("buy", "sell") and (r.get("product") or "CNC") == "MIS"
    half = intraday(row) or (row["action"] == "void" and intraday(was))      # the other leg may come next
    if broken or (uneven and not half):                  # put the file back exactly as it was
        if existed:
            with open(path, "w", encoding="utf-8", newline="") as f:
                f.write(before)
        else:
            os.remove(path)
        raise ValueError("; ".join(broken + uneven))
    return row, "; ".join(uneven)


# -------------------------------------- report ------------------------------------
def rupees(x, signed=False):
    sign = ("+" if x >= 0 else "-") if signed else ("-" if x < 0 else "")
    return f"{sign}Rs {abs(x):,.2f}"


def report(path=FILE):
    s = summary(path)
    if not s["started"]:
        print("No real orders yet. data/real/orders.csv holds only its header.")
        return
    prices = f"prices up to {s['priced_to'].date()}" if s["priced_to"] is not None else "no saved prices"
    print(f"Real account on {s['asof'].date()}, {prices} (first row {s['first'].date()})")
    print(f"  Put in        {rupees(s['put_in'])}")
    print(f"  Worth now     {rupees(s['value'])}  ({rupees(s['pnl'], True)}, {s['pnl_pct']:+.2%})")
    print(f"  Cash          {rupees(s['cash'])}")
    print(f"  Charges paid  {rupees(s['charges'])}" + (f"  ({s['estimated']} orders estimated)" if s["estimated"] else ""))
    print(f"  Paper agent with the same money: {rupees(s['paper'])}  (real is {rupees(s['value'] - s['paper'], True)} against it)")
    for h in s["holdings"]:
        unit = "lots" if h["future"] else "units"
        print(f"  {h['symbol']}: {h['units']} {unit} at {h['avg']:,.2f}, now {h['price']:,.2f}"
              f"{'' if h['priced'] else ' (your last trade price)'}: {rupees(h['gain'], True)}")
    for w in s["warnings"]:
        print(f"  ! {w}")


def main():
    parser = argparse.ArgumentParser(description="The real-money ledger.")
    parser.add_argument("--check", action="store_true", help="check the ledger")
    parser.add_argument("--base", help="a copy of the ledger (or its folder) from before the edit")
    parser.add_argument("--add", dest="action", choices=ACTIONS, help="add a row")
    parser.add_argument("values", nargs="*", help="buy/sell: SYMBOL QUANTITY PRICE; deposit/withdraw/fee: AMOUNT")
    parser.add_argument("--charges", type=float, help="rupees charged on the order (from the contract note)")
    parser.add_argument("--product", choices=PRODUCTS, help="CNC (default), MIS or MCX")
    parser.add_argument("--agent", help="the paper agent this money follows")
    parser.add_argument("--date", help="the day it happened, YYYY-MM-DD (default: today in India)")
    parser.add_argument("--note", help="a short note; nothing private")
    parser.add_argument("--id", type=int, help="correct or cancel the row with this id")
    args = parser.parse_args()
    if args.check:
        problems = check(base=args.base)
        for p in problems:
            print(f"  ! {p}")
        print(f"{FILE}: " + ("looks fine." if not problems else f"{len(problems)} problem(s)."))
        sys.exit(1 if problems else 0)
    if args.action:
        try:
            row, uneven = add(args)
        except ValueError as exc:
            print(f"Not saved: {exc}")
            sys.exit(1)
        print("Saved: " + ", ".join(f"{k}={v}" for k, v in row.items() if v))
        if uneven:
            print(f"  ! The day isn't square yet: {uneven}. Add the other half of the day's trade.")
    report()


if __name__ == "__main__":
    main()
