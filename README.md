# Paper arena

Six agents follow simple Nifty rules, each with ₹1 lakh of virtual money, and a web page shows how they're doing. GitHub runs everything for free every weekday evening.

For learning only. Not investment advice. No real orders are placed.

## What's in this folder

| File | What it does |
|---|---|
| `paper_arena.py` | The arena: the agents, plus your own calls in `MANUAL_AGENTS` |
| `nifty_backtest.py` | The backtest of the same rules from 2010 to today |
| `build_site.py` | Builds the web page into a `site` folder |
| `requirements.txt` | The Python packages GitHub installs |
| `.github/workflows/arena.yml` | Runs everything each weekday evening and publishes the page |

## Set it up once (about 10 minutes)

1. Sign in to GitHub with your **personal** account. You can create one for free at github.com.
2. Click **+** at the top right, then **New repository**. Name it `paper-arena`, choose **Public**, and click **Create repository**. Don't add a README; this folder already has one.
3. On the new, empty repository page, click **uploading an existing file**. Drag in everything from this unzipped folder, including the `.github` folder, and click **Commit changes**.
   - On a Mac, press **Cmd + Shift + .** in Finder to show hidden folders like `.github`.
4. Check that `.github/workflows/arena.yml` now appears in the repository. If it's missing, click **Add file → Create new file**, type `.github/workflows/arena.yml` as the name, paste in the file's contents, and click **Commit changes**.
5. Go to **Settings → Pages**. Under **Build and deployment**, set **Source** to **GitHub Actions**.
6. Go to the **Actions** tab, click **Daily paper arena** on the left, then **Run workflow**. After about two minutes you'll see a green tick.
7. Open `https://YOUR-USERNAME.github.io/paper-arena/`. The link also appears under **Settings → Pages**. Bookmark it on your phone.

The first run starts by itself when you upload the files in step 3. It fails because Pages isn't switched on until step 5. That's expected; the run in step 6 works.

## Every day

Nothing. The page updates on weekdays at about 8:30 pm IST, with a backup run at 11 pm, after the free price data updates. GitHub sometimes starts scheduled runs a little late.

## Add your own call (and Claude's)

1. Open `paper_arena.py` on GitHub and click the pencil icon.
2. Under `"Me"` in `MANUAL_AGENTS`, add a line such as `"2026-10-26": 1.0,` using that evening's date. 0 means all cash, 0.5 means half in Nifty, 1 means fully in Nifty.
3. Click **Commit changes**. The page rebuilds within a few minutes.

To add Claude as a player, ask Claude in chat each evening for a call and record it under a `"Claude"` entry the same way.

Never add a call with a past date, and never change an agent's rule after the start. Both would use hindsight. To test an improved rule, add it as a new agent instead.

## Good to know

- **The page is public.** On GitHub's free plan, Pages sites are public, so anyone with the link can see it. Keep only virtual trades here, nothing personal or work-related.
- **Keep it active.** If the repository has no activity for 60 days, GitHub pauses the daily run. Adding a call counts as activity, and you can turn the run back on from the **Actions** tab.
- **Keep `START` fixed** once paper trading begins.
- **Running it yourself:** `pip install -r requirements.txt`, then `python build_site.py`, and open `site/index.html`. You can also run `paper_arena.py` or `nifty_backtest.py` on their own, or paste them into Google Colab.
- **Data:** free daily index data from [indian-market-historical-data](https://github.com/aswinv90/indian-market-historical-data), licensed for personal, non-commercial use.
