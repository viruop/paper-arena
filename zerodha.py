"""
zerodha.py - what an order costs at Zerodha, so everything here that talks about real money uses the
same numbers: the NIFTYBEES copy of the Telegram calls (berlin_etf.py), the real-money ledger
(real_money.py) and the order ticket on the page (ticket.py).

The rates and the rounding are Zerodha's own, read on 11 Nov 2026: its list of charges
(zerodha.com/charges), the script behind its brokerage calculator (zerodha.com/brokerage-calculator),
its support article on STT for ETFs, and that day's bulletin of intraday margins and square-off times.
Charges change: check the list before relying on these, and move CHECKED when you do. A contract note
rounds a whole day's STT and stamp duty together, so a day with several trades can differ from these
by a rupee or two.

Run it to see a few examples:  python zerodha.py
FOR LEARNING ONLY. Not investment advice. This file never places an order.
"""

import math
from decimal import ROUND_HALF_UP, Decimal

CHECKED = "2026-11-11"
SOURCE = "https://zerodha.com/charges/"

GST = 0.18                  # on brokerage, the exchange's charge and SEBI's fee
SEBI = 0.000001             # Rs 10 a crore, on every buy and sell
BROKERAGE = 0.0003          # intraday and futures orders: 0.03% of the order's value ...
BROKERAGE_CAP = 20.0        # ... or Rs 20, whichever is lower. Delivery is free.
EXCHANGE = {"MIS": (0.0000297, 0.000001),         # NSE, shares and ETFs: 0.00297%, plus 0.0001% for its
            "CNC": (0.0000297, 0.000001),         # investor protection fund (0.00307% in all)
            "MCX": (0.000021,)}                   # MCX futures
STAMP = {"MIS": 0.00003, "CNC": 0.00015, "MCX": 0.00002}     # stamp duty, on the buy only, to the nearest rupee
# Tax on the sale: STT on shares and ETFs (to the nearest rupee), CTT on commodity futures.
# kind: "share", "equity_etf" (NIFTYBEES and other share ETFs) or "metal_etf" (gold and silver ETFs: no STT).
SELL_TAX = {("MIS", "share"): 0.00025, ("MIS", "equity_etf"): 0.00025, ("MIS", "metal_etf"): 0.0,
            ("CNC", "share"): 0.001, ("CNC", "equity_etf"): 0.00001, ("CNC", "metal_etf"): 0.0,
            ("MCX", "future"): 0.0001}
BUY_TAX = {("CNC", "share"): 0.001}               # delivery of shares pays STT on the buy as well
DP_CHARGE = 15.34           # once per scrip per day when units are sold from the demat account (delivery)
AUTO_SQUARE_OFF = 59.0      # Rs 50 plus GST for each intraday order Zerodha closes itself
SQUARE_OFF_IST = "15:25"    # when Zerodha closes open intraday ETF positions (15:12 for shares with F&O)
EXIT_BY_IST = "15:10"       # this arena's rule: be out before either, and before Nifty's shares stop at 15:15

KIND = {"NIFTYBEES": "equity_etf", "GOLDBEES": "metal_etf", "SILVERBEES": "metal_etf"}
# Share of the order's value Zerodha asks for on an intraday (MIS) order: its list for 11 Nov 2026.
MIS_MARGIN = {"NIFTYBEES": 0.20, "GOLDBEES": 0.20, "SILVERBEES": 0.2246}
# MCX futures: rupees made or lost on one lot when the quoted price moves Rs 1, what the price is quoted
# for, and the lot. From the contract table in Zerodha's brokerage calculator.
MCX = {"GOLDPETAL": (1, "1 gram", "1 gram"), "GOLDGUINEA": (1, "8 grams", "8 grams"),
       "GOLDTEN": (1, "10 grams", "10 grams"), "GOLDM": (10, "10 grams", "100 grams"),
       "GOLD": (100, "10 grams", "1 kg"), "CRUDEOILM": (10, "1 barrel", "10 barrels"),
       "CRUDEOIL": (100, "1 barrel", "100 barrels")}


def paise(x):
    """To two decimals, halves up: what the calculator's toFixed(2) does."""
    return float(Decimal(float(x)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def rupee(x):
    """To the nearest rupee, halves up: STT and stamp duty."""
    return float(math.floor(paise(x) + 0.5))


def kind_of(symbol, product="MIS"):
    if product == "MCX":
        return "future"
    return KIND.get(str(symbol).upper(), "share")


def brokerage(value, product):
    return 0.0 if product == "CNC" else min(paise(value * BROKERAGE), BROKERAGE_CAP)


def charges(buy_value, sell_value, product="MIS", kind="equity_etf", dp=None):
    """Every charge on a buy of `buy_value` rupees and a sale of `sell_value` rupees (either can be 0).

    product: "MIS" (intraday shares and ETFs), "CNC" (delivery) or "MCX" (commodity futures).
    kind: see SELL_TAX. dp: add the DP charge; by default on any delivery sale.
    Returns a dict of rupees: brokerage, tax (STT or CTT), exchange, sebi, stamp, gst, dp and total.
    Worked out the way Zerodha's calculator does it, so the two agree to the paisa."""
    if product not in EXCHANGE:
        raise ValueError(f"unknown product {product!r}: MIS, CNC or MCX")
    if (product, kind) not in SELL_TAX:
        raise ValueError(f"unknown kind {kind!r} for {product}")
    buy_value, sell_value = float(buy_value or 0), float(sell_value or 0)
    if buy_value < 0 or sell_value < 0:
        raise ValueError("order values can't be negative")
    turnover = paise(buy_value + sell_value)
    out = {"brokerage": paise(brokerage(buy_value, product) + brokerage(sell_value, product))}
    tax = sell_value * SELL_TAX[(product, kind)] + buy_value * BUY_TAX.get((product, kind), 0.0)
    out["tax"] = paise(tax) if product == "MCX" else rupee(tax)
    out["exchange"] = paise(sum(paise(turnover * rate) for rate in EXCHANGE[product]))
    out["sebi"] = paise(turnover * SEBI)
    out["stamp"] = rupee(buy_value * STAMP[product])
    out["gst"] = paise(GST * (out["brokerage"] + out["exchange"] + out["sebi"]))
    if dp is None:
        dp = product == "CNC" and sell_value > 0
    out["dp"] = DP_CHARGE if dp else 0.0
    out["total"] = paise(sum(out.values()))
    return out


def cost(buy_value, sell_value, product="MIS", kind="equity_etf", dp=None):
    """Total rupees of charges on a buy and a sale (see charges())."""
    return charges(buy_value, sell_value, product, kind, dp)["total"]


def round_trip_pct(value, product="MIS", kind="equity_etf"):
    """A buy and a sale of the same `value`: the charges as a share of that value."""
    return cost(value, value, product, kind) / value if value > 0 else 0.0


def main():
    print(f"Zerodha charges as read on {CHECKED} ({SOURCE})\n")
    print("NIFTYBEES, bought and sold the same day (MIS):")
    for value in (5_000, 10_000, 25_000, 100_000):
        c = charges(value, value, "MIS", "equity_etf")
        print(f"  Rs {value:>8,}: Rs {c['total']:>7.2f} = {c['total'] / value:.3%} of the position "
              f"(brokerage {c['brokerage']:.2f}, STT {c['tax']:.0f}, exchange {c['exchange']:.2f}, "
              f"GST {c['gst']:.2f}, stamp {c['stamp']:.0f})")
    print("\nBought, held and sold later (CNC), Rs 5,000:")
    for name in ("NIFTYBEES", "GOLDBEES"):
        c = charges(5_000, 5_000, "CNC", kind_of(name))
        print(f"  {name}: Rs {c['total']:.2f} = {c['total'] / 5_000:.3%} (of which the DP charge on the sale "
              f"Rs {c['dp']:.2f})")
    print("\nOne Gold Petal future bought and sold at about Rs 14,800 (MCX):")
    c = charges(14_800, 14_800, "MCX", "future")
    print(f"  Rs {c['total']:.2f} = {c['total'] / 14_800:.3%} (brokerage {c['brokerage']:.2f}, CTT {c['tax']:.2f})")


if __name__ == "__main__":
    main()
