"""
claude_agent.py - makes the "Claude" agent's decision automatically each evening.

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

FOR LEARNING ONLY. Paper trading. No real orders are placed. Not investment advice.
"""

# ================================ SETTINGS ================================
MODEL = "claude-sonnet-5-5"   # the Claude model that decides
MAX_SEARCHES = 3              # web searches for market news each evening; 0 = decide from the data only
MAX_TOKENS = 3000
# ==========================================================================

import datetime as dt
import json
import os
import re
import urllib.error
import urllib.request

import pandas as pd

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


# ---------------------------------- helpers -------------------------------------
def load_log():
    if not os.path.exists(pa.CLAUDE_FILE):
        return []
    with open(pa.CLAUDE_FILE, encoding="utf-8") as f:
        return json.load(f)


def save_log(log):
    os.makedirs(os.path.dirname(pa.CLAUDE_FILE), exist_ok=True)
    with open(pa.CLAUDE_FILE, "w", encoding="utf-8") as f:
        json.dump(sorted(log, key=lambda d: d["date"]), f, indent=2, ensure_ascii=False)
        f.write("\n")


def snapshot(closes, res, log, ctx=None):
    """Everything Claude sees: data, indicators, breadth, flows, the rule agents and its past decisions."""
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
    lines.append("Index returns over 1 month / 3 months / 6 months:")
    for name in closes.columns:
        s = closes[name].dropna()
        if len(s) > 126:
            lines.append(f"  {name}: {s.iloc[-1] / s.iloc[-21] - 1:+.1%} / {s.iloc[-1] / s.iloc[-63] - 1:+.1%} / "
                         f"{s.iloc[-1] / s.iloc[-126] - 1:+.1%}")
    lines.append("The arena (each agent started with Rs 1 lakh):")
    if res["started"]:
        for name, row in res["board"].iterrows():
            nxt = row["next"] if isinstance(row["next"], str) else "hold"
            lines.append(f"  {name}: holds {row['holding']}, value {pa.rupees(row['value'])} "
                         f"({row['since_start']:+.2%} since start); at next close: {nxt}. {res['why'][name]}")
    else:
        for name, plan in res["plan"].items():
            lines.append(f"  {name}: will hold {plan} at the first close. {res['why'][name]}")
    lines.append("Your decisions so far (newest first):")
    for d in sorted(log, key=lambda d: d["date"], reverse=True)[:8]:
        lines.append(f"  {d['date']}: {d['position']:.0%} in Nifty. {d.get('summary', '')} "
                     f"Cash if: {d.get('go_to_cash_if', '-')}. Fully in if: {d.get('go_fully_in_if', '-')}.")
    if not log:
        lines.append("  None yet.")
    return "\n".join(lines)


def ask_claude(system, user_text, key):
    tools = ([{"type": "web_search_20250305", "name": "web_search", "max_uses": MAX_SEARCHES}]
             if MAX_SEARCHES > 0 else [])
    messages = [{"role": "user", "content": user_text}]
    for _ in range(3):  # a long search turn can pause; send it back to let Claude finish
        body = {"model": MODEL, "max_tokens": MAX_TOKENS, "system": system, "messages": messages}
        if tools:
            body["tools"] = tools
        request = urllib.request.Request(API_URL, data=json.dumps(body).encode("utf-8"), headers={
            "x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"})
        with urllib.request.urlopen(request, timeout=180) as resp:
            data = json.loads(resp.read())
        if data.get("stop_reason") != "pause_turn":
            return data
        messages = [messages[0], {"role": "assistant", "content": data["content"]}]
    return data


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


def run_api(now=None):
    """GitHub Actions mode: ask Claude through the Claude API."""
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not key:
        print("No ANTHROPIC_API_KEY set, so the Claude agent keeps its last position.")
        return
    now = now or dt.datetime.now(IST)
    log = load_log()
    closes = pa.load_all()
    res = pa.compute(closes)
    due, why = status(res["latest"], log, now)
    if not due:
        print(why)
        return

    system = RULES.format(news=NEWS_ON.format(n=MAX_SEARCHES) if MAX_SEARCHES > 0 else NEWS_OFF)
    user_text = snapshot(closes, res, log, mc.context())
    try:
        data = ask_claude(system, user_text, key)
    except urllib.error.HTTPError as err:
        print(f"Claude API error {err.code}: {err.read()[:500]!r}. Keeping the last position.")
        return
    except Exception as err:  # network problems, timeouts
        print(f"Could not reach the Claude API ({err}). Keeping the last position.")
        return

    text = "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")
    searches = data.get("usage", {}).get("server_tool_use", {}).get("web_search_requests", 0)
    try:
        record = make_record(res["latest"], parse_decision(text) or {}, MODEL, now, searches)
    except ValueError as err:
        print(f"No valid decision in Claude's reply ({err}), so it keeps its last position. Reply was:\n{text[:1500]}")
        return
    log.append(record)
    save_log(log)
    logbook.save_snapshot(record["date"], user_text + "\n\nCLAUDE'S REPLY\n" + text,
                          f"What Claude ({MODEL}, through the API) saw on {record['made_at']}, and its reply.")
    print(f"Claude decided {record['position']:.0%} in Nifty 50 after the close of {record['date']}: {record['summary']}")


def run_snapshot(now=None):
    """Routine mode, step 1: print what Claude should look at and whether a decision is due."""
    now = now or dt.datetime.now(IST)
    log = load_log()
    closes = pa.load_all()
    res = pa.compute(closes)
    due, why = status(res["latest"], log, now)
    print(f"DECISION NEEDED: {'yes' if due else 'no'}. {why}\n")
    print(RULES.split("{news}")[0].strip())
    print("\n" + NEWS_ON.format(n=MAX_SEARCHES) + "\n")
    print(snapshot(closes, res, log, mc.context()))


def run_record(args, now=None):
    """Routine mode, step 2: validate and save the decision Claude made."""
    now = now or dt.datetime.now(IST)
    log = load_log()
    closes = pa.load_all()
    res = pa.compute(closes)
    latest = res["latest"]
    due, why = status(latest, log, now)
    if not due:
        raise SystemExit(f"Not saved: {why}")
    decision = {"position": args.position, "summary": args.summary or "", "reasons": args.reason or [],
                "go_to_cash_if": args.cash_if or "", "go_fully_in_if": args.in_if or ""}
    try:
        record = make_record(latest, decision, args.model, now)
    except ValueError as err:
        raise SystemExit(f"Not saved: {err}")
    text = snapshot(closes, res, log, mc.context())
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
    args = parser.parse_args()
    if args.snapshot:
        run_snapshot()
    elif args.record:
        run_record(args)
    else:
        run_api()


if __name__ == "__main__":
    main()
