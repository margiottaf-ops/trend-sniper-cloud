# Trend Sniper AI v6 - Multi-Timeframe TEST
# GitHub Actions + Telegram
# Timeframe: 4H, 1H, 15M, 5M
# Uso demo/didattico. Non è consulenza finanziaria.

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

# Metti True solo per testare Telegram.
TEST_MODE = False

ACCOUNT_SIZE = 1000
RR_FINAL = 4.0

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

# enabled=True/False per accendere o spegnere un timeframe.
# 4H = principale
# 1H = test secondario
# 15M/5M = solo raccolta dati/demo, molto più rumorosi
PROFILES = {
    "4H": {
        "enabled": True,
        "source_interval": "1h",
        "period": "60d",
        "resample_seconds": 4 * 3600,
        "min_score": 86,
        "pull_atr": 0.60,
        "adx_min": 20,
        "risk_percent": 1.00,
    },
    "1H": {
        "enabled": True,
        "source_interval": "1h",
        "period": "60d",
        "resample_seconds": 1 * 3600,
        "min_score": 90,
        "pull_atr": 0.55,
        "adx_min": 22,
        "risk_percent": 0.50,
    },
    "15M": {
        "enabled": True,
        "source_interval": "15m",
        "period": "30d",
        "resample_seconds": 15 * 60,
        "min_score": 94,
        "pull_atr": 0.45,
        "adx_min": 25,
        "risk_percent": 0.25,
    },
    "5M": {
        "enabled": True,
        "source_interval": "5m",
        "period": "7d",
        "resample_seconds": 5 * 60,
        "min_score": 97,
        "pull_atr": 0.35,
        "adx_min": 28,
        "risk_percent": 0.10,
    },
}

EMA_FAST = 20
EMA_MID = 50
EMA_SLOW = 200
RSI_LEN = 14
ADX_LEN = 14
ATR_LEN = 14
PIVOT_LEN = 6
SWING_STOP_LEN = 14
ATR_MULT = 1.5


def load_state():
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_state(state):
    STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")


def request_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def send_telegram(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("ERRORE TELEGRAM: token o chat id mancanti")
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    data = urllib.parse.urlencode({
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": "true",
    }).encode("utf-8")

    req = urllib.request.Request(url, data=data, method="POST")
    with urllib.request.urlopen(req, timeout=30) as r:
        response = r.read().decode("utf-8")
        print(response)
    return True


def yahoo_download(symbol, period, interval):
    url = (
        "https://query1.finance.yahoo.com/v8/finance/chart/"
        f"{urllib.parse.quote(symbol)}?range={period}&interval={interval}"
    )
    data = request_json(url)

    if not data.get("chart") or not data["chart"].get("result"):
        return []

    result = data["chart"]["result"][0]
    timestamps = result.get("timestamp", [])
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
            "volume": float(v),
        })
    return rows


def resample_rows(rows, seconds):
    if not rows:
        return []

    # 1H, 15M, 5M arrivano già da Yahoo nel timeframe richiesto.
    if seconds in (3600, 900, 300):
        out = rows[:]
        now = int(time.time())
        if out and now < out[-1]["t"] + seconds:
            out = out[:-1]
        return out

    buckets = {}
    for r in rows:
        b = r["t"] - (r["t"] % seconds)
        if b not in buckets:
            buckets[b] = {
                "t": b,
                "open": r["open"],
                "high": r["high"],
                "low": r["low"],
                "close": r["close"],
                "volume": r["volume"],
            }
        else:
            x = buckets[b]
            x["high"] = max(x["high"], r["high"])
            x["low"] = min(x["low"], r["low"])
            x["close"] = r["close"]
            x["volume"] += r["volume"]

    out = [buckets[k] for k in sorted(buckets.keys())]
    now = int(time.time())
    if out and now < out[-1]["t"] + seconds:
        out = out[:-1]
    return out


def ema(values, length):
    alpha = 2 / (length + 1)
    out = [values[0]]
    for v in values[1:]:
        out.append(v * alpha + out[-1] * (1 - alpha))
    return out


def rsi(values, length=14):
    gains = [0]
    losses = [0]

    for i in range(1, len(values)):
        d = values[i] - values[i - 1]
        gains.append(max(d, 0))
        losses.append(max(-d, 0))

    avg_gain = ema(gains, length)
    avg_loss = ema(losses, length)

    out = []
    for g, l in zip(avg_gain, avg_loss):
        if l == 0:
            out.append(100)
        else:
            rs = g / l
            out.append(100 - (100 / (1 + rs)))
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
                abs(r["low"] - pc),
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
            abs(rows[i]["low"] - rows[i - 1]["close"]),
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
        hi_window = [x["high"] for x in rows[i - pivot_len:i + pivot_len + 1]]
        lo_window = [x["low"] for x in rows[i - pivot_len:i + pivot_len + 1]]

        if rows[i]["high"] == max(hi_window):
            last_high = rows[i]["high"]
        if rows[i]["low"] == min(lo_window):
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
    if score >= 97:
        return "A+"
    if score >= 94:
        return "A"
    if score >= 90:
        return "B+"
    if score >= 86:
        return "B"
    return "C"


def fmt(x):
    if abs(x) >= 100:
        return f"{x:.2f}"
    if abs(x) >= 10:
        return f"{x:.3f}"
    return f"{x:.5f}"


def estimate_lot(symbol, entry, sl, risk_percent):
    risk_money = ACCOUNT_SIZE * risk_percent / 100
    distance = abs(entry - sl)

    if distance <= 0:
        return 0.0

    if "JPY" in symbol:
        pip_size = 0.01
    elif symbol == "XAUUSD":
        pip_size = 0.10
    elif symbol in ["US100", "BTCUSD", "ETHUSD"]:
        return round(risk_money / distance, 3)
    else:
        pip_size = 0.0001

    pips = distance / pip_size
    lot = risk_money / (pips * 10) if pips > 0 else 0.0
    return round(lot, 2)


def analyze_symbol(symbol_name, yahoo_symbol, timeframe, cfg):
    raw = yahoo_download(yahoo_symbol, cfg["period"], cfg["source_interval"])
    rows = resample_rows(raw, cfg["resample_seconds"])

    if len(rows) < 220:
        return {
            "symbol": symbol_name,
            "timeframe": timeframe,
            "status": "NO DATA",
            "score": 0,
            "grade": "N/A",
            "note": f"Dati insufficienti: {len(rows)} barre",
        }

    closes = [r["close"] for r in rows]

    ema20 = ema(closes, EMA_FAST)
    ema50 = ema(closes, EMA_MID)
    ema200 = ema(closes, EMA_SLOW)
    rsi_values = rsi(closes, RSI_LEN)
    atr_values = atr(rows, ATR_LEN)
    adx_values = adx(rows, ADX_LEN)

    last = rows[-1]
    close = last["close"]

    ema_long = close > ema200[-1] and ema20[-1] > ema50[-1] and ema50[-1] > ema200[-1]
    ema_short = close < ema200[-1] and ema20[-1] < ema50[-1] and ema50[-1] < ema200[-1]

    rsi_long = 50 < rsi_values[-1] < 72
    rsi_short = 28 < rsi_values[-1] < 50

    adx_ok = adx_values[-1] >= cfg["adx_min"]
    pull_ok = abs(close - ema20[-1]) <= atr_values[-1] * cfg["pull_atr"]

    struct = detect_structure(rows, PIVOT_LEN)
    structure_long = struct == 1
    structure_short = struct == -1

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

    if (
        long_score >= cfg["min_score"]
        and ema_long
        and structure_long
        and rsi_long
        and adx_ok
        and pull_ok
        and bull_confirm
    ):
        side = "BUY"
        score = long_score

    elif (
        short_score >= cfg["min_score"]
        and ema_short
        and structure_short
        and rsi_short
        and adx_ok
        and pull_ok
        and bear_confirm
    ):
        side = "SELL"
        score = short_score

    result = {
        "symbol": symbol_name,
        "timeframe": timeframe,
        "status": side,
        "score": score,
        "grade": setup_grade(score),
        "price": close,
        "rsi": rsi_values[-1],
        "adx": adx_values[-1],
        "candle_type": candle_type,
        "trend": "LONG" if ema_long else "SHORT" if ema_short else "NEUTRALE",
        "structure": "BULLISH" if structure_long else "BEARISH" if structure_short else "NEUTRALE",
        "candle_time": datetime.fromtimestamp(last["t"], tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "candle_id": str(last["t"]),
        "risk_percent": cfg["risk_percent"],
        "checks": {
            "EMA trend": ema_long or ema_short,
            "BOS struttura": (ema_long and structure_long) or (ema_short and structure_short),
            "RSI": (ema_long and rsi_long) or (ema_short and rsi_short),
            "ADX": adx_ok,
            "Pullback": pull_ok,
            "Candela": (ema_long and bull_confirm) or (ema_short and bear_confirm),
        },
    }

    if side == "WAIT":
        return result

    entry = close

    if side == "BUY":
        sl = min(entry - atr_values[-1] * ATR_MULT, min([r["low"] for r in rows[-SWING_STOP_LEN:]]))
        risk = entry - sl
        tp1 = entry + risk
        tp2 = entry + risk * 2
        tp3 = entry + risk * 3
        tp4 = entry + risk * RR_FINAL
    else:
        sl = max(entry + atr_values[-1] * ATR_MULT, max([r["high"] for r in rows[-SWING_STOP_LEN:]]))
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
        "risk_money": ACCOUNT_SIZE * cfg["risk_percent"] / 100,
        "lot": estimate_lot(symbol_name, entry, sl, cfg["risk_percent"]),
    })

    return result


def telegram_alert(r):
    emoji = "🟢" if r["status"] == "BUY" else "🔴"

    if r["timeframe"] == "4H":
        profile_label = "PRINCIPALE"
    elif r["timeframe"] == "1H":
        profile_label = "TEST SECONDARIO"
    else:
        profile_label = "SOLO TEST RAPIDO"

    stars = "★★★★★" if r["score"] >= 97 else "★★★★☆" if r["score"] >= 94 else "★★★☆☆"

    checks = "\n".join([
        f"{'✅' if ok else '❌'} {name}"
        for name, ok in r["checks"].items()
    ])

    if r["symbol"] in ["XAUUSD", "US100", "BTCUSD", "ETHUSD"]:
        lot_label = "Unità indicative"
    else:
        lot_label = "Lotto indicativo"

    return (
        f"🚨 <b>TREND SNIPER AI v6 - TEST</b>\n\n"
        f"{emoji} <b>{r['status']} {r['symbol']}</b>\n"
        f"Timeframe: <b>{r['timeframe']}</b> - {profile_label}\n"
        f"{stars}\n"
        f"Qualità: <b>{r['grade']} - {r['score']}/100</b>\n"
        f"Candela chiusa: {r['candle_time']}\n\n"
        f"<b>Livelli operativi</b>\n"
        f"Entry: <b>{fmt(r['entry'])}</b>\n"
        f"Stop Loss: <b>{fmt(r['sl'])}</b>\n"
        f"TP1 1R: <b>{fmt(r['tp1'])}</b>\n"
        f"TP2 / Break-even: <b>{fmt(r['tp2'])}</b>\n"
        f"TP3 3R: <b>{fmt(r['tp3'])}</b>\n"
        f"TP4 1:{RR_FINAL}: <b>{fmt(r['tp4'])}</b>\n\n"
        f"<b>Gestione rischio demo</b>\n"
        f"Capitale demo: {ACCOUNT_SIZE} €\n"
        f"Rischio test: {r['risk_percent']}%\n"
        f"Perdita max indicativa: {r['risk_money']:.2f} €\n"
        f"{lot_label}: <b>{r['lot']}</b>\n\n"
        f"<b>Motivo</b>\n"
        f"Trend: {r['trend']}\n"
        f"Struttura: {r['structure']}\n"
        f"Candela: {r['candle_type']}\n"
        f"RSI: {r['rsi']:.2f}\n"
        f"ADX: {r['adx']:.2f}\n\n"
        f"{checks}\n\n"
        f"⚠️ Demo only. Apri TradingView e conferma prima di entrare."
    )


def test_message():
    return (
        "✅ <b>Trend Sniper AI v6 Multi-Timeframe TEST</b>\n\n"
        "Telegram collegato correttamente.\n"
        "GitHub Actions → Telegram funziona.\n\n"
        "Timeframe attivi: 4H, 1H, 15M, 5M"
    )


def main():
    if TEST_MODE:
        send_telegram(test_message())
        return

    state = load_state()
    alerts = 0
    logs = []

    for timeframe, cfg in PROFILES.items():
        if not cfg["enabled"]:
            continue

        logs.append(f"===== TIMEFRAME {timeframe} =====")

        for symbol_name, yahoo_symbol in WATCHLIST.items():
            try:
                result = analyze_symbol(symbol_name, yahoo_symbol, timeframe, cfg)

                logs.append(
                    f"{timeframe} | {symbol_name}: {result['status']} | "
                    f"Score {result['score']} | Grade {result['grade']} | "
                    f"Trend {result.get('trend', '-')}"
                )

                if result["status"] in ["BUY", "SELL"]:
                    key = (
                        f"{result['timeframe']}_"
                        f"{result['symbol']}_"
                        f"{result['status']}_"
                        f"{result['candle_id']}"
                    )

                    if state.get(key):
                        logs.append(f"{timeframe} | {symbol_name}: alert già inviato")
                        continue

                    send_telegram(telegram_alert(result))
                    state[key] = datetime.now(timezone.utc).isoformat()
                    alerts += 1

            except Exception as e:
                logs.append(f"{timeframe} | {symbol_name}: ERRORE {e}")

    if len(state) > 500:
        keys = list(state.keys())[-250:]
        state = {k: state[k] for k in keys}

    save_state(state)
    print("\n".join(logs))
    print(f"Alert inviati: {alerts}")


if __name__ == "__main__":
    main()
