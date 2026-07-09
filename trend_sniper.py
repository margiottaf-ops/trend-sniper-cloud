# Trend Sniper AI v8.1 SCHEDULED SCAN
# GitHub Actions + Telegram
# 5M ogni 5 minuti, 15M ogni 15 minuti, 1H ogni ora, 4H ogni 4 ore.
# Demo/testing only. Non è consulenza finanziaria.

import os, csv, json, time, urllib.request, urllib.parse
from pathlib import Path
from datetime import datetime, timezone

STATE_FILE = Path("state.json")
SIGNALS_FILE = Path("signals.csv")
LAST_SCAN_FILE = Path("last_scan.json")

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

TEST_MODE = False
HEARTBEAT_ENABLED = True

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

PROFILES = {
    "4H":  {"enabled": True, "source_interval": "1h",  "period": "60d", "seconds": 14400, "min_score": 86, "pull_atr": 0.60, "adx_min": 20, "risk": 1.00, "profile": "PRINCIPALE"},
    "1H":  {"enabled": True, "source_interval": "1h",  "period": "60d", "seconds": 3600,  "min_score": 90, "pull_atr": 0.55, "adx_min": 22, "risk": 0.50, "profile": "TEST SECONDARIO"},
    "15M": {"enabled": True, "source_interval": "15m", "period": "30d", "seconds": 900,   "min_score": 90, "pull_atr": 0.65, "adx_min": 20, "risk": 0.25, "profile": "SOLO TEST RAPIDO"},
    "5M":  {"enabled": True, "source_interval": "5m",  "period": "7d",  "seconds": 300,   "min_score": 92, "pull_atr": 0.70, "adx_min": 20, "risk": 0.10, "profile": "SOLO PRATICA"},
}

def load_json(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default
    except Exception:
        return default

def save_json(path, data):
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")

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
        print(r.read().decode("utf-8"))
    return True

def should_scan(tf, now):
    if tf == "5M":
        return now.minute % 5 == 0
    if tf == "15M":
        return now.minute % 15 == 0
    if tf == "1H":
        return now.minute == 0
    if tf == "4H":
        return now.minute == 0 and now.hour % 4 == 0
    return False

def active_timeframes(now):
    return [tf for tf, cfg in PROFILES.items() if cfg["enabled"] and should_scan(tf, now)]

def yahoo_download(symbol, period, interval):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(symbol)}?range={period}&interval={interval}"
    data = request_json(url)
    if not data.get("chart") or not data["chart"].get("result"):
        return []
    result = data["chart"]["result"][0]
    timestamps = result.get("timestamp", [])
    q = result["indicators"]["quote"][0]
    rows = []
    for i, ts in enumerate(timestamps):
        o, h, l, c = q["open"][i], q["high"][i], q["low"][i], q["close"][i]
        v = q.get("volume", [0] * len(timestamps))[i] or 0
        if o is None or h is None or l is None or c is None:
            continue
        rows.append({"t": int(ts), "open": float(o), "high": float(h), "low": float(l), "close": float(c), "volume": float(v)})
    return rows

def resample_rows(rows, seconds):
    if not rows:
        return []
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
            buckets[b] = {"t": b, "open": r["open"], "high": r["high"], "low": r["low"], "close": r["close"], "volume": r["volume"]}
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
    a = 2 / (length + 1)
    out = [values[0]]
    for v in values[1:]:
        out.append(v * a + out[-1] * (1 - a))
    return out

def rsi(values, length=14):
    gains, losses = [0], [0]
    for i in range(1, len(values)):
        d = values[i] - values[i - 1]
        gains.append(max(d, 0))
        losses.append(max(-d, 0))
    ag, al = ema(gains, length), ema(losses, length)
    return [100 if l == 0 else 100 - (100 / (1 + g / l)) for g, l in zip(ag, al)]

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
    atr_s, plus_s, minus_s = ema(tr, length), ema(plus_dm, length), ema(minus_dm, length)
    dx = []
    for a, p, m in zip(atr_s, plus_s, minus_s):
        if a == 0 or p + m == 0:
            dx.append(0)
        else:
            plus_di, minus_di = 100 * p / a, 100 * m / a
            dx.append(100 * abs(plus_di - minus_di) / (plus_di + minus_di))
    return ema(dx, length)

def detect_structure(rows, pivot_len=6):
    structure, last_high, last_low = 0, None, None
    for i in range(pivot_len, len(rows) - pivot_len):
        if rows[i]["high"] == max(x["high"] for x in rows[i - pivot_len:i + pivot_len + 1]):
            last_high = rows[i]["high"]
        if rows[i]["low"] == min(x["low"] for x in rows[i - pivot_len:i + pivot_len + 1]):
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
    ctype = "Bullish Engulfing" if bull_engulf else "Bearish Engulfing" if bear_engulf else "Hammer" if hammer else "Shooting Star" if shooting else "Breakout candela precedente" if last["close"] > prev["high"] else "Breakdown candela precedente" if last["close"] < prev["low"] else "Nessuna"
    return bull, bear, ctype

def setup_grade(score):
    return "A+" if score >= 97 else "A" if score >= 94 else "B+" if score >= 90 else "B" if score >= 86 else "C"

def fmt(x):
    return f"{x:.2f}" if abs(x) >= 100 else f"{x:.3f}" if abs(x) >= 10 else f"{x:.5f}"

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
    return round(risk_money / (pips * 10), 2) if pips > 0 else 0.0

def analyze_symbol(symbol_name, yahoo_symbol, timeframe, cfg):
    raw = yahoo_download(yahoo_symbol, cfg["period"], cfg["source_interval"])
    rows = resample_rows(raw, cfg["seconds"])
    if len(rows) < 220:
        return {"symbol": symbol_name, "timeframe": timeframe, "status": "NO DATA", "score": 0, "grade": "N/A", "note": f"Dati insufficienti: {len(rows)} barre"}
    closes = [r["close"] for r in rows]
    ema20, ema50, ema200 = ema(closes, 20), ema(closes, 50), ema(closes, 200)
    rsi_values, atr_values, adx_values = rsi(closes, 14), atr(rows, 14), adx(rows, 14)
    last, close = rows[-1], rows[-1]["close"]
    ema_long = close > ema200[-1] and ema20[-1] > ema50[-1] and ema50[-1] > ema200[-1]
    ema_short = close < ema200[-1] and ema20[-1] < ema50[-1] and ema50[-1] < ema200[-1]
    rsi_long = 50 < rsi_values[-1] < 72
    rsi_short = 28 < rsi_values[-1] < 50
    adx_ok = adx_values[-1] >= cfg["adx_min"]
    pull_ok = abs(close - ema20[-1]) <= atr_values[-1] * cfg["pull_atr"]
    struct = detect_structure(rows, 6)
    structure_long, structure_short = struct == 1, struct == -1
    bull_confirm, bear_confirm, candle_type = candle_confirm(rows)
    long_score = (30 if ema_long else 0) + (15 if structure_long else 0) + (15 if rsi_long else 0) + (10 if adx_ok else 0) + (15 if pull_ok else 0) + (10 if bull_confirm else 0) + 5
    short_score = (30 if ema_short else 0) + (15 if structure_short else 0) + (15 if rsi_short else 0) + (10 if adx_ok else 0) + (15 if pull_ok else 0) + (10 if bear_confirm else 0) + 5
    side, score = "WAIT", max(long_score, short_score)
    if long_score >= cfg["min_score"] and ema_long and structure_long and rsi_long and adx_ok and pull_ok and bull_confirm:
        side, score = "BUY", long_score
    elif short_score >= cfg["min_score"] and ema_short and structure_short and rsi_short and adx_ok and pull_ok and bear_confirm:
        side, score = "SELL", short_score
    result = {
        "symbol": symbol_name, "timeframe": timeframe, "profile": cfg["profile"], "status": side,
        "score": score, "grade": setup_grade(score), "price": close, "rsi": rsi_values[-1], "adx": adx_values[-1],
        "candle_type": candle_type, "trend": "LONG" if ema_long else "SHORT" if ema_short else "NEUTRALE",
        "structure": "BULLISH" if structure_long else "BEARISH" if structure_short else "NEUTRALE",
        "candle_time": datetime.fromtimestamp(last["t"], tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "candle_id": str(last["t"]), "risk_percent": cfg["risk"],
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
        sl = min(entry - atr_values[-1] * 1.5, min(r["low"] for r in rows[-14:]))
        risk = entry - sl
        tp = entry + risk * RR_FINAL
    else:
        sl = max(entry + atr_values[-1] * 1.5, max(r["high"] for r in rows[-14:]))
        risk = sl - entry
        tp = entry - risk * RR_FINAL
    result.update({
        "entry": entry, "sl": sl, "tp": tp, "rr": RR_FINAL,
        "risk_money": ACCOUNT_SIZE * cfg["risk"] / 100,
        "lot": estimate_lot(symbol_name, entry, sl, cfg["risk"]),
    })
    return result

def telegram_alert(r):
    emoji = "🟢" if r["status"] == "BUY" else "🔴"
    stars = "★★★★★" if r["score"] >= 97 else "★★★★☆" if r["score"] >= 94 else "★★★☆☆"
    checks = "\n".join(f"{'✅' if ok else '❌'} {name}" for name, ok in r["checks"].items())
    lot_label = "Unità indicative" if r["symbol"] in ["XAUUSD", "US100", "BTCUSD", "ETHUSD"] else "Lotto indicativo"
    return (
        f"🚨 <b>TREND SNIPER AI v8.1</b>\n\n"
        f"{emoji} <b>{r['status']} {r['symbol']}</b>\n"
        f"Timeframe: <b>{r['timeframe']}</b> - {r['profile']}\n"
        f"{stars}\n"
        f"Qualità: <b>{r['grade']} - {r['score']}/100</b>\n"
        f"Candela chiusa: {r['candle_time']}\n\n"
        f"<b>Livelli operativi</b>\n"
        f"Entry: <b>{fmt(r['entry'])}</b>\n"
        f"Stop Loss: <b>{fmt(r['sl'])}</b>\n"
        f"Take Profit 1:{RR_FINAL}: <b>{fmt(r['tp'])}</b>\n\n"
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
        f"⚠️ Demo only. Conferma su TradingView prima di entrare."
    )

def save_signal_csv(r):
    exists = SIGNALS_FILE.exists()
    fields = ["created_at_utc","symbol","timeframe","profile","side","score","grade","entry","sl","tp","rr","risk_percent","risk_money","lot","trend","structure","candle_type","rsi","adx","candle_time"]
    with SIGNALS_FILE.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        if not exists:
            writer.writeheader()
        writer.writerow({
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "symbol": r["symbol"], "timeframe": r["timeframe"], "profile": r["profile"],
            "side": r["status"], "score": r["score"], "grade": r["grade"],
            "entry": r["entry"], "sl": r["sl"], "tp": r["tp"], "rr": r["rr"],
            "risk_percent": r["risk_percent"], "risk_money": r["risk_money"],
            "lot": r["lot"], "trend": r["trend"], "structure": r["structure"],
            "candle_type": r["candle_type"], "rsi": r["rsi"], "adx": r["adx"],
            "candle_time": r["candle_time"],
        })

def test_message():
    return "✅ <b>Trend Sniper AI v8.1</b>\n\nTelegram collegato.\nScanner allineato alle chiusure candela.\n5M/15M/1H/4H attivi.\nlast_scan.json attivo."

def heartbeat_message(last_scan):
    active = ", ".join(last_scan.get("active_timeframes", [])) or "nessuno"
    return (
        "🟢 <b>Trend Sniper AI online</b>\n\n"
        f"Ultimo scan UTC: {last_scan.get('scan_time_utc')}\n"
        f"Timeframe analizzati: {active}\n"
        f"Alert inviati: {last_scan.get('alerts_sent', 0)}\n"
        f"Mercati controllati: {last_scan.get('markets_checked', 0)}"
    )

def main():
    now_utc = datetime.now(timezone.utc)
    if TEST_MODE:
        send_telegram(test_message())
        return
    state = load_json(STATE_FILE, {})
    alerts, markets_checked = 0, 0
    logs = [f"SCAN UTC: {now_utc.strftime('%Y-%m-%d %H:%M:%S')}"]
    active = active_timeframes(now_utc)
    logs.append(f"TIMEFRAME ATTIVI ORA: {', '.join(active) if active else 'nessuno'}")
    for timeframe in active:
        cfg = PROFILES[timeframe]
        logs.append(f"===== TIMEFRAME {timeframe} | {cfg['profile']} =====")
        for symbol_name, yahoo_symbol in WATCHLIST.items():
            markets_checked += 1
            try:
                r = analyze_symbol(symbol_name, yahoo_symbol, timeframe, cfg)
                check_text = ""
                if "checks" in r:
                    check_text = " | " + " ".join(f"{k}:{'OK' if v else 'NO'}" for k, v in r["checks"].items())
                logs.append(f"{timeframe} | {symbol_name}: {r['status']} | Score {r['score']} | Grade {r['grade']} | Trend {r.get('trend', '-')}{check_text}")
                if r["status"] in ["BUY", "SELL"]:
                    key = f"{r['timeframe']}_{r['symbol']}_{r['status']}_{r['candle_id']}"
                    if state.get(key):
                        logs.append(f"{timeframe} | {symbol_name}: alert già inviato")
                        continue
                    send_telegram(telegram_alert(r))
                    save_signal_csv(r)
                    state[key] = datetime.now(timezone.utc).isoformat()
                    alerts += 1
            except Exception as e:
                logs.append(f"{timeframe} | {symbol_name}: ERRORE {e}")
    if len(state) > 500:
        keys = list(state.keys())[-250:]
        state = {k: state[k] for k in keys}
    save_json(STATE_FILE, state)
    last_scan = {
        "scan_time_utc": now_utc.strftime("%Y-%m-%d %H:%M:%S"),
        "active_timeframes": active,
        "alerts_sent": alerts,
        "markets_checked": markets_checked,
        "heartbeat_enabled": HEARTBEAT_ENABLED,
    }
    save_json(LAST_SCAN_FILE, last_scan)
    if HEARTBEAT_ENABLED and now_utc.minute == 0:
        send_telegram(heartbeat_message(last_scan))
    print("\n".join(logs))
    print(f"Alert inviati: {alerts}")
    print(f"Ultimo scan salvato in: {LAST_SCAN_FILE}")
    print("File segnali:", SIGNALS_FILE if SIGNALS_FILE.exists() else "nessun segnale ancora")

if __name__ == "__main__":
    main()
