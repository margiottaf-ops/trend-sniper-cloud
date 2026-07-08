# Trend Sniper AI v2
# GitHub Actions + Telegram
# Uso demo/didattico. Non è consulenza finanziaria.
# Controlla sempre TradingView prima di entrare.

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

# Cambia a True solo se vuoi inviare un messaggio test.
TEST_MODE = False

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
RR_FINAL = 4.0

EMA_FAST = 20
EMA_MID = 50
EMA_SLOW = 200

RSI_LEN = 14
ADX_LEN = 14
ATR_LEN = 14
PIVOT_LEN = 6
SWING_STOP_LEN = 14
ATR_MULT = 1.5

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
        print("ERRORE: mancano TELEGRAM_BOT_TOKEN o TELEGRAM_CHAT_ID")
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    data = urllib.parse.urlencode({
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": "true"
    }).encode("utf-8")

    req = urllib.request.Request(url, data=data, method="POST")
    with urllib.request.urlopen(req, timeout=25) as r:
        response = r.read().decode("utf-8")
        print(response)
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

        rows.append({
            "t": int(ts),
            "open": float(o),
            "high": float(h),
            "low": float(l),
            "close": float(c),
            "volume": float(v)
        })
    return rows


def to_4h(rows):
    buckets = {}
    for r in rows:
        bucket = r["t"] - (r["t"] % (4 * 3600))
        if bucket not in buckets:
            buckets[bucket] = {
                "t": bucket,
                "open": r["open"],
                "high": r["high"],
                "low": r["low"],
                "close": r["close"],
                "volume": r["volume"]
            }
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
            tr.append(max(
                r["high"] - r["low"],
                abs(r["high"] - pc),
                abs(r["low"] - pc)
            ))
    return ema(tr, length)


def adx(rows, length=14):
    plus_dm = [0]
    minus_dm = [0]
    tr = [rows[0]["high"] - rows[0]["low"]]

    for i in range(1, len(rows)):
        up = rows[i]["high"] - rows[i - 1]["high"]
        down = rows[i - 1]["low"] - rows[i]["low"]

        plus_dm.append(up if up > down and up > 0 else 0)
        minus_dm.append(down if down > up and down > 0 else 0)

        tr.append(max(
            rows[i]["high"] - rows[i]["low"],
            abs(rows[i]["high"] - rows[i - 1]["close"]),
            abs(rows[i]["low"] - rows[i - 1]["close"])
        ))

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
    structure = 0
    last_high = None
    last_low = None

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
    last = rows[-1]
    prev = rows[-2]

    body = abs(last["close"] - last["open"])
    upper = last["high"] - max(last["open"], last["close"])
    lower = min(last["open"], last["close"]) - last["low"]

    bull_engulf = (
        last["close"] > last["open"]
        and prev["close"] < prev["open"]
        and last["close"] >= prev["open"]
        and last["open"] <= prev["close"]
    )

    bear_engulf = (
        last["close"] < last["open"]
        and prev["close"] > prev["open"]
        and last["close"] <= prev["open"]
        and last["open"] >= prev["close"]
    )

    hammer = lower > body * 2 and upper <= body * 1.25 and last["close"] > last["open"]
    shooting = upper > body * 2 and lower <= body * 1.25 and last["close"] < last["open"]

    bull = last["close"] > last["open"] and (bull_engulf or hammer or last["close"] > prev["high"])
    bear = last["close"] < last["open"] and (bear_engulf or shooting or last["close"] < prev["low"])

    candle_type = "Nessuna"
    if bull_engulf:
        candle_type = "Bullish Engulfing"
    elif bear_engulf:
        candle_type = "Bearish Engulfing"
    elif hammer:
        candle_type = "Hammer"
    elif shooting:
        candle_type = "Shooting Star"
    elif last["close"] > prev["high"]:
        candle_type = "Breakout candela precedente"
    elif last["close"] < prev["low"]:
        candle_type = "Breakdown candela precedente"

    return bull, bear, candle_type


def setup_grade(score):
    if score >= 95:
        return "A+"
    if score >= 90:
        return "A"
    if score >= 86:
        return "B+"
    if score >= 78:
        return "B"
    return "C"


def fmt(x):
    if abs(x) >= 100:
        return f"{x:.2f}"
    if abs(x) >= 10:
        return f"{x:.3f}"
    return f"{x:.5f}"


def estimate_lot(symbol, entry, sl):
    risk_money = ACCOUNT_SIZE * RISK_PERCENT / 100
    distance = abs(entry - sl)

    if distance <= 0:
        return 0.0

    if "JPY" in symbol:
        pip_size = 0.01
    elif symbol == "XAUUSD":
        pip_size = 0.10
    elif symbol in ["US100", "BTCUSD", "ETHUSD"]:
        pip_size = 1.0
    else:
        pip_size = 0.0001

    pips = distance / pip_size

    if symbol in ["XAUUSD", "US100", "BTCUSD", "ETHUSD"]:
        units = risk_money / distance
        return round(units, 3)

    lot = risk_money / (pips * 10) if pips > 0 else 0.0
    return round(lot, 2)


def analyze(name, yahoo_symbol):
    rows = to_4h(yahoo_1h(yahoo_symbol))

    if len(rows) < 220:
        return {
            "symbol": name,
            "status": "NO DATA",
            "score": 0,
            "grade": "N/A",
            "note": "Dati insufficienti"
        }

    closes = [r["close"] for r in rows]

    ema20 = ema(closes, EMA_FAST)
    ema50 = ema(closes, EMA_MID)
    ema200 = ema(closes, EMA_SLOW)

    rsi_v = rsi(closes, RSI_LEN)
    atr_v = atr(rows, ATR_LEN)
    adx_v = adx(rows, ADX_LEN)

    last = rows[-1]
    close = last["close"]

    ema_long = close > ema200[-1] and ema20[-1] > ema50[-1] and ema50[-1] > ema200[-1]
    ema_short = close < ema200[-1] and ema20[-1] < ema50[-1] and ema50[-1] < ema200[-1]

    rsi_long = 50 < rsi_v[-1] < 72
    rsi_short = 28 < rsi_v[-1] < 50

    adx_ok = adx_v[-1] >= ADX_MIN
    pull_ok = abs(close - ema20[-1]) <= atr_v[-1] * PULL_ATR

    structure = detect_structure(rows, PIVOT_LEN)
    structure_long = structure == 1
    structure_short = structure == -1

    bull_confirm, bear_confirm, candle_type = candle_confirm(rows)

    long_score = 0
    long_score += 30 if ema_long else 0
    long_score += 15 if structure_long else 0
    long_score += 15 if rsi_long else 0
    long_score += 10 if adx_ok else 0
    long_score += 15 if pull_ok else 0
    long_score += 10 if bull_confirm else 0
    long_score += 5

    short_score = 0
    short_score += 30 if ema_short else 0
    short_score += 15 if structure_short else 0
    short_score += 15 if rsi_short else 0
    short_score += 10 if adx_ok else 0
    short_score += 15 if pull_ok else 0
    short_score += 10 if bear_confirm else 0
    short_score += 5

    side = "WAIT"
    score = max(long_score, short_score)

    if long_score >= MIN_SCORE and ema_long and structure_long and rsi_long and adx_ok and pull_ok and bull_confirm:
        side = "BUY"
        score = long_score
    elif short_score >= MIN_SCORE and ema_short and structure_short and rsi_short and adx_ok and pull_ok and bear_confirm:
        side = "SELL"
        score = short_score

    result = {
        "symbol": name,
        "status": side,
        "score": score,
        "grade": setup_grade(score),
        "price": close,
        "rsi": rsi_v[-1],
        "adx": adx_v[-1],
        "candle_type": candle_type,
        "trend": "LONG" if ema_long else "SHORT" if ema_short else "NEUTRALE",
        "structure": "BULLISH" if structure_long else "BEARISH" if structure_short else "NEUTRALE",
        "candle_time": datetime.fromtimestamp(last["t"], tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "candle_id": str(last["t"]),
        "checks": {
            "EMA trend": ema_long or ema_short,
            "BOS struttura": (ema_long and structure_long) or (ema_short and structure_short),
            "RSI": (ema_long and rsi_long) or (ema_short and rsi_short),
            "ADX": adx_ok,
            "Pullback": pull_ok,
            "Candela": (ema_long and bull_confirm) or (ema_short and bear_confirm),
        }
    }

    if side == "WAIT":
        return result

    entry = close

    if side == "BUY":
        sl = min(entry - atr_v[-1] * ATR_MULT, min([r["low"] for r in rows[-SWING_STOP_LEN:]]))
        risk = entry - sl
        tp1 = entry + risk
        tp2 = entry + risk * 2
        tp3 = entry + risk * 3
        tp4 = entry + risk * RR_FINAL
    else:
        sl = max(entry + atr_v[-1] * ATR_MULT, max([r["high"] for r in rows[-SWING_STOP_LEN:]]))
        risk = sl - entry
        tp1 = entry - risk
        tp2 = entry - risk * 2
        tp3 = entry - risk * 3
        tp4 = entry - risk * RR_FINAL

    result.update({
        "entry": entry,
        "sl": sl,
        "tp1": tp1,
        "tp2": tp2,
        "tp3": tp3,
        "tp4": tp4,
        "risk_money": ACCOUNT_SIZE * RISK_PERCENT / 100,
        "lot": estimate_lot(name, entry, sl),
    })

    return result


def telegram_alert(r):
    emoji = "🟢" if r["status"] == "BUY" else "🔴"
    stars = "★★★★★" if r["score"] >= 95 else "★★★★☆" if r["score"] >= 90 else "★★★☆☆"

    checks = "\n".join([
        f"{'✅' if ok else '❌'} {name}"
        for name, ok in r["checks"].items()
    ])

    lot_label = "Lotto indicativo" if r["symbol"] not in ["XAUUSD", "US100", "BTCUSD", "ETHUSD"] else "Unità indicative"

    return (
        f"🚨 <b>TREND SNIPER AI v2</b>\n\n"
        f"{emoji} <b>{r['status']} {r['symbol']}</b>\n"
        f"{stars}\n"
        f"Qualità: <b>{r['grade']} - {r['score']}/100</b>\n"
        f"Timeframe: <b>4H</b>\n"
        f"Candela chiusa: {r['candle_time']}\n\n"
        f"<b>Livelli operativi</b>\n"
        f"Entry: <b>{fmt(r['entry'])}</b>\n"
        f"Stop Loss: <b>{fmt(r['sl'])}</b>\n"
        f"TP1 1R: <b>{fmt(r['tp1'])}</b>\n"
        f"TP2 / Break-even: <b>{fmt(r['tp2'])}</b>\n"
        f"TP3 3R: <b>{fmt(r['tp3'])}</b>\n"
        f"TP4 1:{RR_FINAL}: <b>{fmt(r['tp4'])}</b>\n\n"
        f"<b>Gestione rischio</b>\n"
        f"Capitale demo: {ACCOUNT_SIZE} €\n"
        f"Rischio: {RISK_PERCENT}%\n"
        f"Perdita max indicativa: {r['risk_money']:.2f} €\n"
        f"{lot_label}: <b>{r['lot']}</b>\n\n"
        f"<b>Motivo del segnale</b>\n"
        f"Trend: {r['trend']}\n"
        f"Struttura: {r['structure']}\n"
        f"Candela: {r['candle_type']}\n"
        f"RSI: {r['rsi']:.2f}\n"
        f"ADX: {r['adx']:.2f}\n\n"
        f"{checks}\n\n"
        f"⚠️ Apri TradingView e conferma visivamente prima di entrare in demo."
    )


def test_message():
    return (
        "✅ <b>Trend Sniper AI v2</b>\n\n"
        "Test Telegram completato con successo.\n"
        "GitHub Actions → Telegram funziona.\n\n"
        "Modalità operativa: scanner 4H attivo."
    )


def main():
    if TEST_MODE:
        send_telegram(test_message())
        return

    state = load_state()
    alerts = 0
    summary = []

    for name, yahoo_symbol in WATCHLIST.items():
        try:
            r = analyze(name, yahoo_symbol)
            summary.append(f"{name}: {r['status']} | Score {r['score']} | Grade {r['grade']} | Trend {r.get('trend', '-')}")
            if r["status"] in ["BUY", "SELL"]:
                key = f"{r['symbol']}_{r['status']}_{r['candle_id']}"
                if state.get(key):
                    summary.append(f"{name}: alert già inviato")
                    continue

                send_telegram(telegram_alert(r))
                state[key] = datetime.now(timezone.utc).isoformat()
                alerts += 1

        except Exception as e:
            summary.append(f"{name}: ERRORE {e}")

    if len(state) > 200:
        keys = list(state.keys())[-100:]
        state = {k: state[k] for k in keys}

    save_state(state)
    print("\n".join(summary))
    print(f"Alert inviati: {alerts}")


if __name__ == "__main__":
    main()
