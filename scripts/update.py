#!/usr/bin/env python3
"""Gold Sniper v3 - 双时间框架策略：4h定方向 + 1h找入场"""
import json, urllib.request, datetime, math

def fetch(url):
    req = urllib.request.Request(url)
    return json.load(urllib.request.urlopen(req, timeout=15))

def calc_rsi(closes, period=14):
    gains = [max(0, closes[i] - closes[i-1]) for i in range(1, len(closes))]
    losses = [abs(min(0, closes[i] - closes[i-1])) for i in range(1, len(closes))]
    if len(gains) < period:
        return 50
    ag = sum(gains[-period:]) / period
    al = sum(losses[-period:]) / period
    if al == 0: return 100
    return 100 - (100 / (1 + ag / al))

def calc_ema(data, period):
    k = 2 / (period + 1)
    val = data[0]
    for v in data[1:]:
        val = v * k + val * (1 - k)
    return val

def calc_bb(closes, period=20):
    d = closes[-period:]
    mean = sum(d) / period
    std = math.sqrt(sum((x - mean)**2 for x in d) / period)
    return mean, mean + 2*std, mean - 2*std, std

def calc_atr(klines, period=14):
    trs = []
    for i in range(1, len(klines)):
        h, l, pc = float(klines[i][2]), float(klines[i][3]), float(klines[i-1][4])
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    return sum(trs[-period:]) / period if len(trs) >= period else sum(trs) / max(len(trs),1)

# ===== 获取数据 =====
tk = fetch('https://api.bitget.com/api/v2/spot/market/tickers?symbol=PAXGUSDT')['data'][0]
price = float(tk['lastPr'])

k4h = fetch('https://api.bitget.com/api/v2/spot/market/candles?symbol=PAXGUSDT&granularity=4h&limit=50')['data']
k4h.reverse()
closes_4h = [float(k[4]) for k in k4h]

k1h = fetch('https://api.bitget.com/api/v2/spot/market/candles?symbol=PAXGUSDT&granularity=1h&limit=50')['data']
k1h.reverse()
closes_1h = [float(k[4]) for k in k1h]

# ===== 4H级别分析（判断大趋势+横盘） =====
rsi_4h = calc_rsi(closes_4h, 14)
ema7_4h = calc_ema(closes_4h, 7)
ema25_4h = calc_ema(closes_4h, 25)
bb_mid_4h, bb_up_4h, bb_low_4h, bb_std_4h = calc_bb(closes_4h, 20)
atr_4h = calc_atr(k4h, 14)

# 24h涨跌幅（6根4h）
h24_change = (price - closes_4h[-7]) / closes_4h[-7] * 100 if len(closes_4h) >= 7 else 0
# 12h涨跌幅（3根4h）
h12_change = (price - closes_4h[-4]) / closes_4h[-4] * 100 if len(closes_4h) >= 4 else 0

# 大涨/大跌判断
is_surge_4h = h24_change > 2.0  # 24h涨超2%
is_dump_4h = h24_change < -2.0  # 24h跌超2%

# 横盘震荡判断（4h级别，最近4根=16h）
recent_4h = k4h[-4:]
recent_highs = [float(k[2]) for k in recent_4h]
recent_lows = [float(k[3]) for k in recent_4h]
range_16h = (max(recent_highs) - min(recent_lows)) / min(recent_lows) * 100

# 每根4h的振幅
candle_ranges = [(float(k[2]) - float(k[3])) / float(k[4]) * 100 for k in recent_4h]
range_shrinking = len(candle_ranges) >= 3 and candle_ranges[-1] < candle_ranges[-2] < candle_ranges[-3]

# ATR收窄：当前ATR < 前14根ATR均值的80%
atr_prev = calc_atr(k4h[:-14], 14) if len(k4h) > 28 else atr_4h * 1.2
atr_narrowing = atr_4h < atr_prev * 0.8 if atr_prev > 0 else True

# RSI中性区
rsi_4h_neutral = 35 < rsi_4h < 65

# 价格在BB中轨附近（±1倍标准差）
price_near_bb_mid = abs(price - bb_mid_4h) < bb_std_4h

# 综合横盘判断：至少满足3个条件
osc_conditions = [
    range_16h < 3.0,           # 16h波幅<3%
    rsi_4h_neutral,             # RSI中性
    price_near_bb_mid,          # 价格在BB中轨附近
    range_shrinking or atr_narrowing  # 振幅收窄或ATR收窄
]
is_oscillating_4h = sum(osc_conditions) >= 3

# ===== 1H级别分析（找精确入场） =====
rsi_1h = calc_rsi(closes_1h, 14)
ema7_1h = calc_ema(closes_1h, 7)
ema25_1h = calc_ema(closes_1h, 25)
bb_mid_1h, bb_up_1h, bb_low_1h, bb_std_1h = calc_bb(closes_1h, 20)

# 1h K线形态（最近3根）
last3_1h = k1h[-3:]
# 看跌形态：上影线长 + 实体小
bearish_candle = False
for k in last3_1h:
    o, h, l, c = float(k[1]), float(k[2]), float(k[3]), float(k[4])
    body = abs(c - o)
    upper = h - max(o, c)
    if upper > body * 1.5 and body < (h - l) * 0.3:
        bearish_candle = True
# 看涨形态：下影线长 + 实体小
bullish_candle = False
for k in last3_1h:
    o, h, l, c = float(k[1]), float(k[2]), float(k[3]), float(k[4])
    body = abs(c - o)
    lower = min(o, c) - l
    if lower > body * 1.5 and body < (h - l) * 0.3:
        bullish_candle = True

# ===== 综合策略 =====
signal = 'waiting'
reasons = []

# 记录状态
reasons.append(f'24h:{h24_change:+.1f}%')
reasons.append(f'RSI(4h):{rsi_4h:.0f} RSI(1h):{rsi_1h:.0f}')
reasons.append(f'ATR:{atr_4h:.0f}')

if is_oscillating_4h:
    reasons.append(f'横盘确认({sum(osc_conditions)}/4)')
else:
    reasons.append(f'非横盘({sum(osc_conditions)}/4)')

# 策略1：大涨后横盘 + 1h确认 → 做空
if is_surge_4h and is_oscillating_4h:
    signal = 'short'
    reasons.insert(0, '🔊大涨后横盘→高位做空')
    reasons.append(f'止损:{price + atr_4h*1.5:.0f} 止盈:{price - atr_4h*2:.0f}')

# 策略2：大跌后横盘 + 1h确认 → 做多
elif is_dump_4h and is_oscillating_4h:
    signal = 'long'
    reasons.insert(0, '🔊大跌后横盘→低位做多')
    reasons.append(f'止损:{price - atr_4h*1.5:.0f} 止盈:{price + atr_4h*2:.0f}')

# 策略3：趋势策略（备用）
elif not is_oscillating_4h:
    trend_up = ema7_1h > ema25_1h
    rsi_extreme_low = rsi_1h < 30
    rsi_extreme_high = rsi_1h > 70
    
    if trend_up and rsi_extreme_low and price < bb_low_1h:
        signal = 'long'
        reasons.insert(0, '趋势做多')
    elif not trend_up and rsi_extreme_high and price > bb_up_1h:
        signal = 'short'
        reasons.insert(0, '趋势做空')

print(f'Price={price:.2f} RSI4h={rsi_4h:.1f} RSI1h={rsi_1h:.1f} ATR={atr_4h:.0f} Signal={signal}')
print(f'24h={h24_change:+.2f}% 16h_range={range_16h:.2f}% Osc={is_oscillating_4h}')

# ===== 输出数据 =====
data = {
    'ticker': {
        'lastPrice': str(price),
        'priceChange': str(round(float(tk.get('change24h', 0)) * price, 2)),
        'priceChangePercent': str(round(float(tk.get('change24h', 0)) * 100, 2)),
        'highPrice': float(tk['high24h']),
        'lowPrice': float(tk['low24h']),
        'volume': str(round(float(tk.get('baseVolume', 0)), 2))
    },
    'strategy': {
        'signal': signal,
        'price': price,
        'reason': ' | '.join(reasons),
        'indicators': {
            'rsi': round(rsi_1h, 1),
            'ema7': round(ema7_1h, 2),
            'ema25': round(ema25_1h, 2),
            'bbUpper': round(bb_up_1h, 2),
            'bbMiddle': round(bb_mid_1h, 2),
            'bbLower': round(bb_low_1h, 2),
            'volatility': round(float(k1h[-1][2]) - float(k1h[-1][3]), 2),
            'stable': is_oscillating_4h
        },
        # 4h级别指标（前端可选展示）
        'h4': {
            'rsi': round(rsi_4h, 1),
            'ema7': round(ema7_4h, 2),
            'ema25': round(ema25_4h, 2),
            'atr': round(atr_4h, 2),
            'h24_change': round(h24_change, 2),
            'oscillating': is_oscillating_4h,
            'osc_score': sum(osc_conditions),
            'stopLoss': round(price + atr_4h * 1.5, 2) if signal == 'short' else round(price - atr_4h * 1.5, 2) if signal == 'long' else 0,
            'takeProfit': round(price - atr_4h * 2, 2) if signal == 'short' else round(price + atr_4h * 2, 2) if signal == 'long' else 0
        }
    },
    'timestamp': int(datetime.datetime.now(datetime.timezone.utc).timestamp() * 1000),
    'source': 'github-actions-v3'
}

import os
out = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data', 'data.json')
with open(out, 'w') as fp:
    json.dump(data, fp, indent=2)
print(f'Written to {out}')
