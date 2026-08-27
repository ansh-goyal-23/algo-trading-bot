# Deploying unattended paper trading (Render + Supabase)

This replaces manually running `start_paper_trader.sh` on your Mac every
day with a Render Cron Job that fires itself at 9:00 AM IST on weekdays,
using a new Supabase database for state instead of local CSV/JSON files
(Render's containers don't keep a filesystem between runs).

**What's new in this repo**, none of it touching your existing local
scripts:
- `execution/state_store.py` — reads/writes positions, trades, and
  intraday OHLC state to Supabase instead of local files
- `execution/run_daily.py` — the single entry point Render will run. Same
  trading rules as `paper_trader.py`/`eod_scanner.py` (it imports
  `check_position_exit`/`get_position_size` from `execution/portfolio.py`
  unchanged), decides itself whether to run the full-day monitor or just
  the EOD scan based on what's in Supabase
- `requirements-render-live.txt` / `requirements-render-data.txt` — **two**
  dependency sets, not one (see "Why two venvs" below)
- `.gitignore` now excludes `venv-data/` (wasn't excluded before)
- `.python-version` pins Render's build to Python 3.11.9, matching what
  your local `venv/` already needed (neo_api_client requires 3.10+)

Supabase project **algo-trading-bot** (region ap-south-1) and its three
tables (`positions`, `trades`, `ohlc_state`) already exist — created this
session. Your two Sportsfest projects are untouched. GRASIM's current
position is already seeded into the `positions` table to match your
local `open_positions.csv`.

## Why two venvs, not one

First attempt used one combined `requirements-render.txt` — that failed:
`neo-api-client` (Kotak) hard-pins `websockets==8.1` in its own package
metadata, while `yfinance` requires `websockets>=13.0`. That's a real
conflict between the two libraries' declared dependencies, not a pin
choice on my end, so it can't be resolved by relaxing anything — pip
confirmed this with `ResolutionImpossible`.

This is exactly the same conflict your local `venv`/`venv-data` split was
already built to avoid (see project doc, Mistakes & Dead Ends), and
`run_daily.py` now follows that same pattern: it runs directly in a
"live" venv (Kotak Neo, no pandas/yfinance at all) and shells out to a
separate "data" venv for anything yfinance/pandas-based — the exact
subprocess bridge (`venv-data/bin/python`) your
`paper_trader.py`/`eod_scanner.py` already use locally, just with two
new venvs built specifically for Render (`render-live-venv` /
`render-data-venv`, not touching your existing `venv`/`venv-data`).

**Second round of the same problem:** the `supabase` Python SDK also
pulls in `realtime`, which needs `websockets>=11` — same clash with
neo-api-client's `websockets==8.1`, confirmed by testing. Fixed by
dropping the SDK entirely: `execution/state_store.py` now talks to
Supabase's REST API directly over HTTPS via `requests` (already needed
for Kotak), so the live venv adds zero new packages beyond what's already
required for Kotak Neo. `requirements-render-live.txt` no longer lists
`supabase` at all.

## Step 1 — Build both venvs locally and verify each one

**Use `python3.11`, not plain `python3`** — `neo_api_client` needs Python
3.10+, and `python3` defaults to 3.9 on your Mac (same reason your
existing `venv/` was rebuilt on 3.11):

```bash
cd ~/Documents/algo-trading-bot
rm -rf render-test-venv render-live-venv render-data-venv   # clean slate

# live venv — Kotak Neo + Supabase
python3.11 -m venv render-live-venv
render-live-venv/bin/pip install --upgrade pip
render-live-venv/bin/pip install -r requirements-render-live.txt
render-live-venv/bin/python -c "from dotenv import load_dotenv; load_dotenv(); from execution.portfolio import login; login()"

# data venv — yfinance + strategy deps
python3.11 -m venv render-data-venv
render-data-venv/bin/pip install --upgrade pip
render-data-venv/bin/pip install -r requirements-render-data.txt
render-data-venv/bin/python -c "import yfinance as yf; print(yf.download('RELIANCE.NS', period='5d'))"
```

Both need to succeed independently. If either fails, tell me the error —
these versions are trimmed from your already-working `requirements-live.txt`/
`requirements-data.txt`, so a failure here likely means something in the
trim was wrong, not a new conflict.

## Step 2 — Test run_daily.py itself, locally, before Render ever runs it

`run_daily.py` runs in the live venv and calls out to the data venv by
relative path (`render-data-venv/bin/python`), so run it from the repo
root with the live venv active — both venvs need to exist side by side:

```bash
cd ~/Documents/algo-trading-bot
source render-live-venv/bin/activate
export SUPABASE_URL="https://itenopojyephpeuzwaho.supabase.co"
export SUPABASE_KEY="<the SECRET key from Supabase dashboard -> Project Settings -> API — not the publishable one>"
python -m execution.run_daily
```

Since GRASIM is already seeded in Supabase, this should immediately go
into full-day monitor mode. Since it's after market hours right now, just
confirm it logs in, resolves tokens, and reads GRASIM's position from
Supabase correctly, then stop it with Ctrl+C — you don't need to run it
through a full trading day locally.

**Note:** from this point on, GRASIM's position exists in two places —
your local `open_positions.csv` (used by `paper_trader.py`/
`eod_scanner.py` if you keep running those manually) and Supabase (used
by `run_daily.py` on Render). Once Render is actually running the daily
job, stop running the local scripts too, or the two could drift out of
sync with each other on future trades.

## Step 3 — Push to GitHub

Render deploys from a git repo. Make it **private** — even though secrets
themselves stay out of git via `.env`/`.gitignore`, there's no reason to
make the strategy code public.

```bash
cd ~/Documents/algo-trading-bot
git status                      # sanity check
git ls-files | grep venv-data   # if this prints anything, venv-data got
                                 # committed before .gitignore excluded it —
                                 # run: git rm -r --cached venv-data
git add .gitignore .python-version requirements-render-live.txt requirements-render-data.txt execution/state_store.py execution/run_daily.py execution/tick_aggregator.py DEPLOY.md
git commit -m "Add Render/Supabase unattended paper trading path"
```

(`requirements-render.txt`, the original single-file attempt, is
deliberately left out of this — it's superseded and marked as such in the
file itself. Feel free to `rm requirements-render.txt` locally, or just
leave it untracked.)

Then on GitHub: create a new **private** repo named `algo-trading-bot`
(don't initialize it with a README), then:

```bash
git remote add origin git@github.com:<your-username>/algo-trading-bot.git
git branch -M main
git push -u origin main
```

(If `git remote add origin` fails because a remote already exists, use
`git remote set-url origin <url>` instead.)

## Step 4 — Tell me the repo URL

Once it's pushed, tell me (just the URL, e.g.
`https://github.com/<you>/algo-trading-bot`) and I'll create the Render
Cron Job with:
- **Schedule:** `30 3 * * 1-5` (03:30 UTC = 9:00 AM IST, Mon–Fri)
- **Build command:** creates both venvs inside the build container —
  ```
  python -m venv render-live-venv && render-live-venv/bin/pip install --upgrade pip && render-live-venv/bin/pip install -r requirements-render-live.txt && python -m venv render-data-venv && render-data-venv/bin/pip install --upgrade pip && render-data-venv/bin/pip install -r requirements-render-data.txt
  ```
- **Start command:** `render-live-venv/bin/python -m execution.run_daily`

## Step 5 — Set secrets in the Render dashboard (not here)

After the Cron Job exists, go to its Environment tab in the Render
dashboard and add these yourself — **please don't paste real values into
chat**, even to me (your own project doc already records one prior
incident of live credentials getting pasted into a chat and having to be
rotated):

| Key | Value |
|---|---|
| `NEO_CONSUMER_KEY` | from your Kotak Neo API app |
| `NEO_MOBILE` | your registered mobile |
| `NEO_UCC` | your Kotak UCC |
| `NEO_MPIN` | your MPIN |
| `NEO_TOTP_SECRET` | your TOTP setup key |
| `SUPABASE_URL` | `https://itenopojyephpeuzwaho.supabase.co` |
| `SUPABASE_KEY` | the **secret** key, from Supabase dashboard -> Project Settings -> API |

## Step 6 — Watch it closely for the first week

Don't fully trust this unattended on day one. Suggested rollout:
- First few trading days: let the Render cron job run, but also keep
  checking Supabase (`positions`/`trades` tables) and Render's logs each
  evening to confirm it actually did the right thing
- Keep `start_paper_trader.sh` available locally as a manual fallback if
  the cloud run misbehaves
- Once you've seen it handle a stop-loss or target hit correctly at
  least once unattended, it's reasonable to stop checking daily

## One open uncertainty, worth knowing

Render's Cron Job product is generally used for short scheduled tasks —
I haven't been able to confirm from here whether a ~6-hour run (full-day
monitor, when a position is open) is within normal bounds or whether
Render might time it out. Watch the first day a position is open closely;
if it gets killed partway through, the fallback is switching to a Render
**Background Worker** instead (always-on, no cron schedule, the script's
own market-hours check decides when to be active) — that's a small change
to `run_daily.py`'s entry point, not a rewrite, if it comes to that.
