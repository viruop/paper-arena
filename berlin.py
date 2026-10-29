"""
berlin.py - the Trade Like Berlin channel's strategies being tested, one entry per video, plus
its Telegram channel.

Each key in STRATEGIES is the name the strategy trades under. "agent" entries are agents in
asset_arena.py (their names were fixed when they started, so they keep "(control)"); the
"events" entry is the forex news-event plan, paper traded call by call in berlin_calls.py and
checked on past decisions in berlin_study.py. The page's Trade Like Berlin section shows every
entry with the video, the claim, what had to change to test it, and how it is doing.

To test a new video, use the berlin-new-video skill: write the rule down as the video states it,
code it as a new agent with a new name (never change an existing one), backtest it, then add an
entry here. To add Telegram calls, tag them in data/berlin/telegram_calls.csv (see berlin_calls.py).
"""

CHANNEL = "https://www.youtube.com/@tradelikeberlin_"
TELEGRAM = "https://t.me/tradelikeberlin"
TELEGRAM_FROM = "2026-10-27"       # every post from this day on is archived and, if it's a call, paper traded

STRATEGIES = {
    "Gold breakdown short (control)": {
        "kind": "agent",
        "title": "Gold breakdown short",
        "video": "GOLD IS PREPARING FOR SOMETHING BIG",
        "url": "https://www.youtube.com/watch?v=fDenCL7cyHE",
        "published": "2026-10-22",
        "claim": ("Gold is in a downtrend. A break of the 4,070 'trigger zone', a 70-day low, can bring a 10% "
                  "sell-off, so he shorts gold below 4,070."),
        "changes": ("The trigger is COMEX gold's lowest low of the previous 55 sessions, the video gives no stop "
                    "so one is added (a close above the previous 20 sessions' highest close), and it trades MCX "
                    "Gold Petal futures, since offshore XAUUSD isn't legal for Indian residents."),
        "claimed": "a 10% fall after the breakdown",
    },
    "3-day rule + US filter (control)": {
        "kind": "agent",
        "title": "3-day rule",
        "video": "BTST TRADE RULES | THE BERLIN MINDSET",
        "url": "https://www.youtube.com/watch?v=jVhcbgPxD98",
        "published": "2025-10-26",
        "claim": ("A close above the previous 3 days' high, in line with the 8-10 day trend and the US market, "
                  "means the next day usually follows: the rules 'work 70 to 80% of the time'."),
        "changes": ("Long side only, with NIFTYBEES bought at the next close instead of options held overnight, "
                    "and the S&P 500's last 3 sessions standing in for the US trend. The video's exit, a close "
                    "below the previous 3 days' low, is kept."),
        "claimed": "a winning next day 70 to 80% of the time",
    },
    "Forex news-event plan": {
        "kind": "events",
        "title": "Forex news-event plan",
        "video": "THE FOREX TRADE OPPORTUNITY",
        "url": "https://www.youtube.com/watch?v=QFfNmQayv2U",
        "published": "2026-10-25",
        "claim": ("Trade a central bank's rate decision in the direction of the last 4 to 5 days. The news candle "
                  "moves 0.45-0.65% one way, and the direction is right '6 out of 10' times. He adds a hedge "
                  "(one buy and one sell) so a wrong direction still pays."),
        "changes": ("Paper traded only: offshore forex/CFDs with 1:2000 leverage aren't legal for Indian residents. "
                    "Each event he announces on Telegram is traded with the video's stops (0.20% naked, 0.15% "
                    "hedge legs) and 1:3 targets on 5-minute prices, closed an hour after the news. The direction "
                    "claim is also checked on every RBNZ decision since 1999."),
        "claimed": "the right direction 6 times out of 10",
    },
}
