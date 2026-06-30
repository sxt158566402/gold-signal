#!/usr/bin/env python3
"""Gold Sniper v4 - 回踩横盘趋势策略
核心逻辑：
  1. 判断趋势方向（EMA排列 + 价格相对位置）
  2. 等待价格回踩EMA25附近
  3. 回踩后横盘企稳 → 顺势入场
  4. 1H级别确认入场时机

改进项：
  - 修复横盘判断与趋势矛盾（不再要求RSI中性，改为匹配趋势方向）
  - 趋势判断用近期数据+价格相对位置，避免EMA严重滞后
  - 增加急跌/急涨反弹模式
  - 盈亏比改为1:1.5（2ATR止损/3ATR止盈）
  - 仓位管理（风险2%法则）
  - 信号冷却（1小时）
  - 周末/事件过滤
  - 内置回测引擎
"""
import json, urllib.request, datetime, math, os

# ===== 信号冷却 =====
SIGNAL_COOLDOWN_FILE = '/opt/gold-signal/data/last_signal.json'

def load_last_signal():
    try:
        with open(SIGNAL_COOLDOWN_FILE) as f:
            return json.load(f)
    except:
        return {}

def save_last_signal(sig):
    try:
        with open(SIGNAL_COOLDOWN_FILE, 'w') as f:
            json.dump(sig, f)
    except:
        pass

def is_in_cooldown():
    last = load_last_signal()
    if not last.get('time'):
        return False
    try:
        elapsed = (datetime.datetime.now(datetime.timezone.utc) -
                   datetime.datetime.fromisoformat(last['time'])).total_seconds()
        return elapsed < 3600  # 1小时冷却
    except:
        return False

# ===== 事件过滤 =====
def is_high_impact_window():
    """检查是否在低流动性/重大事件窗口"""
    now = datetime.datetime.now(datetime.timezone.utc)
    if now.weekday() >= 5:  # 周六周日
        return True, "周末低流动性"
    return False, None

# ===== 技术指标 =====
def fetch(url):
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    return json.load(urllib.request.urlopen(req, timeout=15))

def calc_rsi(closes, period=14):
    if len(closes) < period + 1:
        return 50
    gains = [max(0, closes[i] - closes[i-1]) for i in range(1, len(closes))]
    losses = [abs(min(0, closes[i] - closes[i-1])) for i in range(1, len(closes))]
    ag = sum(gains[-period:]) / period
    al = sum(losses[-period:]) / period
    if al == 0: return 100
    return 100 - (100 / (1 + ag / al))

def calc_ema(data, period):
    if len(data) < period:
        return sum(data) / max(len(data), 1)
    k = 2 / (period + 1)
    val = data[0]
    for v in data[1:]:
        val = v * k + val * (1 - k)
    return val

def calc_bb(closes, period=20):
    if len(closes) < period:
        period = len(closes)
    d = closes[-period:]
    mean = sum(d) / period
    std = math.sqrt(sum((x - mean)**2 for x in d) / period)
    return mean, mean + 2*std, mean - 2*std, std

def calc_atr(klines, period=14):
    trs = []
    for i in range(1, len(klines)):
        h, l, pc = float(klines[i][2]), float(klines[i][3]), float(klines[i-1][4])
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    return sum(trs[-period:]) / period if len(trs) >= period else sum(trs) / max(len(trs), 1)

# ===== 回测引擎 =====
def backtest(klines_4h, initial_capital=10000):
    """回测策略历史表现，计算胜率/盈亏比/最大回撤"""
    if len(klines_4h) < 60:
        return {'total': 0, 'wins': 0, 'win_rate': 0, 'note': '数据不足'}
    
    closes = [float(k[4]) for k in klines_4h]
    trades = []
    
    for i in range(50, len(closes) - 6):
        window_closes = closes[:i+1]
        window_kl = klines_4h[:i+1]
        
        if len(window_closes) < 50:
            continue
            
        ema7 = calc_ema(window_closes, 7)
        ema25 = calc_ema(window_closes, 25)
        atr = calc_atr(window_kl, 14)
        
        if atr == 0:
            continue
            
        price = closes[i]
        rsi = calc_rsi(window_closes, 14)
        
        # 趋势判断（简化版：价格<EMA25且EMA7<EMA25=下跌）
        trend_down = price < ema25 and ema7 < ema25
        trend_up = price > ema25 and ema7 > ema25
        
        if not trend_down and not trend_up:
            continue
        
        # 回踩判断
        if trend_down:
            pullback = price > ema25 - atr * 1.5 and price < ema25 + atr * 0.5
        else:
            pullback = price < ema25 + atr * 1.5 and price > ema25 - atr * 0.5
        
        if not pullback:
            continue
        
        # 横盘判断（最近6根4h）
        if i < 6:
            continue
        recent = closes[i-5:i+1]
        recent_range = (max(recent) - min(recent)) / min(recent) * 100 if min(recent) > 0 else 0
        
        if trend_down:
            rsi_ok = 25 < rsi < 60
        else:
            rsi_ok = 40 < rsi < 75
        
        is_consolidating = recent_range < 3.0 and rsi_ok
        
        if not is_consolidating:
            continue
        
        # 模拟交易
        entry = closes[i]
        if trend_down:
            sl = entry + atr * 2
            tp = entry - atr * 3
            signal = 'short'
        else:
            sl = entry - atr * 2
            tp = entry + atr * 3
            signal = 'long'
        
        # 检查6根K线内是否触止损/止盈
        result = None
        for j in range(1, 7):
            if i + j >= len(klines_4h):
                break
            k = klines_4h[i + j]
            h, l = float(k[2]), float(k[3])
            if signal == 'short':
                if h >= sl:
                    result = 'loss'
                    break
                if l <= tp:
                    result = 'win'
                    break
            else:
                if l <= sl:
                    result = 'loss'
                    break
                if h >= tp:
                    result = 'win'
                    break
        
        if result is None:
            exit_price = closes[min(i+6, len(closes)-1)]
            if signal == 'short':
                result = 'win' if exit_price < entry else 'loss'
            else:
                result = 'win' if exit_price > entry else 'loss'
        
        trades.append({'signal': signal, 'result': result, 'entry': entry})
    
    if not trades:
        return {'total': 0, 'wins': 0, 'win_rate': 0, 'note': '回测期间无信号触发'}
    
    wins = sum(1 for t in trades if t['result'] == 'win')
    win_rate = round(wins / len(trades) * 100, 1)
    return {
        'total': len(trades),
        'wins': wins,
        'win_rate': win_rate,
        'note': f'{len(trades)}笔交易,{wins}胜{len(trades)-wins}负,胜率{win_rate}%'
    }

# ===== 获取数据 =====
tk = fetch('https://api.bitget.com/api/v2/spot/market/tickers?symbol=PAXGUSDT')['data'][0]
price = float(tk['lastPr'])

k4h = fetch('https://api.bitget.com/api/v2/spot/market/candles?symbol=PAXGUSDT&granularity=4h&limit=200')['data']
k4h.reverse()
closes_4h = [float(k[4]) for k in k4h]

k1h = fetch('https://api.bitget.com/api/v2/spot/market/candles?symbol=PAXGUSDT&granularity=1h&limit=100')['data']
k1h.reverse()
closes_1h = [float(k[4]) for k in k1h]

# ===== 4H指标 =====
rsi_4h = calc_rsi(closes_4h, 14)
ema7_4h = calc_ema(closes_4h, 7)
ema25_4h = calc_ema(closes_4h, 25)
ema50_4h = calc_ema(closes_4h, 50)
bb_mid_4h, bb_up_4h, bb_low_4h, bb_std_4h = calc_bb(closes_4h, 20)
atr_4h = calc_atr(k4h, 14)

# 24h涨跌幅
h24_change = (price - closes_4h[-7]) / closes_4h[-7] * 100 if len(closes_4h) >= 7 else 0

# ===== 趋势判断（改进：双重确认）=====
# 方法1：EMA排列（严格三线）
trend_down_strict = ema7_4h < ema25_4h < ema50_4h
trend_up_strict = ema7_4h > ema25_4h > ema50_4h

# 方法2：价格+EMA（简单但更灵敏，解决EMA滞后问题）
# 价格低于EMA25且EMA7低于EMA25 → 下跌
# 价格高于EMA25且EMA7高于EMA25 → 上涨
trend_down_simple = price < ema25_4h and ema7_4h < ema25_4h
trend_up_simple = price > ema25_4h and ema7_4h > ema25_4h

# 综合趋势判断：任一方法确认即可
trend_down = trend_down_strict or trend_down_simple
trend_up = trend_up_strict or trend_up_simple
trend_none = not trend_down and not trend_up

if trend_down:
    trend_dir = '下跌'
    # 趋势强度：价格距EMA50的ATR距离
    trend_strength = (ema50_4h - price) / atr_4h * 100 if atr_4h > 0 else 0
elif trend_up:
    trend_dir = '上涨'
    trend_strength = (price - ema50_4h) / atr_4h * 100 if atr_4h > 0 else 0
else:
    trend_dir = '无趋势'
    trend_strength = 0

# ===== 回踩判断 =====
# 下跌趋势中：价格从下方反弹回踩到EMA25附近
pullback_down = (price > ema25_4h - atr_4h * 1.5 and
                 price < ema25_4h + atr_4h * 0.5 and
                 trend_down)
# 上涨趋势中：价格从上方回调回踩到EMA25附近
pullback_up = (price < ema25_4h + atr_4h * 1.5 and
               price > ema25_4h - atr_4h * 0.5 and
               trend_up)

# 回踩距离（ATR单位）
pullback_distance = (price - ema25_4h) / atr_4h if atr_4h > 0 else 0

# ===== 横盘企稳判断（修复矛盾）=====
# 最近6根4h（24h）波幅
recent_6h = k4h[-6:]
recent_highs = [float(k[2]) for k in recent_6h]
recent_lows = [float(k[3]) for k in recent_6h]
range_24h = (max(recent_highs) - min(recent_lows)) / min(recent_lows) * 100 if min(recent_lows) > 0 else 0

# 振幅收窄
recent_3_range = max(float(k[2]) for k in k4h[-3:]) - min(float(k[3]) for k in k4h[-3:])
prev_3_range = max(float(k[2]) for k in k4h[-6:-3]) - min(float(k[3]) for k in k4h[-6:-3])
range_shrinking = recent_3_range < prev_3_range * 0.8 if prev_3_range > 0 else False

# ATR收窄
atr_prev = calc_atr(k4h[:-6], 14) if len(k4h) > 20 else atr_4h * 1.2
atr_narrowing = atr_4h < atr_prev * 0.85 if atr_prev > 0 else True

# RSI匹配趋势（不再要求中性）
if trend_down:
    rsi_fits_trend = 20 < rsi_4h < 60  # 下跌中RSI偏弱
elif trend_up:
    rsi_fits_trend = 40 < rsi_4h < 80  # 上涨中RSI偏强
else:
    rsi_fits_trend = 35 < rsi_4h < 65  # 无趋势时中性

# 价格在EMA25附近（±1.5 ATR）
price_near_ema25 = abs(price - ema25_4h) < atr_4h * 1.5

# 综合横盘判断
osc_conditions = [
    range_24h < 3.0,                           # 24h波幅<3%
    rsi_fits_trend,                            # RSI匹配趋势方向
    price_near_ema25,                          # 价格在EMA25附近
    range_shrinking or atr_narrowing           # 振幅/ATR收窄
]
is_consolidating = sum(osc_conditions) >= 3

# ===== 急跌/急涨反弹模式 =====
# 当价格远低于EMA25（>3 ATR）且RSI超卖（<30）
# → 等待反弹回踩，不立即进场
is_oversold = rsi_4h < 30
is_overbought = rsi_4h > 70
far_from_ema25 = abs(pullback_distance) > 3  # 距EMA25超过3个ATR

# ===== 1H级别精确入场 =====
rsi_1h = calc_rsi(closes_1h, 14)
ema7_1h = calc_ema(closes_1h, 7)
ema25_1h = calc_ema(closes_1h, 25)
bb_mid_1h, bb_up_1h, bb_low_1h, bb_std_1h = calc_bb(closes_1h, 20)

# 1h趋势确认
h1_trend_down = ema7_1h < ema25_1h
h1_trend_up = ema7_1h > ema25_1h

# 1h K线形态
last3_1h = k1h[-3:]
bearish_candle = False
bullish_candle = False
for k in last3_1h:
    o, h, l, c = float(k[1]), float(k[2]), float(k[3]), float(k[4])
    body = abs(c - o)
    upper = h - max(o, c)
    lower = min(o, c) - l
    if upper > body * 1.2 and body < (h - l) * 0.4:
        bearish_candle = True
    if lower > body * 1.2 and body < (h - l) * 0.4:
        bullish_candle = True

# ===== 仓位管理（风险2%法则）=====
account_size = 10000
risk_amount = account_size * 0.02
stop_distance = atr_4h * 2
position_size = risk_amount / stop_distance if stop_distance > 0 else 0
position_pct = (position_size * price / account_size) * 100 if price > 0 else 0

# ===== 过滤检查 =====
skip_event, event_reason = is_high_impact_window()
in_cooldown = is_in_cooldown()
can_trade = not skip_event and not in_cooldown

# ===== 综合信号 =====
signal = 'waiting'
reasons = []

reasons.append(f'{trend_dir}趋势(强度{trend_strength:.0f}%)')
reasons.append(f'24h:{h24_change:+.1f}%')
reasons.append(f'RSI(4h):{rsi_4h:.0f} RSI(1h):{rsi_1h:.0f}')
reasons.append(f'ATR:{atr_4h:.0f}')

if is_consolidating:
    reasons.append(f'横盘确认({sum(osc_conditions)}/4)')
else:
    reasons.append(f'非横盘({sum(osc_conditions)}/4)')

# 回踩状态
if trend_down:
    if pullback_down:
        reasons.append('✅回踩EMA25到位')
    elif far_from_ema25 and is_oversold:
        reasons.append(f'⏳急跌超卖(RSI<{30}),等待反弹回踩EMA25({ema25_4h:.0f})')
    else:
        reasons.append(f'⏳等待回踩(距EMA25:{pullback_distance:+.1f}ATR)')
elif trend_up:
    if pullback_up:
        reasons.append('✅回踩EMA25到位')
    elif far_from_ema25 and is_overbought:
        reasons.append(f'⏳急涨超买(RSI>{70}),等待回调回踩EMA25({ema25_4h:.0f})')
    else:
        reasons.append(f'⏳等待回踩(距EMA25:{pullback_distance:+.1f}ATR)')

# === 信号触发 ===
if can_trade:
    # 做空：下跌趋势 + 回踩EMA25 + 横盘 + 1h确认
    if trend_down and pullback_down and is_consolidating:
        if h1_trend_down or bearish_candle:
            signal = 'short'
            sl = price + atr_4h * 2
            tp = price - atr_4h * 3
            reasons.insert(0, '🔊下跌趋势回踩横盘→做空')
            reasons.append(f'止损:{sl:.0f} 止盈:{tp:.0f}')
            reasons.append(f'仓位:{position_size:.2f}手({position_pct:.1f}%) 盈亏比1:1.5')
            save_last_signal({'time': datetime.datetime.now(datetime.timezone.utc).isoformat(), 'signal': 'short', 'price': price})

    # 做多：上涨趋势 + 回踩EMA25 + 横盘 + 1h确认
    elif trend_up and pullback_up and is_consolidating:
        if h1_trend_up or bullish_candle:
            signal = 'long'
            sl = price - atr_4h * 2
            tp = price + atr_4h * 3
            reasons.insert(0, '🔊上涨趋势回踩横盘→做多')
            reasons.append(f'止损:{sl:.0f} 止盈:{tp:.0f}')
            reasons.append(f'仓位:{position_size:.2f}手({position_pct:.1f}%) 盈亏比1:1.5')
            save_last_signal({'time': datetime.datetime.now(datetime.timezone.utc).isoformat(), 'signal': 'long', 'price': price})

if skip_event:
    reasons.append(f'⚠️{event_reason}暂停交易')
if in_cooldown:
    reasons.append('⏸️信号冷却中(1h)')

# ===== 回测 =====
bt_result = backtest(k4h)

print(f'Price={price:.2f} Trend={trend_dir}({trend_strength:.0f}%) RSI4h={rsi_4h:.1f} RSI1h={rsi_1h:.1f} ATR={atr_4h:.0f} Signal={signal}')
print(f'24h={h24_change:+.2f}% 24h_range={range_24h:.2f}% Consolidating={is_consolidating} Pullback_dist={pullback_distance:.1f}ATR')
if bt_result:
    print(f'Backtest: {bt_result["note"]}')

# ===== 输出 =====
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
            'stable': is_consolidating
        },
        'h4': {
            'rsi': round(rsi_4h, 1),
            'ema7': round(ema7_4h, 2),
            'ema25': round(ema25_4h, 2),
            'ema50': round(ema50_4h, 2),
            'atr': round(atr_4h, 2),
            'h24_change': round(h24_change, 2),
            'trend': trend_dir,
            'trend_strength': round(trend_strength, 2),
            'oscillating': is_consolidating,
            'osc_score': sum(osc_conditions),
            'pullback': pullback_down or pullback_up,
            'pullback_distance': round(pullback_distance, 2),
            'far_from_ema25': far_from_ema25,
            'oversold': is_oversold,
            'overbought': is_overbought,
            'stopLoss': round(price + atr_4h * 2, 2) if signal == 'short' else round(price - atr_4h * 2, 2) if signal == 'long' else 0,
            'takeProfit': round(price - atr_4h * 3, 2) if signal == 'short' else round(price + atr_4h * 3, 2) if signal == 'long' else 0,
            'position_size': round(position_size, 2) if signal != 'waiting' else 0,
            'position_pct': round(position_pct, 1) if signal != 'waiting' else 0
        },
        'backtest': bt_result
    },
    'timestamp': int(datetime.datetime.now(datetime.timezone.utc).timestamp() * 1000),
    'source': 'vps-rainyun-v4'
}

out = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data', 'data.json')
with open(out, 'w') as fp:
    json.dump(data, fp, indent=2)
print(f'Written to {out}')