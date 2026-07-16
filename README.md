# RichesseFX-style Alert Bot (EURUSD / GBPUSD)

Watches for: **Asia range sweep during London AM → MSS confirmation → 0.5-0.618 Fib retracement**,
then sends you a free Telegram push notification. It never places trades — you enter manually.

Cost: **$0**. Runs on GitHub Actions (free), pulls data from Twelve Data's free API (free, works from
anywhere — no OANDA-style country restrictions), and notifies you via Telegram (free).

---

## Setup (about 15 minutes, one time)

### 1. Create your Telegram bot
1. In Telegram, message **@BotFather** → send `/newbot` → follow the prompts.
2. BotFather gives you a **bot token** (looks like `123456789:ABCdef...`). Save it.
3. Send any message to your new bot (e.g. "hi") so it can message you back.
4. Get your **chat ID**: message **@userinfobot** on Telegram, it replies with your numeric ID. Save it.

### 2. Get a free Twelve Data API key
1. Go to twelvedata.com → sign up for the free **Basic** plan (no card needed).
2. Once logged in, your **API key** is shown on your dashboard. Save it.
3. Free plan gives you 800 API calls/day and 8/minute — plenty, since this bot only queries during
   the London AM window (07:00–11:00 UTC), roughly 96 calls/day for both pairs combined.

### 3. Create a GitHub repo
1. Go to github.com → New repository → make it **public** (so Actions minutes are unlimited/free) → create it.
2. Upload all the files from this folder (`main.py`, `requirements.txt`, `state.json`, and the
   `.github/workflows/strategy_watch.yml` folder — keep that folder structure exactly as is).

### 4. Add your secrets
In your new repo: **Settings → Secrets and variables → Actions → New repository secret**. Add these three:
- `TWELVE_DATA_API_KEY`
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`

### 5. Turn it on
1. Go to the **Actions** tab in your repo → you should see "Strategy Watch" → click **Enable workflow** if prompted.
2. Click **Run workflow** once manually to test it works (won't send a message unless a real setup is live, but check the run logs for errors).
3. From then on, it runs automatically every 5 minutes, all day, for free.

---

## How the logic works

- **Asia range**: high/low of price between 00:00–07:00 UTC each day.
- **Sweep**: first time price during London AM (07:00–11:00 UTC) trades beyond that Asia high or low.
- **MSS (Market Structure Shift)**: after the sweep, price must close back beyond the last swing point in the
  opposite direction — confirming the reversal.
- **Fib zone**: once MSS confirms, the leg from the sweep extreme to the reversal point is measured, and you
  get alerted the moment price retraces into the 0.5–0.618 zone of that leg.

**Note:** the MSS/swing detection here is a simplified, rules-based approximation of the discretionary concept
in the PDF — it's a solid trigger for "go look at the chart now," not a perfect substitute for your own read of
the structure. Always confirm visually before entering, exactly as you planned.

## Adjusting the strategy
Open `main.py` — near the top you can change:
- `ASIA_START_HOUR` / `ASIA_END_HOUR` — Asia session window (UTC)
- `LONDON_AM_START_HOUR` / `LONDON_AM_END_HOUR` — when sweeps are monitored (UTC)
- `FIB_LOW` / `FIB_HIGH` — retracement zone bounds
- `TD_INTERVAL` — candle timeframe used for MSS detection (default 5min)
