"""
RichesseFX-style alert bot
---------------------------
Watches EUR_USD and GBP_USD all day, every day, for:
  1. Asia session (00:00-07:00 UTC) range sweep at any point afterward
  2. MSS (Market Structure Shift) confirmation after the sweep
  3. Price retracing into the 0.5 - 0.618 Fibonacci zone of the reversal leg

Sends you a Telegram message at EACH stage as it happens (sweep -> MSS -> Fib zone entry),
not just at the final signal. Stays silent only when nothing has happened yet.
This is an ALERT-ONLY tool. It never places trades. You still enter manually.

Data source: Twelve Data free API - free signup, no restricted-country issues, forex included.
Runs on a schedule via GitHub Actions (see .github/workflows/strategy_watch.yml)
"""

import os
import json
import requests
from datetime import datetime, timezone, timedelta

# ---------- Config ----------
PAIRS = {
    "EUR/USD": "EURUSD",
    "GBP/USD": "GBPUSD",
}
TD_INTERVAL = "5min"                # 5-minute candles for structure/MSS detection
ASIA_START_HOUR = 0                # UTC
ASIA_END_HOUR = 7                  # UTC
FIB_LOW = 0.5
FIB_HIGH = 0.618
STATE_FILE = os.path.join(os.path.dirname(__file__), "state.json")

TWELVE_DATA_API_KEY = os.environ["TWELVE_DATA_API_KEY"]
TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

TWELVE_DATA_BASE_URL = "https://api.twelvedata.com"


# ---------- Helpers ----------
def send_telegram(message: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    resp = requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": message}, timeout=10)
    resp.raise_for_status()


def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    return {}


def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2, default=str)


def fetch_candles(symbol: str, count: int = 300):
    """Fetch recent 5-minute candles from the Twelve Data free API."""
    url = f"{TWELVE_DATA_BASE_URL}/time_series"
    params = {
        "symbol": symbol,
        "interval": TD_INTERVAL,
        "outputsize": count,
        "timezone": "UTC",
        "order": "ASC",
        "apikey": TWELVE_DATA_API_KEY,
    }
    resp = requests.get(url, params=params, timeout=15)
    resp.raise_for_status()
    data = resp.json()

    if data.get("status") == "error":
        raise RuntimeError(f"Twelve Data error for {symbol}: {data.get('message')}")

    values = data.get("values", [])
    candles = []
    for c in values:
        candles.append({
            "time": datetime.strptime(c["datetime"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc),
            "open": float(c["open"]),
            "high": float(c["high"]),
            "low": float(c["low"]),
            "close": float(c["close"]),
        })
    return candles


def today_key(now: datetime) -> str:
    return now.strftime("%Y-%m-%d")


def get_asia_range(candles, now: datetime):
    """Return (asia_high, asia_low) for today's Asia session, or None if not yet complete."""
    today = now.date()
    asia_start = datetime(today.year, today.month, today.day, ASIA_START_HOUR, tzinfo=timezone.utc)
    asia_end = datetime(today.year, today.month, today.day, ASIA_END_HOUR, tzinfo=timezone.utc)

    if now < asia_end:
        return None  # Asia session hasn't closed yet today

    asia_candles = [c for c in candles if asia_start <= c["time"] < asia_end]
    if not asia_candles:
        return None

    highs = [c["high"] for c in asia_candles]
    lows = [c["low"] for c in asia_candles]
    return max(highs), min(lows)


def find_prior_structure_point(candles, sweep_index, direction, lookback=40):
    """
    Very simplified swing-point finder.
    direction='low_swept'  -> looking for the most recent local HIGH before the sweep (structure high)
    direction='high_swept' -> looking for the most recent local LOW before the sweep (structure low)
    """
    start = max(0, sweep_index - lookback)
    window = candles[start:sweep_index]
    if not window:
        return None
    if direction == "low_swept":
        return max(c["high"] for c in window)
    else:
        return min(c["low"] for c in window)


def analyze_pair(td_symbol: str, display_symbol: str, state: dict):
    now = datetime.now(timezone.utc)
    day = today_key(now)

    pair_state = state.get(display_symbol, {})
    if pair_state.get("date") != day:
        # New day - reset everything, including notification flags
        pair_state = {
            "date": day, "swept": None, "sweep_price": None, "sweep_index": None,
            "mss_confirmed": False, "leg_extreme": None, "alerted": False,
            "sweep_notified": False, "mss_notified": False,
        }

    # Safety net: if state.json was written by an older version of this script,
    # make sure the newer fields exist so nothing crashes today.
    pair_state.setdefault("sweep_notified", False)
    pair_state.setdefault("mss_notified", False)

    candles = fetch_candles(td_symbol, count=300)
    if len(candles) < 50:
        state[display_symbol] = pair_state
        return

    asia_range = get_asia_range(candles, now)
    if asia_range is None:
        # Still inside today's Asia session (00:00-07:00 UTC) - range isn't set yet, nothing to do
        state[display_symbol] = pair_state
        return
    asia_high, asia_low = asia_range

    # Candles from the moment Asia session closed today, onward - this is the whole watch window
    watch_candles = [(i, c) for i, c in enumerate(candles)
                      if c["time"].date() == now.date() and c["time"].hour >= ASIA_END_HOUR]

    # 1. Detect sweep (only look for the first one today)
    if pair_state["swept"] is None:
        for i, c in watch_candles:
            if c["high"] > asia_high:
                pair_state.update({"swept": "high", "sweep_price": c["high"], "sweep_index": i})
                break
            if c["low"] < asia_low:
                pair_state.update({"swept": "low", "sweep_price": c["low"], "sweep_index": i})
                break

        if pair_state["swept"] and not pair_state["sweep_notified"]:
            direction_txt = "Asia HIGH swept — expecting reversal DOWN" if pair_state["swept"] == "high" \
                else "Asia LOW swept — expecting reversal UP"
            send_telegram(
                f"⏳ {display_symbol}\n"
                f"{direction_txt}\n"
                f"Watching for MSS confirmation now..."
            )
            pair_state["sweep_notified"] = True

    # 2. Detect MSS confirmation (only after a sweep, and not yet confirmed)
    if pair_state["swept"] and not pair_state["mss_confirmed"]:
        sweep_index = pair_state["sweep_index"]
        direction = "low_swept" if pair_state["swept"] == "low" else "high_swept"
        structure_point = find_prior_structure_point(candles, sweep_index, direction)

        for i in range(sweep_index + 1, len(candles)):
            c = candles[i]
            if pair_state["swept"] == "low" and structure_point and c["close"] > structure_point:
                pair_state["mss_confirmed"] = True
                pair_state["leg_extreme"] = c["high"]  # running extreme for the leg
                break
            if pair_state["swept"] == "high" and structure_point and c["close"] < structure_point:
                pair_state["mss_confirmed"] = True
                pair_state["leg_extreme"] = c["low"]
                break
            # Invalidation: price re-sweeps further beyond original extreme -> keep tracking new extreme
            if pair_state["swept"] == "low" and c["low"] < pair_state["sweep_price"]:
                pair_state["sweep_price"] = c["low"]
            if pair_state["swept"] == "high" and c["high"] > pair_state["sweep_price"]:
                pair_state["sweep_price"] = c["high"]

        if pair_state["mss_confirmed"] and not pair_state["mss_notified"]:
            bias_txt = "bullish (buy bias)" if pair_state["swept"] == "low" else "bearish (sell bias)"
            send_telegram(
                f"🔎 {display_symbol}\n"
                f"MSS confirmed — {bias_txt}\n"
                f"Watching for retracement into the 0.5-0.618 Fib zone..."
            )
            pair_state["mss_notified"] = True

    # 3. Update running leg extreme + check Fib retracement zone -> final entry alert
    if pair_state["mss_confirmed"] and not pair_state["alerted"]:
        recent = candles[-10:]
        if pair_state["swept"] == "low":
            leg_low = pair_state["sweep_price"]
            leg_high = max(pair_state["leg_extreme"], max(c["high"] for c in recent))
            pair_state["leg_extreme"] = leg_high
            rng = leg_high - leg_low
            level_50 = leg_high - FIB_LOW * rng
            level_618 = leg_high - FIB_HIGH * rng
            current_low = candles[-1]["low"]
            if level_618 <= current_low <= level_50:
                send_telegram(
                    f"📈 {display_symbol} — BUY zone\n"
                    f"Asia low swept, bullish MSS confirmed.\n"
                    f"Price retraced into 0.5-0.618 Fib zone: {level_618:.5f} - {level_50:.5f}\n"
                    f"Current price: {candles[-1]['close']:.5f}\n"
                    f"Verify on chart before entering."
                )
                pair_state["alerted"] = True
        else:
            leg_high = pair_state["sweep_price"]
            leg_low = min(pair_state["leg_extreme"], min(c["low"] for c in recent))
            pair_state["leg_extreme"] = leg_low
            rng = leg_high - leg_low
            level_50 = leg_low + FIB_LOW * rng
            level_618 = leg_low + FIB_HIGH * rng
            current_high = candles[-1]["high"]
            if level_50 <= current_high <= level_618:
                send_telegram(
                    f"📉 {display_symbol} — SELL zone\n"
                    f"Asia high swept, bearish MSS confirmed.\n"
                    f"Price retraced into 0.5-0.618 Fib zone: {level_50:.5f} - {level_618:.5f}\n"
                    f"Current price: {candles[-1]['close']:.5f}\n"
                    f"Verify on chart before entering."
                )
                pair_state["alerted"] = True

    state[display_symbol] = pair_state


def main():
    state = load_state()
    for td_symbol, display_symbol in PAIRS.items():
        try:
            analyze_pair(td_symbol, display_symbol, state)
        except Exception as e:
            print(f"Error processing {display_symbol}: {e}")
    save_state(state)


if __name__ == "__main__":
    main()
