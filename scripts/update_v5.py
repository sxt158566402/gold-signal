#!/usr/bin/env python3
"""Gold Sniper v5 - 日线趋势 + 分级回踩 + 超卖反弹策略

核心逻辑：
  1. 日线定方向：找最近18+根K线的盘整区间，破位确认趋势
  2. 三种入场模式增加出单频率：
     A. 超卖反弹做空/超买回调做多（最频繁）
     B. 回踩EMA7做空/做多（中等频率）
     C. 回踩EMA25做空/做多（标准趋势单）
  3. 1H级别企稳确认入场时机
  4. 只顺趋势方向做单

改进项（v4→v5）：
  - 趋势判断改为日线级别（18+根K线破位），不再用4H EMA排列
  - 增加超卖反弹/超买回调模式，不用等回踩EMA25
  - 增加回踩EMA7模式，比EMA25更容易触发
  - 1H企稳确认：波幅收窄 + RSI拐头 + 止跌K线
  - 保留：仓位管理、信号冷却、周末过滤、回测引擎
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

# ===== 日线趋势判断（18+根K线破位）=====
def judge_daily_trend(klines_1d, price):
    """
    找最近的盘整区间，判断是否破位。
    
    逻辑：
    1. 从最近的K线往前找，计算每根K线的高低范围
    2. 找到一个连续盘整的区间（高低范围重叠）
    3. 如果盘整了18根以上，然后价格突破区间上沿→多头
    4. 如果盘整了18根以上，然后价格跌破区间下沿→空头
    
    返回: (trend_dir, trend_strength, range_high, range_low, bars_in_range, breakout_dir)
    """
    if len(klines_1d) < 20:
        return '无趋势', 0, 0, 0, 0, 'none'
    
    closes = [float(k[4]) for k in klines_1d]
    closes[-1] = price  # 用实时价格
    
    # 从最近往前扫描，找盘整区间
    # 策略：从最后一根往前推，维护一个区间[low, high]
    # 如果新K线在区间内→扩展区间
    # 如果突破区间→记录破位方向
    # 如果盘整了18+根→确认趋势
    
    best_range_high = 0
    best_range_low = float('inf')
    best_bars_in_range = 0
    best_breakout = 'none'
    best_breakout_idx = -1
    
    # 从最近往前看50根日线
    lookback = min(len(closes) - 1, 50)
    
    for start in range(len(closes) - 1, max(len(closes) - 1 - lookback, 18), -1):
        # 从start往前看有多少根在这个盘整区间内
        range_high = closes[start]
        range_low = closes[start]
        bars = 1
        
        for j in range(start - 1, max(start - 50, -1), -1):
            c = closes[j]
            new_high = max(range_high, c)
            new_low = min(range_low, c)
            new_range_pct = (new_high - new_low) / new_low * 100
            
            # 如果区间扩展不超过8%，认为还在盘整
            if new_range_pct < 8.0:
                range_high = new_high
                range_low = new_low
                bars += 1
            else:
                break
        
        # 检查是否盘整了18+根且价格已破位
        if bars >= 18:
            # 检查当前价格是否破位
            if price < range_low:
                # 跌破下沿 → 空头
                breakout_strength = (range_low - price) / (range_high - range_low) * 100 if range_high > range_low else 0
                if bars > best_bars_in_range or (bars == best_bars_in_range and breakout_strength > 0):
                    best_range_high = range_high
                    best_range_low = range_low
                    best_bars_in_range = bars
                    best_breakout = 'down'
                    best_breakout_idx = start
                    break
            elif price > range_high:
                # 突破上沿 → 多头
                breakout_strength = (price - range_high) / (range_high - range_low) * 100 if range_high > range_low else 0
                if bars > best_bars_in_range:
                    best_range_high = range_high
                    best_range_low = range_low
                    best_bars_in_range = bars
                    best_breakout = 'up'
                    best_breakout_idx = start
                    break
    
    # 如果没有找到18+根的盘整区间，用EMA辅助判断
    if best_breakout == 'none':
        ema7_d = calc_ema(closes, 7)
        ema25_d = calc_ema(closes, 25)
        ema50_d = calc_ema(closes, 50)
        
        trend_down_strict = ema7_d < ema25_d < ema50_d
        trend_down_simple = price < ema25_d and ema7_d < ema25_d
        trend_up_strict = ema7_d > ema25_d > ema50_d
        trend_up_simple = price > ema25_d and ema7_d > ema25_d
        
        if trend_down_strict or trend_down_simple:
            atr_d = calc_atr(klines_1d, 14) if len(klines_1d) > 15 else 20
            strength = (ema25_d - price) / atr_d * 100 if atr_d > 0 else 0
            return '下跌', round(strength, 2), round(ema25_d, 2), round(ema50_d, 2), 0, 'ema_down'
        elif trend_up_strict or trend_up_simple:
            atr_d = calc_atr(klines_1d, 14) if len(klines_1d) > 15 else 20
            strength = (price - ema25_d) / atr_d * 100 if atr_d > 0 else 0
            return '上涨', round(strength, 2), round(ema25_d, 2), round(ema50_d, 2), 0, 'ema_up'
        else:
            return '无趋势', 0, 0, 0, 0, 'none'
    
    # 找到了破位区间
    if best_breakout == 'down':
        atr_d = calc_atr(klines_1d, 14) if len(klines_1d) > 15 else 20
        strength = (best_range_low - price) / atr_d * 100 if atr_d > 0 else 0
        return '下跌', round(strength, 2), round(best_range_high, 2), round(best_range_low, 2), best_bars_in_range, 'breakout_down'
    else:
        atr_d = calc_atr(klines_1d, 14) if len(klines_1d) > 15 else 20
        strength = (price - best_range_high) / atr_d * 100 if atr_d > 0 else 0
        return '上涨', round(strength, 2), round(best_range_high, 2), round(best_range_low, 2), best_bars_in_range, 'breakout_up'

# ===== 1H企稳判断 =====
def check_h1_stabilize(klines_1h, closes_1h, trend_dir):
    """
    判断1H级别是否企稳。
    企稳条件（满足2个即可）：
    1. 最近3根1H K线波幅收窄
    2. 1H RSI拐头（从下往上=企稳做空前的反弹，或从上往下=企稳做多前的回调）
    3. 1H出现止跌/止涨K线形态
    """
    if len(klines_1h) < 6 or len(closes_1h) < 20:
        return False, 0, []
    
    score = 0
    details = []
    
    # 1. 最近3根1H波幅 vs 前3根
    recent_3_range = max(float(k[2]) for k in klines_1h[-3:]) - min(float(k[3]) for k in klines_1h[-3:])
    prev_3_range = max(float(k[2]) for k in klines_1h[-6:-3]) - min(float(k[3]) for k in klines_1h[-6:-3])
    if prev_3_range > 0 and recent_3_range < prev_3_range * 0.7:
        score += 1
        details.append('波幅收窄')
    
    # 2. RSI拐头
    rsi_now = calc_rsi(closes_1h[-15:], 14)
    rsi_prev = calc_rsi(closes_1h[-16:-1], 14)
    
    if trend_dir == '下跌':
        # 做空前需要企稳：RSI从超卖区拐头往上=反弹企稳
        if rsi_now > rsi_prev and rsi_now < 50:
            score += 1
            details.append(f'RSI拐头反弹({rsi_now:.0f})')
    elif trend_dir == '上涨':
        # 做多前需要企稳：RSI从超买区拐头往下=回调企稳
        if rsi_now < rsi_prev and rsi_now > 50:
            score += 1
            details.append(f'RSI拐头回调({rsi_now:.0f})')
    
    # 3. 止跌/止涨K线形态
    last = klines_1h[-1]
    o, h, l, c = float(last[1]), float(last[2]), float(last[3]), float(last[4])
    body = abs(c - o)
    upper_wick = h - max(o, c)
    lower_wick = min(o, c) - l
    total_range = h - l
    
    if total_range > 0:
        if trend_dir == '下跌':
            # 止跌K线：下影线长 + 实体小（十字星/锤子线/阳线）
            if lower_wick > body * 1.5 and lower_wick > total_range * 0.4:
                score += 1
                details.append('止跌K线')
            elif c > o:  # 收阳
                score += 1
                details.append('收阳企稳')
        elif trend_dir == '上涨':
            # 止涨K线：上影线长 + 实体小
            if upper_wick > body * 1.5 and upper_wick > total_range * 0.4:
                score += 1
                details.append('止涨K线')
            elif c < o:  # 收阴
                score += 1
                details.append('收阴企稳')
    
    return score >= 2, score, details

# ===== 回测引擎（v5：三种模式）=====
def backtest(klines_4h, klines_1d, initial_capital=10000):
    """回测v5策略历史表现"""
    if len(klines_4h) < 60 or len(klines_1d) < 20:
        return {'total': 0, 'wins': 0, 'win_rate': 0, 'note': '数据不足'}
    
    closes_4h = [float(k[4]) for k in klines_4h]
    trades = []
    
    for i in range(50, len(closes_4h) - 6):
        window_closes = closes_4h[:i+1]
        window_kl = klines_4h[:i+1]
        
        if len(window_closes) < 50:
            continue
        
        price_i = closes_4h[i]
        ema7 = calc_ema(window_closes, 7)
        ema25 = calc_ema(window_closes, 25)
        atr = calc_atr(window_kl, 14)
        rsi = calc_rsi(window_closes, 14)
        
        if atr == 0:
            continue
        
        # 简化趋势判断
        trend_down = price_i < ema25 and ema7 < ema25
        trend_up = price_i > ema25 and ema7 > ema25
        
        if not trend_down and not trend_up:
            continue
        
        signal = None
        
        # 模式A：超卖反弹做空 / 超买回调做多
        if trend_down and rsi < 25:
            signal = 'short'
        elif trend_up and rsi > 75:
            signal = 'long'
        
        # 模式B：回踩EMA7
        if signal is None:
            if trend_down and abs(price_i - ema7) < atr * 1.0 and price_i < ema25:
                signal = 'short'
            elif trend_up and abs(price_i - ema7) < atr * 1.0 and price_i > ema25:
                signal = 'long'
        
        # 模式C：回踩EMA25
        if signal is None:
            if trend_down and abs(price_i - ema25) < atr * 1.5:
                signal = 'short'
            elif trend_up and abs(price_i - ema25) < atr * 1.5:
                signal = 'long'
        
        if signal is None:
            continue
        
        entry = closes_4h[i]
        if signal == 'short':
            sl = entry + atr * 2
            tp = entry - atr * 3
        else:
            sl = entry - atr * 2
            tp = entry + atr * 3
        
        result = None
        for j in range(1, 7):
            if i + j >= len(klines_4h):
                break
            k = klines_4h[i + j]
            h, l = float(k[2]), float(k[3])
            if signal == 'short':
                if h >= sl: result = 'loss'; break
                if l <= tp: result = 'win'; break
            else:
                if l <= sl: result = 'loss'; break
                if h >= tp: result = 'win'; break
        
        if result is None:
            exit_price = closes_4h[min(i+6, len(closes_4h)-1)]
            if signal == 'short':
                result = 'win' if exit_price < entry else 'loss'
            else:
                result = 'win' if exit_price > entry else 'loss'
        
        trades.append({'signal': signal, 'result': result})
    
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

# 日线数据
k1d = fetch('https://api.bitget.com/api/v2/spot/market/candles?symbol=PAXGUSDT&granularity=1day&limit=60')['data']
k1d.reverse()
closes_1d = [float(k[4]) for k in k1d]
closes_1d[-1] = price  # 实时价格替换未收盘日线

# 4H数据
k4h = fetch('https://api.bitget.com/api/v2/spot/market/candles?symbol=PAXGUSDT&granularity=4h&limit=200')['data']
k4h.reverse()
closes_4h = [float(k[4]) for k in k4h]
closes_4h[-1] = price

# 1H数据
k1h = fetch('https://api.bitget.com/api/v2/spot/market/candles?symbol=PAXGUSDT&granularity=1h&limit=100')['data']
k1h.reverse()
closes_1h = [float(k[4]) for k in k1h]
closes_1h[-1] = price

# ===== 日线指标 =====
ema7_d = calc_ema(closes_1d, 7)
ema25_d = calc_ema(closes_1d, 25)
ema50_d = calc_ema(closes_1d, 50)
rsi_d = calc_rsi(closes_1d, 14)
atr_d = calc_atr(k1d, 14)

# 日线趋势判断（18+根K线破位）
trend_dir, trend_strength, range_high, range_low, bars_in_range, breakout_type = judge_daily_trend(k1d, price)

# ===== 4H指标 =====
rsi_4h = calc_rsi(closes_4h, 14)
ema7_4h = calc_ema(closes_4h, 7)
ema25_4h = calc_ema(closes_4h, 25)
ema50_4h = calc_ema(closes_4h, 50)
bb_mid_4h, bb_up_4h, bb_low_4h, bb_std_4h = calc_bb(closes_4h, 20)
atr_4h = calc_atr(k4h, 14)

# 24h涨跌幅
h24_change = (price - closes_4h[-7]) / closes_4h[-7] * 100 if len(closes_4h) >= 7 else 0

# ===== 1H指标 =====
rsi_1h = calc_rsi(closes_1h, 14)
ema7_1h = calc_ema(closes_1h, 7)
ema25_1h = calc_ema(closes_1h, 25)
bb_mid_1h, bb_up_1h, bb_low_1h, bb_std_1h = calc_bb(closes_1h, 20)

# ===== 趋势方向（从日线趋势得到）=====
trend_down = (trend_dir == '下跌')
trend_up = (trend_dir == '上涨')

# ===== 三种入场模式判断 =====
# 模式A：超卖反弹做空 / 超买回调做多
mode_a = False
mode_a_reason = ''
if trend_down and rsi_4h < 20:
    mode_a = True
    mode_a_reason = f'模式A:超卖反弹做空(RSI4h={rsi_4h:.0f}<20)'
elif trend_up and rsi_4h > 80:
    mode_a = True
    mode_a_reason = f'模式A:超买回调做多(RSI4h={rsi_4h:.0f}>80)'

# 模式B：回踩EMA7
mode_b = False
mode_b_reason = ''
dist_ema7 = abs(price - ema7_4h) / atr_4h if atr_4h > 0 else 999
if trend_down and dist_ema7 < 1.0 and price < ema25_4h:
    mode_b = True
    mode_b_reason = f'模式B:回踩EMA7做空(距{dist_ema7:.1f}ATR)'
elif trend_up and dist_ema7 < 1.0 and price > ema25_4h:
    mode_b = True
    mode_b_reason = f'模式B:回踩EMA7做多(距{dist_ema7:.1f}ATR)'

# 模式C：回踩EMA25（标准趋势单）
mode_c = False
mode_c_reason = ''
dist_ema25 = abs(price - ema25_4h) / atr_4h if atr_4h > 0 else 999
if trend_down and dist_ema25 < 1.5:
    mode_c = True
    mode_c_reason = f'模式C:回踩EMA25做空(距{dist_ema25:.1f}ATR)'
elif trend_up and dist_ema25 < 1.5:
    mode_c = True
    mode_c_reason = f'模式C:回踩EMA25做多(距{dist_ema25:.1f}ATR)'

# 1H企稳确认
h1_stable, h1_score, h1_details = check_h1_stabilize(k1h, closes_1h, trend_dir)

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
signal_mode = ''
reasons = []

# 趋势信息
if bars_in_range >= 18:
    reasons.append(f'日线{trend_dir}趋势(破位{bars_in_range}根区间,强度{trend_strength:.0f}%)')
else:
    reasons.append(f'日线{trend_dir}趋势(EMA确认,强度{trend_strength:.0f}%)')

reasons.append(f'24h:{h24_change:+.1f}%')
reasons.append(f'RSI(d):{rsi_d:.0f} RSI(4h):{rsi_4h:.0f} RSI(1h):{rsi_1h:.0f}')
reasons.append(f'ATR(4h):{atr_4h:.0f}')

# 日线EMA
reasons.append(f'EMA25(d):{ema25_d:.0f} EMA50(d):{ema50_d:.0f}')

# 入场模式状态
mode_status = []
if mode_a: mode_status.append('A✅')
if mode_b: mode_status.append('B✅')
if mode_c: mode_status.append('C✅')
if not mode_status: mode_status.append('等待中')
reasons.append(f'入场模式:{"|".join(mode_status)}')

if mode_a: reasons.append(mode_a_reason)
if mode_b: reasons.append(mode_b_reason)
if mode_c: reasons.append(mode_c_reason)

# 1H企稳状态
if h1_stable:
    reasons.append(f'1H企稳✅({",".join(h1_details)})')
else:
    reasons.append(f'1H未企稳({h1_score}/2)')

# 距离EMA7和EMA25
reasons.append(f'距EMA7(4h):{dist_ema7:.1f}ATR 距EMA25(4h):{dist_ema25:.1f}ATR')

# === 信号触发 ===
if can_trade and (trend_down or trend_up):
    # 选择最高优先级的模式
    triggered = False
    
    # 模式A：超卖/超买 + 1H企稳
    if not triggered and mode_a and h1_stable:
        triggered = True
        signal_mode = 'A'
        if trend_down:
            signal = 'short'
            sl = price + atr_4h * 2
            tp = price - atr_4h * 3
            reasons.insert(0, f'🔊【模式A】超卖反弹做空')
        else:
            signal = 'long'
            sl = price - atr_4h * 2
            tp = price + atr_4h * 3
            reasons.insert(0, f'🔊【模式A】超买回调做多')
    
    # 模式B：回踩EMA7 + 1H企稳
    if not triggered and mode_b and h1_stable:
        triggered = True
        signal_mode = 'B'
        if trend_down:
            signal = 'short'
            sl = price + atr_4h * 2
            tp = price - atr_4h * 3
            reasons.insert(0, f'🔊【模式B】回踩EMA7做空')
        else:
            signal = 'long'
            sl = price - atr_4h * 2
            tp = price + atr_4h * 3
            reasons.insert(0, f'🔊【模式B】回踩EMA7做多')
    
    # 模式C：回踩EMA25 + 1H企稳
    if not triggered and mode_c and h1_stable:
        triggered = True
        signal_mode = 'C'
        if trend_down:
            signal = 'short'
            sl = price + atr_4h * 2
            tp = price - atr_4h * 3
            reasons.insert(0, f'🔊【模式C】回踩EMA25做空')
        else:
            signal = 'long'
            sl = price - atr_4h * 2
            tp = price + atr_4h * 3
            reasons.insert(0, f'🔊【模式C】回踩EMA25做多')
    
    if triggered:
        reasons.append(f'止损:{sl:.0f} 止盈:{tp:.0f}')
        reasons.append(f'仓位:{position_size:.2f}手({position_pct:.1f}%) 盈亏比1:1.5')
        save_last_signal({
            'time': datetime.datetime.now(datetime.timezone.utc).isoformat(),
            'signal': signal,
            'price': price,
            'mode': signal_mode
        })

if skip_event:
    reasons.append(f'⚠️{event_reason}暂停交易')
if in_cooldown:
    reasons.append('⏸️信号冷却中(1h)')

# ===== 回测 =====
bt_result = backtest(k4h, k1d)

print(f'Price={price:.2f} Trend={trend_dir}({trend_strength:.0f}%) RSI4h={rsi_4h:.1f} RSI1h={rsi_1h:.1f} ATR={atr_4h:.0f} Signal={signal}')
print(f'24h={h24_change:+.2f}% ModeA={mode_a} ModeB={mode_b} ModeC={mode_c} H1stable={h1_stable}({h1_score}/2)')
print(f'Breakout: type={breakout_type} bars={bars_in_range} range={range_low:.0f}~{range_high:.0f}')
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
        'signal_mode': signal_mode,
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
            'stable': h1_stable
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
            'oscillating': h1_stable,
            'osc_score': h1_score,
            'pullback': mode_a or mode_b or mode_c,
            'pullback_distance': round((price - ema25_4h) / atr_4h, 2) if atr_4h > 0 else 0,
            'far_from_ema25': dist_ema25 > 3,
            'oversold': rsi_4h < 30,
            'overbought': rsi_4h > 70,
            'mode_a': mode_a,
            'mode_b': mode_b,
            'mode_c': mode_c,
            'mode_a_reason': mode_a_reason,
            'mode_b_reason': mode_b_reason,
            'mode_c_reason': mode_c_reason,
            'h1_stable': h1_stable,
            'h1_score': h1_score,
            'h1_details': h1_details,
            'stopLoss': round(sl, 2) if signal != 'waiting' else 0,
            'takeProfit': round(tp, 2) if signal != 'waiting' else 0,
            'position_size': round(position_size, 2) if signal != 'waiting' else 0,
            'position_pct': round(position_pct, 1) if signal != 'waiting' else 0
        },
        'daily': {
            'rsi': round(rsi_d, 1),
            'ema7': round(ema7_d, 2),
            'ema25': round(ema25_d, 2),
            'ema50': round(ema50_d, 2),
            'atr': round(atr_d, 2),
            'trend': trend_dir,
            'trend_strength': round(trend_strength, 2),
            'breakout_type': breakout_type,
            'bars_in_range': bars_in_range,
            'range_high': round(range_high, 2),
            'range_low': round(range_low, 2),
            'price_vs_ema25': round((price - ema25_d) / ema25_d * 100, 2) if ema25_d > 0 else 0
        },
        'backtest': bt_result
    },
    'timestamp': int(datetime.datetime.now(datetime.timezone.utc).timestamp() * 1000),
    'source': 'vps-rainyun-v5'
}

out = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data', 'data.json')
with open(out, 'w') as fp:
    json.dump(data, fp, indent=2)
