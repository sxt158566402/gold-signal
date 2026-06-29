#!/usr/bin/env python3
import json, urllib.request, datetime, os, sys, base64, math

token = os.environ.get('GH_TOKEN', '')
if not token:
    print('ERROR: No GH_TOKEN')
    sys.exit(1)

print(f'Token OK')

# Fetch ticker
try:
    req = urllib.request.Request('https://api.binance.com/api/v3/ticker/24hr?symbol=PAXGUSDT')
    ticker = json.load(urllib.request.urlopen(req, timeout=15))
    print(f'Ticker: {ticker["lastPrice"]}')
except Exception as e:
    print('TICKER FAIL:', e)
    sys.exit(1)

# Fetch klines
try:
    req = urllib.request.Request('https://api.binance.com/api/v3/klines?symbol=PAXGUSDT&interval=5m&limit=50')
    klines = json.load(urllib.request.urlopen(req, timeout=15))
except Exception as e:
    print('KLINES FAIL:', e)
    sys.exit(1)

closes = [float(k[4]) for k in klines]

# RSI
gains = 0.0
losses = 0.0
for i in range(len(closes) - 14, len(closes)):
    diff = closes[i] - closes[i - 1]
    if diff > 0:
        gains += diff
    else:
        losses -= diff
rsi = 100.0 - (100.0 / (1.0 + gains / losses)) if losses > 0 else 50.0

# EMA7
ema7 = closes[-1]
for c in closes[-7:]:
    ema7 = c * (2.0/8.0) + ema7 * (6.0/8.0)

# EMA25
ema25 = closes[-1]
for c in closes[-25:]:
    ema25 = c * (2.0/26.0) + ema25 * (24.0/26.0)

# Bollinger Bands
sma20 = sum(closes[-20:]) / 20.0
std20 = math.sqrt(sum((c - sma20) ** 2 for c in closes[-20:]) / 20.0)
bb_upper = sma20 + 2.0 * std20
bb_lower = sma20 - 2.0 * std20

# 5min move
lookback = min(5, len(closes) - 1)
change_pct = (closes[-1] - closes[-lookback - 1]) / closes[-lookback - 1] * 100.0
move_type = None
if change_pct > 0.15:
    move_type = 'big_up'
elif change_pct < -0.15:
    move_type = 'big_down'

stabilized = False
if move_type:
    recent = closes[-3:]
    vol = (max(recent) - min(recent)) / sum(recent) * 3.0 * 100.0
    stabilized = vol < 0.5

signal = 'waiting'
reason = 'monitoring'
p = float(ticker['lastPrice'])

if move_type == 'big_up' and (stabilized or rsi > 55):
    signal, reason = 'short', '5min up ' + str(round(change_pct, 2)) + '% RSI=' + str(round(rsi, 1))
elif move_type == 'big_down' and (stabilized or rsi < 45):
    signal, reason = 'long', '5min down ' + str(round(change_pct, 2)) + '% RSI=' + str(round(rsi, 1))
elif rsi > 75:
    signal, reason = 'short', 'RSI overbought ' + str(round(rsi, 1))
elif rsi < 25:
    signal, reason = 'long', 'RSI oversold ' + str(round(rsi, 1))

now = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8)))
if now.weekday() == 4 and 20 <= now.hour < 24:
    signal, reason = 'warning', 'Black Friday'

print(f'RSI={round(rsi,2)} EMA7={round(ema7,2)} EMA25={round(ema25,2)} Signal={signal}')

data = {
    'ticker': ticker,
    'klines': klines,
    'strategy': {
        'signal': signal,
        'price': p,
        'reason': reason,
        'indicators': {
            'rsi': round(rsi, 2),
            'ema7': round(ema7, 2),
            'ema25': round(ema25, 2),
            'bbUpper': round(bb_upper, 2),
            'bbMiddle': round(sma20, 2),
            'bbLower': round(bb_lower, 2)
        },
        'bigMove': move_type,
        'stabilized': stabilized
    },
    'timestamp': int(datetime.datetime.now(datetime.timezone.utc).timestamp() * 1000)
}

# Push to gh-pages via GitHub API
try:
    content = base64.b64encode(json.dumps(data).encode()).decode()
    req = urllib.request.Request(
        'https://api.github.com/repos/sxt158566402/gold-signal/contents/data/data.json?ref=gh-pages',
        headers={'Authorization': 'token ' + token, 'Accept': 'application/vnd.github.v3+json'}
    )
    resp = json.load(urllib.request.urlopen(req))
    sha = resp['sha']
    body = {
        'message': 'update data',
        'content': content,
        'sha': sha,
        'branch': 'gh-pages'
    }
    req2 = urllib.request.Request(
        'https://api.github.com/repos/sxt158566402/gold-signal/contents/data/data.json',
        data=json.dumps(body).encode(),
        headers={
            'Authorization': 'token ' + token,
            'Content-Type': 'application/json',
            'Accept': 'application/vnd.github.v3+json'
        },
        method='PUT'
    )
    r = json.load(urllib.request.urlopen(req2))
    if 'content' in r:
        print('SUCCESS')
    else:
        print('FAIL')
        sys.exit(1)
except Exception as e:
    print(f'PUSH ERROR: {e}')
    sys.exit(1)
