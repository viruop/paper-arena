"""
scorecard.py - "Is this channel worth following?", the same written-down test for every channel.

The bar was written down on 4 Nov 2026 (when 5 of Trade Like Berlin's calls had been scored and none of
the second channel's) and is never changed, so it can't drift to fit the results. Checks 9 and 10 were
added the same evening, before any more calls were scored. A channel gets a verdict only after
MIN_CALLS scored calls; until then the checks show where it stands.

  1. Enough calls: at least 40 scored calls, so a few lucky trades can't decide it.
  2. Makes money after costs, at Rs 1,000 risk per call.
  3. In both halves: the first and second half of its calls, in posting order, each make money.
  4. Not two lucky calls: still in profit without its two best calls.
  5. Survives a real delay: still in profit when every call is taken 15 minutes late.
  6. His direction matters: the same trades reversed do worse.
  7. Checkable: at least 60% of his trade calls have levels free data can score.
  8. Honest claims: where his own "TP hit" or "SL hit" posts can be checked, at least 80% match the record.
  9. Not luck: the profit is big enough that a channel with no edge would make it less than 1 time in 20
     (a one-sided test on the per-call results; needs at least 20 calls). A simulation of 4,000 channels
     with no edge found about 1 in 8 passing checks 2 to 6 after 40 calls; with this check, about 1 in 30.
 10. His calls stay up: none of his calls was deleted from the channel after it was saved here.
"""

import math

import pandas as pd

MIN_CALLS = 40


def rupees(x):
    return f"{'+' if x >= 0 else '−'}₹{abs(x):,.0f}"


def luck(per_call):
    """(t statistic, one-sided chance of at least this profit with no edge) for the per-call results."""
    n = len(per_call)
    sd = float(per_call.std(ddof=1)) if n > 1 else 0.0
    if n < 2 or sd == 0:
        return None, None
    t = float(per_call.mean()) / (sd / math.sqrt(n))
    return t, 0.5 * math.erfc(t / math.sqrt(2))


def evaluate(per_call, variants, scorable, trade_calls, claims=None, deleted_calls=0):
    """per_call: P&L per scored call (Series, posting order). variants: DataFrame with variant, pnl_rs.
    claims: list of verdicts ("matches", "doesn't match"; others ignored). deleted_calls: how many of his
    calls he deleted after they were saved. Returns checks and a verdict."""
    per_call = per_call.astype(float) if len(per_call) else pd.Series(dtype=float)
    n, total = len(per_call), float(per_call.sum())
    var = variants.assign(p=pd.to_numeric(variants["pnl_rs"], errors="coerce").fillna(0)) if len(variants) else None
    late = float(var.loc[var["variant"] == "late15", "p"].sum()) if var is not None else None
    flip = float(var.loc[var["variant"] == "flip", "p"].sum()) if var is not None else None
    half = n // 2
    first, second = float(per_call.iloc[:half].sum()), float(per_call.iloc[half:].sum())
    best_two = float(per_call.sort_values(ascending=False).iloc[:2].sum()) if n else 0.0
    checked = [c for c in (claims or []) if c in ("matches", "doesn't match")]
    matched = sum(c == "matches" for c in checked)
    rows = [
        ("Enough calls", True if n >= MIN_CALLS else None, f"{n} of {MIN_CALLS} scored"),
        ("Makes money after costs", total > 0 if n else None, rupees(total) if n else "no calls scored yet"),
        ("In both halves", (first > 0 and second > 0) if n >= 4 else None,
         f"{rupees(first)} then {rupees(second)}" if n >= 4 else "needs at least 4 calls"),
        ("Not two lucky calls", (total - best_two > 0) if n >= 3 else None,
         f"{rupees(total - best_two)} without the best two" if n >= 3 else "needs at least 3 calls"),
        ("Survives 15 minutes' delay", (late > 0) if late is not None and n else None,
         f"{rupees(late)} if taken 15 minutes late" if late is not None and n else "not checked yet"),
        ("His direction matters", (total > flip) if flip is not None and n else None,
         f"{rupees(flip)} if reversed" if flip is not None and n else "not checked yet"),
        ("Enough calls can be checked", (scorable / trade_calls >= 0.6) if trade_calls else None,
         f"{scorable} of {trade_calls} trade calls" if trade_calls else "no trade calls yet"),
        ("His claims match the record", (matched / len(checked) >= 0.8) if checked else None,
         f"{matched} of {len(checked)} checked" if checked else "none checked yet"),
    ]
    t, p = luck(per_call)
    if n < 20 or p is None:
        rows.append(("Not luck", None, "needs at least 20 calls"))
    elif total <= 0:
        rows.append(("Not luck", False, "no profit to test"))
    else:
        rows.append(("Not luck", p < 0.05, f"a profit this size happens by luck about 1 time in {max(1, round(1 / p)):,}"
                     if p > 0 else "far beyond luck"))
    rows.append(("His calls stay up", deleted_calls == 0,
                 "none deleted" if deleted_calls == 0 else f"{deleted_calls} deleted after posting"))
    failed = [label for label, ok, _ in rows[1:] if ok is False]
    if n < MIN_CALLS:
        verdict = f"Too early to judge: {n} of {MIN_CALLS} calls scored."
    elif failed:
        verdict = "Doesn't pass: " + ", ".join(f.lower() for f in failed) + "."
    else:
        verdict = "Passes every check so far."
    return {"rows": rows, "verdict": verdict}


def in_order(per_call, calls):
    """Per-call P&L in posting order, for the two-halves check."""
    if not len(per_call) or not len(calls):
        return per_call
    order = [str(i) for i in calls.sort_values("posted_at")["id"]]
    have = set(per_call.index.astype(str))
    return per_call.reindex([i for i in order if i in have])


def berlin_checks(tg):
    """The checks for Trade Like Berlin's level calls, from berlin_calls.summary()."""
    calls, ups = tg["calls"], tg.get("updates")
    claims = ups.loc[ups["action"] == "claim", "verdict"].tolist() if ups is not None and len(ups) else []
    scorable = int((calls["scorable"] == "yes").sum()) if len(calls) else 0
    return evaluate(in_order(tg["books"]["calls"]["per_call"], calls), tg.get("variants", pd.DataFrame()),
                    scorable, len(calls), claims, tg.get("deleted_calls", 0))


def signal_checks(sm):
    """The checks for a signal channel, from signal_calls.summary(). Trade posts the code couldn't read
    count as trade calls that can't be checked."""
    calls = sm["calls"]
    claims = sm["claims"]["verdict"].tolist() if len(sm["claims"]) else []
    scorable = int((calls["scorable"] == "yes").sum()) if len(calls) else 0
    return evaluate(in_order(sm["book"]["per_call"], calls), sm["variants"], scorable,
                    len(calls) + sm["unread_trades"], claims, sm.get("deleted_calls", 0))


def all_checks():
    """[(channel name, checks)] for every channel, exactly as the page shows them."""
    import berlin_calls
    import channels
    import signal_calls
    out = [(channels.CHANNELS["berlin"]["name"], berlin_checks(berlin_calls.summary()))]
    for ch in channels.CHANNELS.values():
        if ch["tagging"] == "parser":
            out.append((ch["name"], signal_checks(signal_calls.summary(ch))))
    return out


if __name__ == "__main__":      # python scorecard.py: every channel's checks, for the weekly scheduled task
    for name, sc in all_checks():
        print(f"{name}: {sc['verdict']}")
        for label, ok, detail in sc["rows"]:
            print(f"  {'✓' if ok else '✗' if ok is False else '·'} {label}: {detail}")
