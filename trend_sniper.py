# trend_sniper.py
# Scanner gratuito per GitHub Actions + Telegram.
# Timeframe: 4H ricostruito da dati 1H Yahoo Finance.
# Uso demo/didattico: controlla sempre il grafico prima di entrare.

import os
import json
import time
import urllib.request
import urllib.parse
from pathlib import Path
from datetime import datetime, timezone

STATE_FILE = Path("state.json")

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

WATCHLIST = {
    "EURUSD": "EURUSD=X",
    "GBPUSD": "GBPUSD=X",
    "USDJPY": "JPY=X",
    "AUDUSD": "AUDUSD=X",
    "USDCAD": "CAD=X",
    "EURJPY": "EURJPY=X",
    "GBPJPY": "GBPJPY=X",
    "XAUUSD": "GC=F",
    "US100": "NQ=F",
    "BTCUSD": "BTC-USD",
    "ETHUSD": "ETH-USD",
}

MODE = "MOLTO_FILTRATA"
ACCOUNT_SIZE = 1000
RISK_PERCENT = 1.0
RR = 4.0

if MODE == "MOLTO_FILTRATA":
    MIN_SCORE = 86
    PULL_ATR = 0.60
    ADX_MIN = 20
elif MODE == "BILANCIATA":
    MIN_SCORE = 78
    PULL_ATR = 0.85
    ADX_MIN = 16
else:
    MIN_SCORE = 70
    PULL_ATR = 1.10
    ADX_MIN = 12


def load_state():
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_state(state):
    STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")


def http_get_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=25) as r:
        return json.loads(r.read().decode("utf-8"))


def send_telegram(text):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Manca TELEGRAM_BOT_TOKEN o TELEGRAM_CHAT_ID")
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    data = urllib.parse.urlencode({
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML"
    }).encode("utf-8")

    req = urllib.request.Request(url, data=data, method="POST")
    with urllib.request.urlopen(req, timeout=25) as r:
        print(r.read().decode("utf-8"))
    return True


def yahoo_1h(symbol):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(symbol)}?range=60d&interval=1h"
    data = http_get_json(url)
    result = data["chart"]["result"][0]
    timestamps = result["timestamp"]
    q = result["indicators"]["quote"][0]

    rows = []
    for i, ts in enumerate(timestamps):
        o = q["open"][i]
        h = q["high"][i]
        l = q["low"][i]
        c = q["close"][i]
        v = q.get("volume", [0] * len(timestamps))[i] or 0
        if o is None or h is None or l is None or c is None:
            continue
        rows.append({"t": int(ts), "open": float(o), "high": float(h), "low": float(l), "close": float(c), "volume": float(v)})
    return rows


def to_4h(rows):
    buckets = {}
    for r in rows:
        bucket = r["t"] - (r["t"] % (4 * 3600))
        if bucket not in buckets:
            buckets[bucket] = {"t": bucket, "open": r["open"], "high": r["high"], "low": r["low"], "close": r["close"], "volume": r["volume"]}
        else:
            b = buckets[bucket]
            b["high"] = max(b["high"], r["high"])
            b["low"] = min(b["low"], r["low"])
            b["close"] = r["close"]
            b["volume"] += r["volume"]
    out = [buckets[k] for k in sorted(buckets.keys())]
    now = int(time.time())
    if out and now < out[-1]["t"] + 4 * 3600:
        out = out[:-1]
    return out


def ema(values, length):
    alpha = 2 / (length + 1)
    out = [values[0]]
    for v in values[1:]:
        out.append(v * alpha + out[-1] * (1 - alpha))
    return out


def rsi(values, length=14):
    gains, losses = [0], [0]
    for i in range(1, len(values)):
        d = values[i] - values[i - 1]
        gains.append(max(d, 0))
        losses.append(max(-d, 0))
    avg_gain = ema(gains, length)
    avg_loss = ema(losses, length)
    out = []
    for g, l in zip(avg_gain, avg_loss):
        out.append(100 if l == 0 else 100 - (100 / (1 + g / l)))
    return out


def atr(rows, length=14):
    tr = []
    for i, r in enumerate(rows):
        if i == 0:
            tr.append(r["high"] - r["low"])
        else:
            pc = rows[i - 1]["close"]
            tr.append(max(r["high"] - r["low"], abs(r["high"] - pc), abs(r["low"] - pc)))
    return ema(tr, length)


def adx(rows, length=14):
    plus_dm, minus_dm, tr = [0], [0], [rows[0]["high"] - rows[0]["low"]]
    for i in range(1, len(rows)):
        up = rows[i]["high"] - rows[i - 1]["high"]
        down = rows[i - 1]["low"] - rows[i]["low"]
        plus_dm.append(up if up > down and up > 0 else 0)
        minus_dm.append(down if down > up and down > 0 else 0)
        tr.append(max(rows[i]["high"] - rows[i]["low"], abs(rows[i]["high"] - rows[i - 1]["close"]), abs(rows[i]["low"] - rows[i - 1]["close"])))
    atr_s = ema(tr, length)
    plus_s = ema(plus_dm, length)
    minus_s = ema(minus_dm, length)
    dx = []
    for a, p, m in zip(atr_s, plus_s, minus_s):
        if a == 0 or p + m == 0:
            dx.append(0)
        else:
            plus_di = 100 * p / a
            minus_di = 100 * m / a
            dx.append(100 * abs(plus_di - minus_di) / (plus_di + minus_di))
    return ema(dx, length)


def detect_structure(rows, pivot_len=6):
    structure, last_high, last_low = 0, None, None
    for i in range(pivot_len, len(rows) - pivot_len):
        highs = [x["high"] for x in rows[i - pivot_len:i + pivot_len + 1]]
        lows = [x["low"] for x in rows[i - pivot_len:i + pivot_len + 1]]
        if rows[i]["high"] == max(highs):
            last_high = rows[i]["high"]
        if rows[i]["low"] == min(lows):
            last_low = rows[i]["low"]
        if last_high is not None and rows[i]["close"] > last_high:
            structure = 1
        if last_low is not None and rows[i]["close"] < last_low:
            structure = -1
    return structure


def candle_confirm(rows):
    last, prev = rows[-1], rows[-2]
    body = abs(last["close"] - last["open"])
    upper = last["high"] - max(last["open"], last["close"])
    lower = min(last["open"], last["close"]) - last["low"]

    bull_engulf = last["close"] > last["open"] and prev["close"] < prev["open"] and last["close"] >= prev["open"] and last["open"] <= prev["close"]
    bear_engulf = last["close"] < last["open"] and prev["close"] > prev["open"] and last["close"] <= prev["open"] and last["open"] >= prev["close"]

    hammer = lower > body * 2 and upper <= body * 1.25 and last["close"] > last["open"]
    shooting = upper > body * 2 and lower <= body * 1.25 and last["close"] < last["open"]

    bull = last["close"] > last["open"] and (bull_engulf or hammer or last["close"] > prev["high"])
    bear = last["close"] < last["open"] and (bear_engulf or shooting or last["close"] < prev["low"])
    return bull, bear


def analyze(name, yahoo_symbol):
    rows = to_4h(yahoo_1h(yahoo_symbol))
    if len(rows) < 220:
        return {"symbol": name, "status": "NO DATA", "score": 0}

    closes = [r["close"] for r in rows]
    ema20, ema50, ema200 = ema(closes, 20), ema(closes, 50), ema(closes, 200)
    rsi_v, atr_v, adx_v = rsi(closes, 14), atr(rows, 14), adx(rows, 14)

    last = rows[-1]
    close = last["close"]

    ema_long = close > ema200[-1] and ema20[-1] > ema50[-1] and ema50[-1] > ema200[-1]
    ema_short = close < ema200[-1] and ema20[-1] < ema50[-1] and ema50[-1] < ema200[-1]
    rsi_long = 50 < rsi_v[-1] < 72
    rsi_short = 28 < rsi_v[-1] < 50
    adx_ok = adx_v[-1] >= ADX_MIN
    pull_ok = abs(close - ema20[-1]) <= atr_v[-1] * PULL_ATR

    structure = detect_structure(rows, 6)
    structure_long = structure == 1
    structure_short = structure == -1
    bull_confirm, bear_confirm = candle_confirm(rows)

    long_score = sum([30 if ema_long else 0, 15 if structure_long else 0, 15 if rsi_long else 0, 10 if adx_ok else 0, 15 if pull_ok else 0, 10 if bull_confirm else 0, 5])
    short_score = sum([30 if ema_short else 0, 15 if structure_short else 0, 15 if rsi_short else 0, 10 if adx_ok else 0, 15 if pull_ok else 0, 10 if bear_confirm else 0, 5])

    side = "WAIT"
    score = max(long_score, short_score)
    if long_score >= MIN_SCORE and ema_long and structure_long and rsi_long and adx_ok and pull_ok and bull_confirm:
        side, score = "BUY", long_score
    elif short_score >= MIN_SCORE and ema_short and structure_short and rsi_short and adx_ok and pull_ok and bear_confirm:
        side, score = "SELL", short_score

    out = {
        "symbol": name,
        "status": side,
        "score": score,
        "price": close,
        "rsi": rsi_v[-1],
        "adx": adx_v[-1],
        "candle_time": datetime.fromtimestamp(last["t"], tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "candle_id": str(last["t"]),
    }

    if side == "WAIT":
        return out

    entry = close
    if side == "BUY":
        sl = min(entry - atr_v[-1] * 1.5, min([r["low"] for r in rows[-14:]]))
        risk = entry - sl
        tp1, tp2, tp3, tp4 = entry + risk, entry + risk * 2, entry + risk * 3, entry + risk * RR
    else:
        sl = max(entry + atr_v[-1] * 1.5, max([r["high"] for r in rows[-14:]]))
        risk = sl - entry
        tp1, tp2, tp3, tp4 = entry - risk, entry - risk * 2, entry - risk * 3, entry - risk * RR

    out.update({"entry": entry, "sl": sl, "tp1": tp1, "tp2": tp2, "tp3": tp3, "tp4": tp4, "risk_money": ACCOUNT_SIZE * RISK_PERCENT / 100})
    return out


def fmt(x):
    if abs(x) >= 100:
        return f"{x:.2f}"
    if abs(x) >= 10:
        return f"{x:.3f}"
    return f"{x:.5f}"


def alert_text(r):
    emoji = "🟢" if r["status"] == "BUY" else "🔴"
    return (
        f"🚨 <b>TREND SNIPER CLOUD</b>\n\n"
        f"{emoji} <b>{r['status']} {r['symbol']}</b>\n"
        f"Timeframe: 4H\n"
        f"Candela: {r['candle_time']}\n"
        f"Score: <b>{r['score']}/100</b>\n\n"
        f"Entry: <b>{fmt(r['entry'])}</b>\n"
        f"Stop Loss: <b>{fmt(r['sl'])}</b>\n"
        f"TP1 1R: <b>{fmt(r['tp1'])}</b>\n"
        f"TP2 / Break-even: <b>{fmt(r['tp2'])}</b>\n"
        f"TP3 3R: <b>{fmt(r['tp3'])}</b>\n"
        f"TP4 1:{RR}: <b>{fmt(r['tp4'])}</b>\n\n"
        f"Rischio demo indicativo: {r['risk_money']:.2f}\n"
        f"RSI: {r['rsi']:.2f}\n"
        f"ADX: {r['adx']:.2f}\n\n"
        f"Apri TradingView e conferma prima di entrare in demo."
    )


def main():
    state = load_state()
    alerts = 0
    summary = []

    for name, yahoo_symbol in WATCHLIST.items():
        try:
            r = analyze(name, yahoo_symbol)
            summary.append(f"{name}: {r['status']} score {r['score']}")
            if r["status"] in ["BUY", "SELL"]:
                key = f"{r['symbol']}_{r['status']}_{r['candle_id']}"
                if state.get(key):
                    summary.append(f"{name}: alert già inviato")
                    continue
                send_telegram(alert_text(r))
                state[key] = datetime.now(timezone.utc).isoformat()
                alerts += 1
        except Exception as e:
            summary.append(f"{name}: ERRORE {e}")

    # tiene pulito lo stato
    if len(state) > 200:
        keys = list(state.keys())[-100:]
        state = {k: state[k] for k in keys}

    save_state(state)
    print("\n".join(summary))
    print(f"Alert inviati: {alerts}")


if __name__ == "__main__":
    main()
