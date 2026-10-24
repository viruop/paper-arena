---
name: claude-agent-decision
description: Makes the paper arena's daily "Claude" agent decision (0, 0.5 or 1 of its virtual money in Nifty 50) and saves it to decisions/claude.json. Use for a "Claude agent update", for the scheduled evening routine, or whenever asked to decide or review the Claude agent's position.
---

# Claude agent: daily decision

This repository runs a paper-trading arena for learning. Six rule-based agents and the Claude agent each manage ₹1 lakh of virtual money in Nifty 50. No real orders are ever placed.

## Steps

1. Install the packages if needed: `pip install -r requirements.txt`
2. Run `python claude_agent.py --snapshot` and read all of it.
   - If the first line says `DECISION NEEDED: no`, stop and report the reason. Don't save anything.
3. Search the web (2 or 3 searches) for news from the latest session and the last few days that matters for Nifty 50: the day's move and its causes, FII and DII flows, crude oil, global markets and RBI policy. The prices, breadth and flows in the snapshot come from the data; trust them over news if they disagree.
4. Decide 0 (all cash), 0.5 (half) or 1 (fully in), following the rules below.
5. Save the decision:
   ```bash
   python claude_agent.py --record --position 0.5 \
     --summary "One plain sentence." \
     --reason "A short reason." --reason "Another short reason." \
     --cash-if "A condition you can check at a close, e.g. Nifty closes below 22,000" \
     --in-if "A condition you can check at a close, e.g. Nifty closes above its 50-day average"
   ```
   If it prints `Not saved`, report why and stop.
6. Commit and push:
   ```bash
   git add decisions
   git commit -m "Claude agent decision for <date of the close>"
   git push origin HEAD:main
   ```
7. Reply with the decision, the summary and the two conditions.

## Rules

- The only positions are 0, 0.5 and 1. No leverage, no shorting, no other assets.
- Read your last decision first. If its "cash if" or "fully in if" condition was met at the latest close, act on it, unless you clearly explain why you're changing the plan.
- Change position only when the evidence clearly changes. Every switch costs money, and research on AI trading shows that overtrading and ignoring the trend usually lose.
- Always give a specific "cash if" and "fully in if" condition that can be checked at a close.
- Never edit or delete past decisions, never backdate, and change no files outside the `decisions` folder.
- This is paper trading for learning. Don't present decisions as advice.
