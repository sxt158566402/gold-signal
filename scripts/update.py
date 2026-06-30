#!/usr/bin/env python3
import json, urllib.request, datetime, math

# Fetch ticker from Bitget
try:
    req = urllib.request.Request('https://api.bitget.com/api/v2/spot/market/tickers?symbol=PAXGUSDT')
    resp = json.load(urllib.request.urlopen(req, timeout=15))
    tk = resp['data'][0]
    price = float(tk['lastPr'])
    print(f'Ticker: {price}')
except Exception as e:
    print(f'TICKER FAIL: {e}')
    exit(1)

# Fetch 1H klines from Bitget
try:
    req = urllib.request.Request('https://api.bitget.com/api/v2/spot/market/candles?symbol=PAXGUSDT&granularity=1h&limit=50')
    resp = json.load(urllib.request.urlopen(req, timeout=15))
    klines = resp['data']
    if len(klines) < 26:
        print(f'Not enough klines: {len(klines)}')
        exit(1)
    klines.reverse()
    print(f'Klines: {len(klines)}')
except Exception as e:
    print(f'KLINES FAIL: {e}')
    exit(1)

closes = [float(k[4]) for k in klines]

# RSI
start = max(1, len(closes) - 14)
gains_v = [max(0, closes[i] - closes[i-1]) for i in range(start, len(closes))]
losses_v = [abs(min(0, closes[i] - closes[i-1])) for i in range(start, len(closes))]
ag = sum(gains_v) / 14 if gains_v else 0
al = sum(losses_v) / 14 if losses_v else 0.001
rs = ag / al
rsi = 100 - (100 / (1 + rs))

# EMA
def ema(data, period):
    k = 2 / (period + 1)
    val = data[0]
    for v in data[1:]:
        val = v * k + val * (1 - k)
    return val

ema7 = ema(closes, 7)
ema25 = ema(closes, 25)

# Bollinger Bands
bb_data = closes[-20:]
bb_mean = sum(bb_data) / 20
bb_std = math.sqrt(sum((x - bb_mean) ** 2 for x in bb_data) / 20)

# Volatility & trend
prev_h = closes[-2]
prev2_h = closes[-3] if len(closes) > 2 else prev_h
volatility = abs(price - prev_h) / prev_h * 100
volatility_prev = abs(prev_h - prev2_h) / prev2_h * 100
is_stable = volatility < 0.12 and volatility_prev < 0.15
is_big_move = volatility > 0.3
trend_up = ema7 > ema25
trend_down = ema7 < ema25
cur_h_change = (price - prev_h) / prev_h * 100

# === 新策略：大涨/大跌后横盘震荡 → 反向操作 ===
h6_change = (price - closes[-7]) / closes[-7] * 100 if len(closes) >= 7 else 0
is_surge = h6_change > 1.5
is_dump = h6_change < -1.5
is_osc_high = is_stable and rsi >= 50
is_osc_low = is_stable and rsi <= 50

signal = 'waiting'
reasons = []
if trend_up: reasons.append('EMA金叉')
else: reasons.append('EMA死叉')
if rsi < 30: reasons.append(f'RSI超卖({rsi:.1f})')
elif rsi > 70: reasons.append(f'RSI超买({rsi:.1f})')
if is_stable: reasons.append('波动收敛(震荡中)')
elif is_big_move: reasons.append('大幅波动(观望)')
reasons.append(f'6h涨跌{h6_change:+.2f}%')

if is_surge and is_osc_high and not is_big_move:
    signal = 'short'
    reasons.insert(0, '大涨后横盘高位做空')
elif is_dump and is_osc_low and not is_big_move:
    signal = 'long'
    reasons.insert(0, '大跌后横盘低位做多')
elif is_big_move:
    signal = 'waiting'
    reasons.append('大行情企稳后再进')
else:
    bull = 0
    if trend_up: bull += 1
    if 25 < rsi < 40: bull += 1
    if price > ema25: bull += 1
    if price > bb_mean: bull += 1
    bear = 0
    if trend_down: bear += 1
    if 60 < rsi < 75: bear += 1
    if price < ema25: bear += 1
    if price < bb_mean: bear += 1
    if bull >= 3 and not is_big_move:
        signal = 'long'
        reasons.insert(0, '做多信号')
    elif bear >= 3 and not is_big_move:
        signal = 'short'
        reasons.insert(0, '做空信号')

print(f'RSI={rsi:.1f} EMA7={ema7:.1f} EMA25={ema25:.1f} Signal={signal} h6={h6_change:+.2f}%')

change24h = float(tk.get('change24h', 0))
change24hP = round(change24h * 100, 2)
change24hUSD = round(change24h * price, 2)
high24h = float(tk['high24h'])
low24h = float(tk['low24h'])

data = {
    'ticker': {
        'lastPrice': str(price),
        'priceChange': str(change24hUSD),
        'priceChangePercent': str(change24hP),
        'highPrice': high24h,
        'lowPrice': low24h,
        'volume': str(round(float(tk.get('baseVolume', 0)), 2))
    },
    'strategy': {
        'signal': signal,
        'price': price,
        'reason': ' | '.join(reasons),
        'indicators': {
            'rsi': round(rsi, 1),
            'ema7': round(ema7, 2),
            'ema25': round(ema25, 2),
            'bbUpper': round(bb_mean + 2 * bb_std, 2),
            'bbMiddle': round(bb_mean, 2),
            'bbLower': round(bb_mean - 2 * bb_std, 2),
            'volatility': round(volatility, 3),
            'stable': is_stable
        }
    },
    'timestamp': int(datetime.datetime.now(datetime.timezone.utc).timestamp() * 1000),
    'source': 'github-actions'
}

# 写入本地文件，Workflow用git push
import os
out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data', 'data.json')
with open(out_path, 'w') as fp:
    json.dump(data, fp, indent=2)
print(f'Written to {out_path}')
print(f'Done!')
