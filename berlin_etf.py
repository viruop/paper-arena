"""
berlin_etf.py - Trade Like Berlin's Nifty calls again, on the instrument a small account can trade.

The record in logs/berlin_calls.csv scores his Nifty calls on the Nifty 50 index itself, which nobody
can buy. This copy asks what following the same calls would have made with NIFTYBEES (an ETF that
tracks Nifty) at Zerodha, after Zerodha's real charges. It is a check on top of the record and never
changes it.

How a call is copied (each uses Rs 10,000 of NIFTYBEES, in whole units):
  - Only calls already scored in the record are copied, so his exits and stop moves are final.
  - His Nifty levels become NIFTYBEES prices through the ratio of the two at the first 5-minute bar
    after his post (NIFTYBEES open / Nifty open), rounded to a paisa: what a follower converting the
    levels at that moment would have used. The orders then work on NIFTYBEES's own prices, which
    wander a little around Nifty during the day.
  - Entry, stop, target and his later posts follow the record's rules (berlin_calls.score_level), with
    one change: an intraday trade is closed at 3:10 pm IST. Zerodha closes open intraday positions
    itself from 3:25 pm and charges for it, and Nifty's own shares stop trading at 3:15 pm.
  - Every fill except a target (a limit order) loses 0.015% to the spread and slippage.
  - Charges are Zerodha's (zerodha.py): an intraday (MIS) trade, or delivery (CNC) for a positional
    long that is held overnight. A short can only be held for the day, so a positional short isn't copied.
  - Each call is also copied 15 and 30 minutes late, converting the levels at that later moment and
    aiming at the on-time trade's target.
Options trades are copied as a plain NIFTYBEES trade in his direction (the record does the same on the
index), in a book of their own.

Results go to logs/berlin_etf.csv, once per call, and are never rewritten.

Run:  python berlin_etf.py          (the nightly run calls main() from berlin_calls.py)
FOR LEARNING ONLY. Paper trading; no real orders. Not investment advice.
"""

import math
import os
import sys

import pandas as pd

import berlin_calls as bc
import zerodha

ETF = "NIFTYBEES"
SYMBOL = "NIFTYBEES.NS"                 # Yahoo's name for it
RESULTS = os.path.join("logs", "berlin_etf.csv")
COLS = ["id", "variant", "book", "side", "product", "ratio", "units", "fill_at", "fill", "stop", "target",
        "exit_at", "exit", "outcome", "move_rs", "slip_rs", "charges_rs", "pnl_rs", "pct", "r", "scored_at"]
POSITION = 10000.0                      # rupees of NIFTYBEES per call
SLIP = 0.00015                          # lost on each fill to the spread and slippage (not on a target)
CLOSE_BY_UTC = "09:40"                  # 3:10 pm IST: intraday trades are out by then (zerodha.EXIT_BY_IST)
SESSION_OPEN_UTC = "03:45"              # 9:15 am IST
VARIANTS = (("ontime", 0), ("late15", 15), ("late30", 30))
GIVE_UP_DAYS = 58                       # Yahoo keeps 5-minute prices for 60 days: after that a call can't be copied


def read_results(path=RESULTS):
    if not os.path.exists(path):
        return pd.DataFrame(columns=COLS)
    return pd.read_csv(path, dtype=str, keep_default_na=False)


def book_of(call):
    """"calls" for a call with levels, "options" for an options trade copied in his direction, or None."""
    if call["instrument"] != "NIFTY":
        return None
    if call["kind"] == "level" and call["scorable"] == "yes":
        return "calls"
    if call["scorable"] != "yes" and bc.option_on_underlying(call):
        return "options"
    return None


def ist_day(t):
    return t.tz_convert("Asia/Kolkata").date()


def ratio(etf, nifty, at, same_day=True):
    """NIFTYBEES / Nifty at the first NIFTYBEES bar that starts at or after `at`: (ratio, that bar's time).
    Uses both opens; if Nifty has no bar then, its last close in the 15 minutes before. (None, None) if
    either price is missing, or (same_day) if that bar isn't on the day of `at`."""
    after = etf[etf.index >= at]
    if after.empty:
        return None, None
    t0 = after.index[0]
    if same_day and ist_day(t0) != ist_day(at):
        return None, None
    if t0 in nifty.index:
        index = nifty.at[t0, "Open"]
    else:
        near = nifty[(nifty.index < t0) & (nifty.index >= t0 - pd.Timedelta(minutes=15))]
        if near.empty:
            return None, None
        index = near["Close"].iloc[-1]
    return float(after["Open"].iloc[0]) / float(index), t0


def covered(etf, begin, cut, share=0.9):
    """Are the day's NIFTYBEES bars there from `begin` to the 3:10 pm close? At least `share` of the
    5-minute bars, so a day Yahoo sent only part of is never scored as if it were whole."""
    opens = pd.Timestamp(f"{cut.date()} {SESSION_OPEN_UTC}", tz="UTC")
    first = max(begin.ceil("5min"), opens)
    slots = int((cut - first) / pd.Timedelta(minutes=5))
    have = int(((etf.index >= first) & (etf.index < cut)).sum())
    return slots <= 0 or have >= share * slots


def scaled(value, k):
    v = bc.num(value)
    return "" if v is None else f"{round(v * k, 2):.2f}"


def convert(call, k, book):
    """His call with every Nifty level turned into a NIFTYBEES price."""
    out = dict(call)
    if book == "options":               # direction only, as score_option does on the index
        out.update(entry_type="market", entry="", stop="", target="", rr="")
    else:
        out.update(entry=scaled(call["entry"], k), stop=scaled(call["stop"], k), target=scaled(call["target"], k))
    out["price_ref"] = ""
    return out


def convert_updates(updates, k):
    """His later posts about the call, with their Nifty levels turned into NIFTYBEES prices."""
    out = []
    for u in updates:
        u = dict(u)
        if str(u.get("price", "")).strip().lower() != "entry":
            u["price"] = scaled(u.get("price"), k)
        u["trigger"] = scaled(u.get("trigger"), k)
        out.append(u)
    return out


def money(side, product, fill, exit_, outcome, stop):
    """Rupees on one copied trade: (units, the move itself, lost to slippage, charges, what's left)."""
    units = math.floor(POSITION / fill)
    sign = 1 if side == "long" else -1
    entry_px = fill * (1 + sign * SLIP)
    exit_px = exit_ if outcome == "target" else exit_ * (1 - sign * SLIP)
    buy, sell = (entry_px, exit_px) if sign > 0 else (exit_px, entry_px)
    move = sign * units * (exit_ - fill)
    slip = move - units * (sell - buy)
    fees = zerodha.cost(units * buy, units * sell, product, zerodha.kind_of(ETF))
    return units, move, slip, fees, move - slip - fees


def row(call, variant, book, now, outcome, k=None, res=None):
    """One line of logs/berlin_etf.csv: a trade (res: the row score_level returned) or the reason for none."""
    out = {c: "" for c in COLS}
    out.update(id=call["id"], variant=variant, book=book, side=call["side"], outcome=outcome, scored_at=now,
               ratio="" if k is None else f"{k:.7f}", units=0, move_rs=0, slip_rs=0, charges_rs=0, pnl_rs=0,
               pct=0, r=0)
    if res is None:
        return out
    fill, exit_, stop = float(res["fill"]), float(res["exit"]), float(res["stop"])
    same_day = ist_day(bc.utc(res["fill_at"])) == ist_day(bc.utc(res["exit_at"]))
    product = "MIS" if call["horizon"] == "intraday" or same_day else "CNC"
    units, move, slip, fees, net = money(res["side"], product, fill, exit_, res["outcome"], stop)
    if units < 1:
        out["outcome"] = "too small"
        return out
    out.update(side=res["side"], product=product, units=units, fill_at=res["fill_at"], fill=f"{fill:.2f}",
               stop=f"{stop:.2f}", target="" if res["target"] == "" else f"{float(res['target']):.2f}",
               exit_at=res["exit_at"], exit=f"{exit_:.2f}", outcome=res["outcome"], move_rs=round(move, 2),
               slip_rs=round(slip, 2), charges_rs=round(fees, 2), pnl_rs=round(net, 2),
               pct=round(net / (units * fill), 5), r=round(net / (units * abs(fill - stop)), 3))
    return out


def copy_call(call, etf, nifty, calls, updates):
    """Every line for one call: on time, 15 and 30 minutes late. None if NIFTYBEES prices don't cover it yet."""
    book, now = book_of(call), pd.Timestamp.now(tz="UTC").strftime("%Y-%m-%dT%H:%M:%SZ")
    posted = bc.utc(call["posted_at"])
    if call["horizon"] != "intraday" and call["side"] == "short":
        return [row(call, "ontime", book, now, "short can't be held overnight")]
    cut = pd.Timestamp(f"{posted.date()} {CLOSE_BY_UTC}", tz="UTC")
    too_old = posted < pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=GIVE_UP_DAYS)
    rows, aim = [], None
    for variant, late in VARIANTS:
        begin = posted + pd.Timedelta(minutes=late)
        intraday = call["horizon"] == "intraday"
        if intraday and begin >= cut:
            rows.append(row(call, variant, book, now, "after 3:10 pm"))
        else:
            k, _ = ratio(etf, nifty, begin, same_day=intraday)
            if intraday and not covered(etf, begin, cut):
                k = None                                 # that day's NIFTYBEES bars aren't (all) saved
            res = None if k is None else bc.score_level(
                convert(call, k, book), etf, calls, convert_updates(updates, k), start=begin if late else None,
                target_level=aim if late else None, close_by=CLOSE_BY_UTC)
            if res is None:                              # no saved prices for that moment, or they end too early
                if not too_old:
                    return None                          # try again tomorrow night
                rows.append(row(call, variant, book, now, "no saved prices", k))
            elif not res:
                rows.append(row(call, variant, book, now, "not filled", k))
            else:
                rows.append(row(call, variant, book, now, res[0]["outcome"], k, res[0]))
                if not late:
                    aim = bc.num(res[0]["target"])
        if not late and not int(rows[-1]["units"]):
            break                                        # no trade on time: nothing to be late for
    return rows


def pending(calls=None, results=None, done=None):
    """Nifty calls the record has scored that haven't been copied yet."""
    calls = bc.read_calls() if calls is None else calls
    if calls.empty:
        return []
    scored = set((bc.read_results() if results is None else results)["id"].astype(str))
    done = set(read_results()["id"].astype(str)) if done is None else done
    return [c for _, c in calls.iterrows()
            if book_of(c) and str(c["id"]) in scored and str(c["id"]) not in done]


def score_all(etf, nifty):
    """Copy every scored Nifty call that has no lines yet. Returns how many lines were added."""
    calls = bc.read_calls()
    updates, rows = bc.read_updates(), []
    for call in pending(calls):
        try:
            out = copy_call(call, etf, nifty, calls, bc.updates_for(updates, call["id"]))
        except Exception as exc:  # one odd call never stops the rest
            print(f"  ! NIFTYBEES copy of call {call['id']}: {exc}", file=sys.stderr)
            continue
        rows += out or []
    bc.append(RESULTS, COLS, rows)
    return len(rows)


# --------------------------------- for the page ---------------------------------
def summary():
    """Totals by book and variant, each copied call, the same calls' result on the index, and what waits."""
    res, main = read_results(), bc.read_results()
    out = {"rows": res, "books": {}, "waiting": [str(c["id"]) for c in pending(results=main)],
           "position": POSITION, "slip": SLIP}
    if not len(res):
        return out
    num = res.assign(**{c: pd.to_numeric(res[c], errors="coerce") for c in
                        ("units", "move_rs", "slip_rs", "charges_rs", "pnl_rs", "r", "fill", "stop")})
    num["risk_rs"] = num["units"] * (num["fill"] - num["stop"]).abs()        # rupees lost if the stop is hit
    index_r = (main.assign(r=pd.to_numeric(main["r"])).groupby("id")["r"].sum().to_dict() if len(main) else {})
    for book in ("calls", "options"):
        part = num[num["book"] == book]
        if part.empty:
            continue
        info = {"copied": int(part.loc[part["variant"] == "ontime", "id"].nunique())}
        for variant, _ in VARIANTS:
            traded = part[(part["variant"] == variant) & (part["units"] > 0)]
            info[variant] = {"n": len(traded), "wins": int((traded["pnl_rs"] > 0).sum()),
                             "move": float(traded["move_rs"].sum()), "slip": float(traded["slip_rs"].sum()),
                             "charges": float(traded["charges_rs"].sum()), "net": float(traded["pnl_rs"].sum()),
                             "r": float(traded["r"].sum()), "risk": float(traded["risk_rs"].sum())}
            if variant == "ontime":
                info["index_r"] = float(sum(index_r.get(str(i), 0.0) for i in traded["id"]))
        out["books"][book] = info
    out["rows"] = num
    return out


def main():
    waiting = pending()
    calls = bc.read_calls()
    done = set(read_results()["id"].astype(str))
    open_calls = [c for _, c in calls.iterrows() if book_of(c) and str(c["id"]) not in done] if len(calls) else []
    if not open_calls:
        print("NIFTYBEES copy: nothing new to copy.")
        return
    try:                                        # also while a call is still open, so its day is never missed
        print(f"{SYMBOL}: {bc.update_bars(SYMBOL)} five-minute bars saved.")
    except Exception as exc:  # Yahoo unreachable: the saved bars are used
        print(f"{SYMBOL}: not updated ({exc})")
    added = score_all(bc.read_bars(SYMBOL), bc.read_bars(bc.symbol("NIFTY"))) if waiting else 0
    left = len(pending())
    print(f"NIFTYBEES copy: {added} lines added" + (f"; {left} scored calls still wait for NIFTYBEES prices."
                                                  if left else "."))


if __name__ == "__main__":
    main()
