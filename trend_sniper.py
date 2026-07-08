# Trend Sniper AI - Multi-Timeframe TEST
# GitHub Actions + Telegram
# Timeframe: 4H, 1H, 15M, 5M
# Uso demo/didattico. Non è consulenza finanziaria.

import os, json, time, urllib.request, urllib.parse
from pathlib import Path
from datetime import datetime, timezone

STATE_FILE = Path("state.json")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

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

PROFILES = {
    "4H":  {"interval": "1h",  "period": "60d", "seconds": 14400, "min_score": 86, "pull_atr": 0.60, "adx_min": 20, "risk": 1.00},
    "1H":  {"interval": "1h",  "period": "60d", "seconds": 3600,  "min_score": 90, "pull_atr": 0.55, "adx_min": 22, "risk": 0.50},
    "15M": {"interval": "15m", "period": "30d", "seconds": 900,   "min_score": 94, "pull_atr": 0.45, "adx_min": 25, "risk": 0.25},
    "5M":  {"interval": "5m",  "period": "7d",  "seconds": 300,   "min_score": 97, "pull_atr": 0.35, "adx_min": 28, "risk": 0.10},
}

def load_state():
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8")) if STATE_FILE.exists() else {}
    except Exception:
        return {}

def save_state(state):
    STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")

def http_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=25) as r:
        return json.loads(r.read().decode("utf-8"))

def send_telegram(text):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("ERRORE: token/chat id mancanti")
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
        print(r.read().decode("utf-8"))
    return True

def yahoo(symbol, period, interval):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(symbol)}?range={period}&interval={interval}"
    data = http_json(url)["chart"]["result"][0]
    ts = data["timestamp"]
    q = data["indicators"]["quote"][0]
    rows = []
    for i, t in enumerate(ts):
        o, h, l, c = q["open"][i], q["high"][i], q["low"][i], q["close"][i]
        v = q.get("volume", [0]*len(ts))[i] or 0
        if None in [o, h, l, c]:
            continue
        rows.append({"t": int(t), "open": float(o), "high": float(h), "low": float(l), "close": float(c), "volume": float(v)})
    return rows

def resample(rows, seconds):
    if seconds in (300, 900, 3600):
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
    out = [buckets[k] for k in sorted(buckets)]
    now = int(time.time())
    if out and now < out[-1]["t"] + seconds:
        out = out[:-1]
    return out

def ema(vals, n):
    a = 2 / (n + 1)
    out = [vals[0]]
    for v in vals[1:]:
        out.append(v*a + out[-1]*(1-a))
    return out

def rsi(vals, n=14):
    gains, losses = [0], [0]
    for i in range(1, len(vals)):
        d = vals[i] - vals[i-1]
        gains.append(max(d, 0)); losses.append(max(-d, 0))
    ag, al = ema(gains, n), ema(losses, n)
    return [100 if l == 0 else 100 - (100/(1+g/l)) for g, l in zip(ag, al)]

def atr(rows, n=14):
    tr = []
    for i, r in enumerate(rows):
        if i == 0:
            tr.append(r["high"] - r["low"])
        else:
            pc = rows[i-1]["close"]
            tr.append(max(r["high"]-r["low"], abs(r["high"]-pc), abs(r["low"]-pc)))
    return ema(tr, n)

def adx(rows, n=14):
    plus, minus, tr = [0], [0], [rows[0]["high"]-rows[0]["low"]]
    for i in range(1, len(rows)):
        up = rows[i]["high"] - rows[i-1]["high"]
        down = rows[i-1]["low"] - rows[i]["low"]
        plus.append(up if up > down and up > 0 else 0)
        minus.append(down if down > up and down > 0 else 0)
        tr.append(max(rows[i]["high"]-rows[i]["low"], abs(rows[i]["high"]-rows[i-1]["close"]), abs(rows[i]["low"]-rows[i-1]["close"])))
    atrs, ps, ms = ema(tr, n), ema(plus, n), ema(minus, n)
    dx = []
    for a, p, m in zip(atrs, ps, ms):
        if a == 0 or p+m == 0:
            dx.append(0)
        else:
            pdi, mdi = 100*p/a, 100*m/a
            dx.append(100*abs(pdi-mdi)/(pdi+mdi))
    return ema(dx, n)

def structure(rows, p=6):
    s, lh, ll = 0, None, None
    for i in range(p, len(rows)-p):
        if rows[i]["high"] == max(x["high"] for x in rows[i-p:i+p+1]):
            lh = rows[i]["high"]
        if rows[i]["low"] == min(x["low"] for x in rows[i-p:i+p+1]):
            ll = rows[i]["low"]
        if lh is not None and rows[i]["close"] > lh:
            s = 1
        if ll is not None and rows[i]["close"] < ll:
            s = -1
    return s

def candle(rows):
    last, prev = rows[-1], rows[-2]
    body = abs(last["close"] - last["open"])
    upper = last["high"] - max(last["open"], last["close"])
    lower = min(last["open"], last["close"]) - last["low"]
    bull_engulf = last["close"] > last["open"] and prev["close"] < prev["open"] and last["close"] >= prev["open"] and last["open"] <= prev["close"]
    bear_engulf = last["close"] < last["open"] and prev["close"] > prev["open"] and last["close"] <= prev["open"] and last["open"] >= prev["close"]
    hammer = lower > body*2 and upper <= body*1.25 and last["close"] > last["open"]
    shooting = upper > body*2 and lower <= body*1.25 and last["close"] < last["open"]
    bull = last["close"] > last["open"] and (bull_engulf or hammer or last["close"] > prev["high"])
    bear = last["close"] < last["open"] and (bear_engulf or shooting or last["close"] < prev["low"])
    typ = "Bullish Engulfing" if bull_engulf else "Bearish Engulfing" if bear_engulf else "Hammer" if hammer else "Shooting Star" if shooting else "Breakout candela" if last["close"] > prev["high"] else "Breakdown candela" if last["close"] < prev["low"] else "Nessuna"
    return bull, bear, typ

def grade(score):
    return "A+" if score >= 97 else "A" if score >= 94 else "B+" if score >= 90 else "B" if score >= 86 else "C"

def fmt(x):
    return f"{x:.2f}" if abs(x) >= 100 else f"{x:.3f}" if abs(x) >= 10 else f"{x:.5f}"

def lot(symbol, entry, sl, risk_pct):
    risk_money = ACCOUNT_SIZE * risk_pct / 100
    dist = abs(entry-sl)
    if dist <= 0:
        return 0
    if "JPY" in symbol:
        pip = 0.01
    elif symbol == "XAUUSD":
        pip = 0.10
    elif symbol in ["US100", "BTCUSD", "ETHUSD"]:
        return round(risk_money/dist, 3)
    else:
        pip = 0.0001
    pips = dist/pip
    return round(risk_money/(pips*10), 2) if pips > 0 else 0

def analyze(sym_name, yahoo_symbol, tf, cfg):
    rows = resample(yahoo(yahoo_symbol, cfg["period"], cfg["interval"]), cfg["seconds"])
    if len(rows) < 220:
        return {"symbol": sym_name, "timeframe": tf, "status": "NO DATA", "score": 0, "grade": "N/A"}
    closes = [r["close"] for r in rows]
    e20, e50, e200 = ema(closes,20), ema(closes,50), ema(closes,200)
    rv, av, xv = rsi(closes,14), atr(rows,14), adx(rows,14)
    last = rows[-1]; close = last["close"]
    ema_long = close > e200[-1] and e20[-1] > e50[-1] and e50[-1] > e200[-1]
    ema_short = close < e200[-1] and e20[-1] < e50[-1] and e50[-1] < e200[-1]
    rsi_long = 50 < rv[-1] < 72
    rsi_short = 28 < rv[-1] < 50
    adx_ok = xv[-1] >= cfg["adx_min"]
    pull_ok = abs(close-e20[-1]) <= av[-1]*cfg["pull_atr"]
    st = structure(rows, 6)
    st_long, st_short = st == 1, st == -1
    bull, bear, ctype = candle(rows)
    long_score = (30 if ema_long else 0)+(15 if st_long else 0)+(15 if rsi_long else 0)+(10 if adx_ok else 0)+(15 if pull_ok else 0)+(10 if bull else 0)+5
    short_score = (30 if ema_short else 0)+(15 if st_short else 0)+(15 if rsi_short else 0)+(10 if adx_ok else 0)+(15 if pull_ok else 0)+(10 if bear else 0)+5
    side, score = "WAIT", max(long_score, short_score)
    if long_score >= cfg["min_score"] and ema_long and st_long and rsi_long and adx_ok and pull_ok and bull:
        side, score = "BUY", long_score
    elif short_score >= cfg["min_score"] and ema_short and st_short and rsi_short and adx_ok and pull_ok and bear:
        side, score = "SELL", short_score
    result = {
        "symbol": sym_name, "timeframe": tf, "status": side, "score": score, "grade": grade(score),
        "price": close, "rsi": rv[-1], "adx": xv[-1], "candle_type": ctype,
        "trend": "LONG" if ema_long else "SHORT" if ema_short else "NEUTRALE",
        "structure": "BULLISH" if st_long else "BEARISH" if st_short else "NEUTRALE",
        "candle_time": datetime.fromtimestamp(last["t"], tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "candle_id": str(last["t"]), "risk_percent": cfg["risk"],
        "checks": {"EMA trend": ema_long or ema_short, "BOS struttura": (ema_long and st_long) or (ema_short and st_short), "RSI": (ema_long and rsi_long) or (ema_short and rsi_short), "ADX": adx_ok, "Pullback": pull_ok, "Candela": (ema_long and bull) or (ema_short and bear)}
    }
    if side == "WAIT":
        return result
    entry = close
    if side == "BUY":
        sl = min(entry-av[-1]*1.5, min(r["low"] for r in rows[-14:]))
        risk = entry - sl
        tp1, tp2, tp3, tp4 = entry+risk, entry+risk*2, entry+risk*3, entry+risk*RR_FINAL
    else:
        sl = max(entry+av[-1]*1.5, max(r["high"] for r in rows[-14:]))
        risk = sl - entry
        tp1, tp2, tp3, tp4 = entry-risk, entry-risk*2, entry-risk*3, entry-risk*RR_FINAL
    result.update({"entry": entry, "sl": sl, "tp1": tp1, "tp2": tp2, "tp3": tp3, "tp4": tp4, "risk_money": ACCOUNT_SIZE*cfg["risk"]/100, "lot": lot(sym_name, entry, sl, cfg["risk"])})
    return result

def alert(r):
    emoji = "🟢" if r["status"] == "BUY" else "🔴"
    label = "PRINCIPALE" if r["timeframe"] == "4H" else "TEST SECONDARIO" if r["timeframe"] == "1H" else "SOLO TEST RAPIDO"
    checks = "\n".join([f"{'✅' if ok else '❌'} {k}" for k, ok in r["checks"].items()])
    return (
        f"🚨 <b>TREND SNIPER AI - TEST</b>\n\n"
        f"{emoji} <b>{r['status']} {r['symbol']}</b>\n"
        f"Timeframe: <b>{r['timeframe']}</b> - {label}\n"
        f"Qualità: <b>{r['grade']} - {r['score']}/100</b>\n"
        f"Candela chiusa: {r['candle_time']}\n\n"
        f"<b>Livelli</b>\nEntry: <b>{fmt(r['entry'])}</b>\nSL: <b>{fmt(r['sl'])}</b>\nTP1: <b>{fmt(r['tp1'])}</b>\nTP2/BE: <b>{fmt(r['tp2'])}</b>\nTP3: <b>{fmt(r['tp3'])}</b>\nTP4 1:{RR_FINAL}: <b>{fmt(r['tp4'])}</b>\n\n"
        f"<b>Rischio demo</b>\nCapitale: {ACCOUNT_SIZE} €\nRischio: {r['risk_percent']}%\nPerdita max: {r['risk_money']:.2f} €\nLotto/unità indicativo: <b>{r['lot']}</b>\n\n"
        f"<b>Motivo</b>\nTrend: {r['trend']}\nStruttura: {r['structure']}\nCandela: {r['candle_type']}\nRSI: {r['rsi']:.2f}\nADX: {r['adx']:.2f}\n\n{checks}\n\n"
        f"⚠️ Demo only. Conferma su TradingView prima di entrare."
    )

def test_message():
    return "✅ <b>Trend Sniper AI Multi-Timeframe TEST</b>\n\nTelegram collegato.\nTimeframe attivi: 4H, 1H, 15M, 5M."

def main():
    if TEST_MODE:
        send_telegram(test_message()); return
    state = load_state()
    sent = 0
    logs = []
    for tf, cfg in PROFILES.items():
        logs.append(f"--- TIMEFRAME {tf} ---")
        for name, ysym in WATCHLIST.items():
            try:
                r = analyze(name, ysym, tf, cfg)
                logs.append(f"{tf} {name}: {r['status']} | Score {r['score']} | Grade {r['grade']} | Trend {r.get('trend','-')}")
                if r["status"] in ["BUY", "SELL"]:
                    key = f"{tf}_{r['symbol']}_{r['status']}_{r['candle_id']}"
                    if state.get(key):
                        logs.append(f"{tf} {name}: alert già inviato")
                        continue
                    send_telegram(alert(r))
                    state[key] = datetime.now(timezone.utc).isoformat()
                    sent += 1
            except Exception as e:
                logs.append(f"{tf} {name}: ERRORE {e}")
    if len(state) > 500:
        keys = list(state.keys())[-250:]
        state = {k: state[k] for k in keys}
    save_state(state)
    print("\n".join(logs))
    print(f"Alert inviati: {sent}")

if __name__ == "__main__":
    main()
