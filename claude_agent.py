"""
claude_agent.py - makes the "Claude" agent's decision automatically each evening, and the challenger's.

GitHub Actions runs this before building the page. It gathers the latest close, the
indicators, every rule agent's signal and Claude's past decisions, asks Claude through the
Claude API for one decision - 0, 0.5 or 1 of the money in Nifty 50 - and saves it in
decisions/claude.json. The arena fills it at the next trading day's close.

Two ways to use it:
  * Claude API (paid per use): GitHub Actions runs `python claude_agent.py` each evening with the
    ANTHROPIC_API_KEY secret. Without a key it does nothing.
  * Claude Code routine or session (uses a Claude plan instead of an API key): Claude follows
    .claude/skills/claude-agent-decision/SKILL.md, which runs
        python claude_agent.py --snapshot      # what to look at, and whether a decision is due
        python claude_agent.py --record ...    # save the decision Claude made

The challenger (added 13 Nov 2026) is a second Claude agent, "Claude, challenged". After Claude decides,
it gets the same data and Claude's decision, argues the case against that decision and the case for it,
and then decides its own position. It is saved in decisions/claude_challenger.json. Claude itself never
sees the challenger's arguments, so the first agent decides exactly as before; the difference between
the two agents is what a challenge adds. With the API key both are asked in the same run; in a session,
the challenger is a separate agent that hasn't seen Claude's reasoning, only its decision:
        python claude_agent.py --snapshot --agent challenger
        python claude_agent.py --record --agent challenger --position ... --against ... --for ... --decided-by ...

FOR LEARNING ONLY. Paper trading. No real orders are placed. Not investment advice.
"""

# ================================ SETTINGS ================================
MODEL = "claude-opus-5-5"     # the Claude model that decides: Claude Opus 5.5, the model behind the
                              # decisions made in chat before the API key was added (Oct-Nov 2026)
MAX_SEARCHES = 3              # web searches for market news each evening; 0 = decide from the data only
MAX_TOKENS = 3000
TIMEOUT = 300                 # seconds to wait for one reply (searching takes a while)
# ==========================================================================

import datetime as dt
import json
import os
import re
import urllib.error
import urllib.request

import pandas as pd

try:
    import events
except ImportError:          # events.py not uploaded yet
    events = None
import logbook
import market_context as mc
import paper_arena as pa

API_URL = "https://api.anthropic.com/v1/messages"
IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
ALLOWED = (0.0, 0.5, 1.0)

RULES = """You are the Claude agent in a paper-trading arena run for learning. No real money is involved.

Each evening after the Indian market closes, you decide what share of your virtual money to hold
in the Nifty 50 index from the next trading day's close: 0 (all cash), 0.5 (half) or 1 (fully in).
No leverage, no shorting, no other assets. Idle cash earns about 6% a year, and every change costs
0.10% of the amount traded.

Your goal is to beat both the "Cash only" and "Buy & hold" agents over months, with smaller falls
than buy & hold. Simple rule agents trade alongside you; their signals are in the message.
Research on AI trading shows that frequent trading and ignoring the trend usually lose money, so
change position only when the evidence clearly changes, stay consistent with what you said you
would do, and state in advance what would make you change your mind.

{news}

Prices and indicators in the message come from the data; trust them over news if they disagree.
Reply with only one JSON object and no other text, in exactly this form:
{{"position": 0.5, "summary": "one plain sentence", "reasons": ["short reason", "short reason"],
"go_to_cash_if": "a specific condition", "go_fully_in_if": "a specific condition"}}"""

NEWS_ON = ("Before deciding, use web search (at most {n} searches) for news from today and the last "
           "few days that matters for the Nifty 50: the day's move and its causes, foreign investor "
           "flows, crude oil, global markets and RBI policy.")
NEWS_OFF = "Do not search the web; decide from the data in the message."

# The challenger's instructions: written down on 13 Nov 2026 and, like an agent's rule, not changed afterwards.
CHALLENGER_RULES = """You are the challenger in a paper-trading arena run for learning. No real money is involved.

Another Claude agent has just decided what share of its virtual money to hold in the Nifty 50 index
from the next trading day's close: 0 (all cash), 0.5 (half) or 1 (fully in). The message gives the
same data it saw, your own past decisions, and then its decision tonight with its reasons. Before you
decide anything, test that decision:

1. The case against it. Argue as a sceptical risk manager whose job is to find what could go wrong:
   the three strongest reasons its position is wrong now. If it is in Nifty, argue for holding less;
   if it is in cash, argue for holding more. Tie each point to a number in the data or a dated fact.
2. The case for it, held to the same standard: its three strongest supports.
3. Then decide your own position, 0, 0.5 or 1, weighing both cases, and say which single point
   decided it. You may agree or disagree with the other agent.

The same limits apply to you: no leverage, no shorting, no other assets; idle cash earns about 6% a
year and every change costs 0.10% of the amount traded. Frequent trading and ignoring the trend usually
lose money, so change your own position only when the evidence clearly changes, stay consistent with
what you said you would do, and state in advance what would make you change your mind.

{news}

Prices and indicators in the message come from the data; trust them over news if they disagree.
Reply with only one JSON object and no other text, in exactly this form:
{{"position": 0.5, "summary": "one plain sentence", "against": ["point", "point", "point"],
"for": ["point", "point", "point"], "decided_by": "the point that decided it",
"go_to_cash_if": "a specific condition", "go_fully_in_if": "a specific condition"}}"""


# ---------------------------------- helpers -------------------------------------
def load_log():
    if not os.path.exists(pa.CLAUDE_FILE):
        return []
    with open(pa.CLAUDE_FILE, encoding="utf-8") as f:
        return json.load(f)


def save_log(log, path=None):
    path = path or pa.CLAUDE_FILE
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(sorted(log, key=lambda d: d["date"]), f, indent=2, ensure_ascii=False)
        f.write("\n")


def load_challenger_log():
    if not os.path.exists(pa.CHALLENGER_FILE):
        return []
    with open(pa.CHALLENGER_FILE, encoding="utf-8") as f:
        return json.load(f)


def save_challenger_log(log):
    save_log(log, pa.CHALLENGER_FILE)


def snapshot(closes, res, log, ctx=None, as_of=None):
    """Everything Claude sees: data, indicators, breadth, flows, market events, the rule agents and its past
    decisions. Events come only from rows that had been added by as_of (now if None)."""
    n, m, latest = closes["NIFTY 50"], res["market"], res["latest"]
    year = n.loc[str(latest.year)]
    lines = [
        f"Latest close: {latest:%A %d %B %Y}. Your decision is filled at the next trading day's close.",
        f"Nifty 50 close: {m['close']:,.2f} ({m['change']:+.2%} on the day).",
        f"Averages: 200-day {m['sma200']:,.0f}, 50-day {m['sma50']:,.0f}, 20-day {pa.sma(n, 20).iloc[-1]:,.0f}, "
        f"5-day {m['sma5']:,.0f}. RSI(2) {m['rsi2']:.0f}, RSI(14) {pa.rsi(n, 14).iloc[-1]:.0f}.",
        f"{latest.year} so far: high {year.max():,.0f} on {year.idxmax():%d %b}, low {year.min():,.0f} on "
        f"{year.idxmin():%d %b}.",
    ]
    lines += mc.describe(ctx or {})
    if events:
        lines += events.describe(as_of if as_of is not None else dt.datetime.now(IST))
    lines.append("Index returns over 1 month / 3 months / 6 months:")
    for name in closes.columns:
        s = closes[name].dropna()
        if len(s) > 126:
            lines.append(f"  {name}: {s.iloc[-1] / s.iloc[-21] - 1:+.1%} / {s.iloc[-1] / s.iloc[-63] - 1:+.1%} / "
                         f"{s.iloc[-1] / s.iloc[-126] - 1:+.1%}")
    lines.append("The arena (each agent started with Rs 1 lakh):")
    hidden = set(getattr(pa, "NEWER", ()))          # the challenger is never shown to the first agent
    if res["started"]:
        for name, row in res.get("board_first", res["board"]).iterrows():
            if name in hidden:
                continue
            nxt = row["next"] if isinstance(row["next"], str) else "hold"
            lines.append(f"  {name}: holds {row['holding']}, value {pa.rupees(row['value'])} "
                         f"({row['since_start']:+.2%} since start); at next close: {nxt}. {res['why'][name]}")
    else:
        for name, plan in res["plan"].items():
            if name in hidden:
                continue
            lines.append(f"  {name}: will hold {plan} at the first close. {res['why'][name]}")
    lines.append("Your decisions so far (newest first):")
    for d in sorted(log, key=lambda d: d["date"], reverse=True)[:8]:
        lines.append(f"  {d['date']}: {d['position']:.0%} in Nifty. {d.get('summary', '')} "
                     f"Cash if: {d.get('go_to_cash_if', '-')}. Fully in if: {d.get('go_fully_in_if', '-')}.")
    if not log:
        lines.append("  None yet.")
    return "\n".join(lines)


def ask_claude(system, user_text, key):
    """Ask Claude once. Returns the whole reply's content blocks, the number of web searches it made
    and why it stopped. A long search turn can pause (stop_reason "pause_turn"): the reply so far is
    sent back unchanged so Claude can finish, and the pieces are joined."""
    tools = ([{"type": "web_search_20250305", "name": "web_search", "max_uses": MAX_SEARCHES}]
             if MAX_SEARCHES > 0 else [])
    question = {"role": "user", "content": user_text}
    content, searches, stop = [], 0, None
    for _ in range(4):
        messages = [question] + ([{"role": "assistant", "content": content}] if content else [])
        body = {"model": MODEL, "max_tokens": MAX_TOKENS, "system": system, "messages": messages}
        if tools:
            body["tools"] = tools
        request = urllib.request.Request(API_URL, data=json.dumps(body).encode("utf-8"), headers={
            "x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"})
        with urllib.request.urlopen(request, timeout=TIMEOUT) as resp:
            data = json.loads(resp.read())
        new = data.get("content") or []
        content = new if content and new[:len(content)] == content else content + new  # never twice
        searches += (data.get("usage") or {}).get("server_tool_use", {}).get("web_search_requests", 0) or 0
        stop = data.get("stop_reason")
        if stop != "pause_turn":
            break
    return {"content": content, "searches": searches, "stop_reason": stop}


def parse_decision(text):
    """The last JSON object in Claude's reply that has a position."""
    decoder = json.JSONDecoder()
    for start in reversed([m.start() for m in re.finditer(r"\{", text)]):
        try:
            obj, _ = decoder.raw_decode(text[start:])
        except ValueError:
            continue
        if isinstance(obj, dict) and "position" in obj:
            return obj
    return None


# ----------------------------------- main ---------------------------------------
def status(latest, log, now):
    """Is a decision due? Claude decides once per close, and only between that close and the next
    market open, so it can never use information from the session in which its decision is filled."""
    if any(d["date"] == latest.date().isoformat() for d in log):
        return False, f"Claude already decided after the close of {latest.date()}."
    next_open = events.next_open(latest) if events else None   # holidays and special sessions (Muhurat) count
    if next_open is None:
        next_open = dt.datetime.combine((latest + pd.offsets.BDay(1)).date(), dt.time(9, 0), IST)
    if now >= next_open:
        return False, (f"The newest close in the data is {latest.date()} and the next session has already "
                       "opened. Wait until the latest close reaches the data (usually after 7:30 pm IST).")
    return True, f"Decide for the close of {latest.date()}; the decision is filled at the next close."


def make_record(latest, decision, model, now, searches=0):
    try:
        position = float(decision["position"])
    except (TypeError, KeyError, ValueError):
        raise ValueError("position must be 0, 0.5 or 1")
    if position not in ALLOWED:
        raise ValueError(f"position must be 0, 0.5 or 1, not {position}")
    summary = str(decision.get("summary", "")).strip()
    if not summary:
        raise ValueError("a one-sentence summary is required")
    return {
        "date": latest.date().isoformat(),
        "position": position,
        "summary": summary[:300],
        "reasons": [str(r)[:300] for r in decision.get("reasons", []) if str(r).strip()][:5],
        "go_to_cash_if": str(decision.get("go_to_cash_if", ""))[:200],
        "go_fully_in_if": str(decision.get("go_fully_in_if", ""))[:200],
        "model": model,
        "searches": searches,
        "made_at": now.isoformat(timespec="minutes"),
    }


# --------------------------------- the challenger ----------------------------------
def tonight(log, latest):
    """Claude's decision for this close, or None."""
    day = latest.date().isoformat()
    return next((d for d in log if d["date"] == day), None)


def challenger_status(latest, log, chlog, now):
    """Is a challenger decision due? Only once Claude has decided for this close, once, and before the next
    session opens."""
    if any(d["date"] == latest.date().isoformat() for d in chlog):
        return False, f"The challenger already decided after the close of {latest.date()}."
    first = tonight(log, latest)
    if first is None:
        return False, (f"Claude hasn't decided after the close of {latest.date()} yet. The challenger tests "
                       "that decision, so it waits for it.")
    due, why = status(latest, [], now)
    if not due:
        return False, why
    return True, (f"Test Claude's {first['position']:.0%} for the close of {latest.date()}; the challenger's own "
                  "decision is filled at the next close.")


def challenger_text(base, chlog, first):
    """What the challenger reads: Claude's data (with Claude's past decisions named as Claude's), the
    challenger's own past decisions, and Claude's decision tonight."""
    base = base.replace("Your decisions so far (newest first):", "Claude's decisions so far (newest first):")
    lines = [base, "Your own decisions so far, as the challenger (newest first):"]
    for d in sorted(chlog, key=lambda d: d["date"], reverse=True)[:8]:
        c = d.get("challenged") or {}
        lines.append(f"  {d['date']}: {d['position']:.0%} in Nifty (Claude had {float(c.get('position', 0)):.0%}). "
                     f"{d.get('summary', '')} Cash if: {d.get('go_to_cash_if', '-')}. "
                     f"Fully in if: {d.get('go_fully_in_if', '-')}.")
    if not chlog:
        lines.append("  None yet.")
    lines += ["", f"CLAUDE'S DECISION TONIGHT ({first['date']}): {first['position']:.0%} in Nifty 50.",
              f"Summary: {first.get('summary', '')}"]
    lines += [f"Reason: {r}" for r in first.get("reasons", [])]
    lines += [f"Goes to cash if: {first.get('go_to_cash_if', '-')}", f"Goes fully in if: {first.get('go_fully_in_if', '-')}"]
    return "\n".join(lines)


def make_challenger_record(latest, decision, first, model, now, searches=0):
    record = make_record(latest, decision, model, now, searches)
    against = [str(r)[:300] for r in decision.get("against", []) if str(r).strip()][:3]
    support = [str(r)[:300] for r in decision.get("for", []) if str(r).strip()][:3]
    decided_by = str(decision.get("decided_by", "")).strip()[:300]
    if not against:
        raise ValueError("the case against Claude's decision is required (up to three points)")
    if not support:
        raise ValueError("the case for Claude's decision is required (up to three points)")
    if not decided_by:
        raise ValueError("say which point decided it")
    return {"date": record["date"], "position": record["position"], "summary": record["summary"],
            "challenged": {"date": first["date"], "position": float(first["position"])},
            "against": against, "for": support, "decided_by": decided_by,
            "go_to_cash_if": record["go_to_cash_if"], "go_fully_in_if": record["go_fully_in_if"],
            "model": model, "searches": searches, "made_at": record["made_at"]}


def first_as_of(first, now):
    """The time Claude decided, so the challenger reads the market events Claude read."""
    try:
        return pd.Timestamp(first["made_at"]).to_pydatetime()
    except Exception:
        return now


def run_challenger_api(key, closes, res, log, now, clock_given):
    """After Claude's decision in the same run: ask the challenger. Any failure leaves Claude's decision as
    saved and the challenger at its last position."""
    latest = res["latest"]
    chlog = load_challenger_log()
    due, why = challenger_status(latest, log, chlog, now)
    if not due:
        print(f"Challenger: {why}")
        return
    first = tonight(log, latest)
    base = snapshot(closes, res, [d for d in log if d["date"] != first["date"]], mc.context(),
                    as_of=first_as_of(first, now))
    text_in = challenger_text(base, chlog, first)
    system = CHALLENGER_RULES.format(news=NEWS_ON.format(n=MAX_SEARCHES) if MAX_SEARCHES > 0 else NEWS_OFF)
    try:
        data = ask_claude(system, text_in, key)
    except urllib.error.HTTPError as err:
        print(f"Challenger: Claude API error {err.code}: {err.read()[:500]!r}. It keeps its last position.")
        return
    except Exception as err:  # network problems, timeouts
        print(f"Challenger: could not reach the Claude API ({err}). It keeps its last position.")
        return
    text = "".join(b.get("text", "") for b in data["content"] if b.get("type") == "text")
    if not clock_given:
        due, why = challenger_status(latest, log, chlog, dt.datetime.now(IST))
        if not due:
            print(f"Challenger: the reply came too late, so nothing is saved: {why}")
            return
    try:
        record = make_challenger_record(latest, parse_decision(text) or {}, first, f"{MODEL} (API)", now,
                                        data["searches"])
    except ValueError as err:
        print(f"Challenger: no valid decision in the reply ({err}; it stopped with {data['stop_reason']}), so it "
              f"keeps its last position. Reply was:\n{text[:1500]}")
        return
    chlog.append(record)
    save_challenger_log(chlog)
    logbook.save_snapshot(record["date"], text_in + "\n\nCLAUDE'S REPLY\n" + text,
                          f"What the challenger ({MODEL}, through the API) saw on {record['made_at']}, and its reply.",
                          suffix="-challenger")
    print(f"Challenger decided {record['position']:.0%} in Nifty 50 (Claude: {first['position']:.0%}) after the "
          f"close of {record['date']}: {record['summary']}")


def run_api(now=None):
    """GitHub Actions mode: ask Claude through the Claude API."""
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not key:
        print("No ANTHROPIC_API_KEY set, so the Claude agent keeps its last position.")
        return
    clock_given = now is not None
    now = now or dt.datetime.now(IST)
    log = load_log()
    closes = pa.load_all()
    res = pa.compute(closes)
    due, why = status(res["latest"], log, now)
    if not due:
        print(why)
        return

    system = RULES.format(news=NEWS_ON.format(n=MAX_SEARCHES) if MAX_SEARCHES > 0 else NEWS_OFF)
    user_text = snapshot(closes, res, log, mc.context(), as_of=now)
    try:
        data = ask_claude(system, user_text, key)
    except urllib.error.HTTPError as err:
        print(f"Claude API error {err.code}: {err.read()[:500]!r}. Keeping the last position.")
        return
    except Exception as err:  # network problems, timeouts
        print(f"Could not reach the Claude API ({err}). Keeping the last position.")
        return

    text = "".join(b.get("text", "") for b in data["content"] if b.get("type") == "text")
    if not clock_given:   # the reply can take minutes: it must still arrive before the next session opens
        due, why = status(res["latest"], log, dt.datetime.now(IST))
        if not due:
            print(f"Claude's reply came too late, so nothing is saved: {why}")
            return
    try:
        record = make_record(res["latest"], parse_decision(text) or {}, f"{MODEL} (API)", now, data["searches"])
    except ValueError as err:
        print(f"No valid decision in Claude's reply ({err}; it stopped with {data['stop_reason']}), "
              f"so it keeps its last position. Reply was:\n{text[:1500]}")
        return
    log.append(record)
    save_log(log)
    logbook.save_snapshot(record["date"], user_text + "\n\nCLAUDE'S REPLY\n" + text,
                          f"What Claude ({MODEL}, through the API) saw on {record['made_at']}, and its reply.")
    print(f"Claude decided {record['position']:.0%} in Nifty 50 after the close of {record['date']}: {record['summary']}")
    run_challenger_api(key, closes, res, log, now, clock_given)


def run_snapshot(now=None, agent="claude"):
    """Routine mode, step 1: print what Claude (or the challenger) should look at and whether a decision is due."""
    now = now or dt.datetime.now(IST)
    log = load_log()
    closes = pa.load_all()
    res = pa.compute(closes)
    if agent == "challenger":
        chlog = load_challenger_log()
        due, why = challenger_status(res["latest"], log, chlog, now)
        print(f"DECISION NEEDED: {'yes' if due else 'no'}. {why}\n")
        print(CHALLENGER_RULES.split("{news}")[0].strip())
        print("\n" + NEWS_ON.format(n=MAX_SEARCHES) + "\n")
        first = tonight(log, res["latest"])
        if first is not None:
            base = snapshot(closes, res, [d for d in log if d["date"] != first["date"]], mc.context(),
                            as_of=first_as_of(first, now))
            print(challenger_text(base, chlog, first))
        return
    due, why = status(res["latest"], log, now)
    print(f"DECISION NEEDED: {'yes' if due else 'no'}. {why}\n")
    print(RULES.split("{news}")[0].strip())
    print("\n" + NEWS_ON.format(n=MAX_SEARCHES) + "\n")
    print(snapshot(closes, res, log, mc.context(), as_of=now))


def run_record_challenger(args, closes, res, log, now):
    latest = res["latest"]
    chlog = load_challenger_log()
    due, why = challenger_status(latest, log, chlog, now)
    if not due:
        raise SystemExit(f"Not saved: {why}")
    first = tonight(log, latest)
    decision = {"position": args.position, "summary": args.summary or "", "against": args.against or [],
                "for": args.for_ or [], "decided_by": args.decided_by or "", "go_to_cash_if": args.cash_if or "",
                "go_fully_in_if": args.in_if or ""}
    try:
        record = make_challenger_record(latest, decision, first, args.model, now, args.searches)
    except ValueError as err:
        raise SystemExit(f"Not saved: {err}")
    base = snapshot(closes, res, [d for d in log if d["date"] != first["date"]], mc.context(),
                    as_of=first_as_of(first, now))
    text = challenger_text(base, chlog, first)
    chlog.append(record)
    save_challenger_log(chlog)
    logbook.save_snapshot(record["date"], text, f"What the challenger ({args.model}) decided from on "
                                                f"{record['made_at']}. Its news searches aren't included; its "
                                                "arguments are in claude_challenger.json.", suffix="-challenger")
    print(f"Saved: the challenger holds {record['position']:.0%} in Nifty 50 after the close of {record['date']} "
          f"(Claude: {first['position']:.0%}). Now commit decisions/claude_challenger.json and decisions/snapshots.")


def run_record(args, now=None):
    """Routine mode, step 2: validate and save the decision Claude (or the challenger) made."""
    now = now or dt.datetime.now(IST)
    log = load_log()
    closes = pa.load_all()
    res = pa.compute(closes)
    if getattr(args, "agent", "claude") == "challenger":
        return run_record_challenger(args, closes, res, log, now)
    latest = res["latest"]
    due, why = status(latest, log, now)
    if not due:
        raise SystemExit(f"Not saved: {why}")
    decision = {"position": args.position, "summary": args.summary or "", "reasons": args.reason or [],
                "go_to_cash_if": args.cash_if or "", "go_fully_in_if": args.in_if or ""}
    try:
        record = make_record(latest, decision, args.model, now, args.searches)
    except ValueError as err:
        raise SystemExit(f"Not saved: {err}")
    text = snapshot(closes, res, log, mc.context(), as_of=now)
    log.append(record)
    save_log(log)
    logbook.save_snapshot(record["date"], text, f"What {args.model} decided from on {record['made_at']}. "
                                                "Its news searches aren't included; its reasons are in claude.json.")
    print(f"Saved: {record['position']:.0%} in Nifty 50 after the close of {record['date']}. "
          f"Now commit decisions/claude.json and decisions/snapshots, and push them to main.")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="The Claude agent's daily decision.")
    parser.add_argument("--snapshot", action="store_true", help="print the data Claude decides from")
    parser.add_argument("--record", action="store_true", help="save a decision Claude has made")
    parser.add_argument("--position", type=float, help="0, 0.5 or 1")
    parser.add_argument("--summary", help="one plain sentence")
    parser.add_argument("--reason", action="append", help="a short reason (repeat for more)")
    parser.add_argument("--cash-if", dest="cash_if", help="what would make Claude go to cash")
    parser.add_argument("--in-if", dest="in_if", help="what would make Claude go fully in")
    parser.add_argument("--model", default="Claude (routine)", help="who made the decision")
    parser.add_argument("--searches", type=int, default=0, help="how many web searches were made before deciding")
    parser.add_argument("--agent", choices=("claude", "challenger"), default="claude",
                        help="whose decision: Claude's (the default) or the challenger's")
    parser.add_argument("--against", action="append", help="challenger: a point against Claude's decision (up to 3)")
    parser.add_argument("--for", dest="for_", action="append", help="challenger: a point for Claude's decision (up to 3)")
    parser.add_argument("--decided-by", dest="decided_by", help="challenger: the point that decided it")
    args = parser.parse_args()
    if args.snapshot:
        run_snapshot(agent=args.agent)
    elif args.record:
        run_record(args)
    else:
        run_api()


if __name__ == "__main__":
    main()
