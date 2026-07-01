#!/usr/bin/env python3
"""Gold Sniper v7 - 提前检测快横盘+推送最高价+破位放弃

核心逻辑：
  1. 日线定方向：找最近18+根K线的盘整区间，破位确认趋势
  2. 提前检测快横盘：不用等横盘确认，通过数据分析判断快横盘了
     - RSI回升到50+
     - 价格反弹到EMA25压力位附近
     - K线实体逐渐缩小
     - 连续上涨/下跌根数
     - 反弹/回调幅度
     - 综合评分 >= 3 = 快横盘了
  3. 信号推送横盘最高价（不是当前价格），用户自己等高位进场
  4. 破位检测：横盘被突破往上走 → 推送"放弃本轮，等下一轮"
  5. 止损10点，止盈10点，推动止盈只做提醒（手动操作）
  6. 多头趋势反过来做（在横盘下沿做多）
  7. 冷却15分钟

v7改进：
  - 从"等横盘形成"改为"提前分析快横盘"
  - 信号推送横盘区间最高价（不是当前价格）
  - 新增破位放弃本轮检测
  - 止损止盈只做提醒，不自动执行
  - 保留三种模式A/B/C作为辅助确认
  - 推动止盈提醒
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
        return elapsed < 900  # 15分钟冷却
    except:
        return False

def get_signal_age_seconds():
    """返回上一个信号已经持续了多少秒"""
    last = load_last_signal()
    if not last.get('time'):
        return 0
    try:
        return (datetime.datetime.now(datetime.timezone.utc) -
                datetime.datetime.fromisoformat(last['time'])).total_seconds()
    except:
        return 0

def get_last_signal_first_time():
    """获取信号第一次触发的时间（用于判断信号持续了多久）"""
    last = load_last_signal()
    return last.get('first_time', last.get('time', ''))

def save_last_signal(sig):
    try:
        old = load_last_signal()
        old_signal = old.get('signal', '')
        new_signal = sig.get('signal', '')
        
        if old_signal == new_signal and old.get('first_time'):
            # 信号方向没变，保留 first_time 和已有提醒标记
            sig['first_time'] = old['first_time']
            # 保留提醒标记
            if old.get('reminded_duration'):
                sig['reminded_duration'] = True
            if old.get('reminded_entry'):
                sig['reminded_entry'] = True
        elif new_signal in ('short', 'long'):
            # 新信号方向，重置 first_time，不带提醒标记
            sig['first_time'] = sig.get('time', datetime.datetime.now(datetime.timezone.utc).isoformat())
        # waiting/breakout 不需要 first_time 和提醒标记
        
        with open(SIGNAL_COOLDOWN_FILE, 'w') as f:
            json.dump(sig, f)
    except:
        pass

def has_reminded(reminder_type):
    """检查是否已经发过某种提醒（进场提醒/持续提醒）"""
    last = load_last_signal()
    return last.get(f'reminded_{reminder_type}', False)

def mark_reminded(reminder_type):
    """标记已发过某种提醒"""
    last = load_last_signal()
    last[f'reminded_{reminder_type}'] = True
    try:
        with open(SIGNAL_COOLDOWN_FILE, 'w') as f:
            json.dump(last, f)
    except:
        pass

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
        return 50.0
    gains, losses = [], []
    for i in range(1, len(closes)):
        diff = closes[i] - closes[i-1]
        if diff >= 0:
            gains.append(diff); losses.append(0)
        else:
            gains.append(0); losses.append(abs(diff))
    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return round(100 - 100 / (1 + rs), 1)

def calc_ema(closes, period):
    if len(closes) < period:
        return closes[-1] if closes else 0
    k = 2 / (period + 1)
    ema = closes[0]
    for c in closes[1:]:
        ema = c * k + ema * (1 - k)
    return ema

def calc_atr(klines, period=14):
    if len(klines) < 2:
        return 20.0
    trs = []
    for i in range(1, len(klines)):
        h, l, pc = float(klines[i][2]), float(klines[i][3]), float(klines[i-1][4])
        tr = max(h - l, abs(h - pc), abs(l - pc))
        trs.append(tr)
    return sum(trs[-period:]) / min(period, len(trs))

def calc_bb(closes, period=20, std_dev=2):
    if len(closes) < period:
        mid = sum(closes) / len(closes) if closes else 0
        return mid, mid, mid, 0
    window = closes[-period:]
    mid = sum(window) / period
    variance = sum((x - mid) ** 2 for x in window) / period
    std = math.sqrt(variance)
    return mid, mid + std_dev * std, mid - std_dev * std, std

# ===== 日线趋势判断 =====
def judge_daily_trend(klines_1d, price):
    """找最近盘整区间，判断破位方向"""
    if len(klines_1d) < 20:
        closes = [float(k[4]) for k in klines_1d]
        if len(closes) < 5:
            return '无趋势', 0, 0, 0, 0, 'none'
        ema7 = calc_ema(closes, 7)
        ema25 = calc_ema(closes, 25)
        if ema7 < ema25:
            atr_d = calc_atr(klines_1d, 14) if len(klines_1d) > 15 else 20
            return '下跌', abs((price - ema25) / atr_d * 100), max(closes[-20:]), min(closes[-20:]), min(20, len(klines_1d)), 'ema_confirm'
        else:
            atr_d = calc_atr(klines_1d, 14) if len(klines_1d) > 15 else 20
            return '上涨', abs((price - ema25) / atr_d * 100), max(closes[-20:]), min(closes[-20:]), min(20, len(klines_1d)), 'ema_confirm'

    # 找最近盘整区间（从最近往前找，至少18根）
    best_bars = 0
    best_range_high = 0
    best_range_low = 999999
    closes_all = [float(k[4]) for k in klines_1d]

    for lookback in range(40, min(len(klines_1d), 80), 2):
        window = klines_1d[-lookback:]
        highs = [float(k[2]) for k in window]
        lows = [float(k[3]) for k in window]
        max_h = max(highs)
        min_l = min(lows)
        range_pct = (max_h - min_l) / min_l * 100

        # 盘整区间：波幅小于5%
        if range_pct < 5:
            bars_in = len(window)
            if bars_in > best_bars:
                best_bars = bars_in
                best_range_high = max_h
                best_range_low = min_l

    if best_bars >= 18:
        atr_d = calc_atr(klines_1d, 14)
        if price < best_range_low:
            strength = (best_range_low - price) / atr_d * 100 if atr_d > 0 else 0
            return '下跌', round(strength, 2), round(best_range_high, 2), round(best_range_low, 2), best_bars, 'breakout_down'
        elif price > best_range_high:
            strength = (price - best_range_high) / atr_d * 100 if atr_d > 0 else 0
            return '上涨', round(strength, 2), round(best_range_high, 2), round(best_range_low, 2), best_bars, 'breakout_up'
        else:
            return '无趋势', 0, round(best_range_high, 2), round(best_range_low, 2), best_bars, 'in_range'
    else:
        closes = [float(k[4]) for k in klines_1d]
        ema7 = calc_ema(closes, 7)
        ema25 = calc_ema(closes, 25)
        if ema7 < ema25:
            atr_d = calc_atr(klines_1d, 14) if len(klines_1d) > 15 else 20
            return '下跌', abs((price - ema25) / atr_d * 100), max(closes_all[-30:]), min(closes_all[-30:]), min(30, len(klines_1d)), 'ema_confirm'
        elif ema7 > ema25:
            atr_d = calc_atr(klines_1d, 14) if len(klines_1d) > 15 else 20
            return '上涨', abs((price - ema25) / atr_d * 100), max(closes_all[-30:]), min(closes_all[-30:]), min(30, len(klines_1d)), 'ema_confirm'
        return '无趋势', 0, 0, 0, 0, 'none'

# ===== 1H企稳判断 =====
def check_h1_stabilize(klines_1h, closes_1h, trend_dir):
    if len(klines_1h) < 6 or len(closes_1h) < 20:
        return False, 0, []
    score = 0
    details = []
    recent_3_range = max(float(k[2]) for k in klines_1h[-3:]) - min(float(k[3]) for k in klines_1h[-3:])
    prev_3_range = max(float(k[2]) for k in klines_1h[-6:-3]) - min(float(k[3]) for k in klines_1h[-6:-3])
    if prev_3_range > 0 and recent_3_range < prev_3_range * 0.7:
        score += 1
        details.append('波幅收窄')
    rsi_now = calc_rsi(closes_1h[-15:], 14)
    rsi_prev = calc_rsi(closes_1h[-16:-1], 14)
    if trend_dir == '下跌':
        if rsi_now > rsi_prev and rsi_now < 50:
            score += 1
            details.append(f'RSI拐头反弹({rsi_now:.0f})')
    elif trend_dir == '上涨':
        if rsi_now < rsi_prev and rsi_now > 50:
            score += 1
            details.append(f'RSI拐头回调({rsi_now:.0f})')
    last = klines_1h[-1]
    o, h, l, c = float(last[1]), float(last[2]), float(last[3]), float(last[4])
    body = abs(c - o)
    upper_wick = h - max(o, c)
    lower_wick = min(o, c) - l
    total_range = h - l
    if total_range > 0:
        if trend_dir == '下跌':
            if lower_wick > body * 1.5 and lower_wick > total_range * 0.4:
                score += 1
                details.append('止跌K线')
            elif c > o:
                score += 1
                details.append('收阳企稳')
        elif trend_dir == '上涨':
            if upper_wick > body * 1.5 and upper_wick > total_range * 0.4:
                score += 1
                details.append('止涨K线')
            elif c < o:
                score += 1
                details.append('收阴企稳')
    return score >= 2, score, details

# ===== 头肩顶检测（v7c核心） =====
def detect_head_shoulders_top(klines_1h, closes_1h, price):
    """
    检测头肩顶形态：
    左肩(LS) — 头部(H) — 右肩(RS)
    条件：
      1. 在最近15根K线内找到三个局部高点
      2. 左肩 < 头部，右肩 < 头部（头部最高）
      3. 左肩和右肩高度差不多（差值 < 30%头肩高度）
      4. 右肩已经形成（当前价格已从右肩高点回落）
      5. 颈线 = 左肩和右肩之间的低点
    
    返回: (detected, details_dict)
      detected = True 表示检测到头肩顶
      details_dict = {
        'left_shoulder': 左肩价格,
        'head': 头部价格,
        'right_shoulder': 右肩价格,
        'neckline': 颈线价格,
        'right_shoulder_idx': 右肩是第几根K线前,
        'bars_since_rs': 右肩形成后过了多少根K线,
        'broke_neckline': 是否已破颈线
      }
    """
    if len(klines_1h) < 15:
        return False, {}
    
    # 取最近15根K线的高低点
    recent = klines_1h[-15:]
    highs = [float(k[2]) for k in recent]
    lows = [float(k[3]) for k in recent]
    n = len(highs)
    
    # 找局部高点（比前后2根都高）
    peaks = []
    for i in range(2, n - 2):
        if highs[i] > highs[i-1] and highs[i] > highs[i-2] and \
           highs[i] > highs[i+1] and highs[i] > highs[i+2]:
            peaks.append((i, highs[i]))
    
    if len(peaks) < 3:
        return False, {}
    
    # 尝试找最后三个高点组成头肩顶
    # 从后往前找，取最后三个peak
    for end in range(len(peaks), 2, -1):
        ls = peaks[end-3]
        head = peaks[end-2]
        rs = peaks[end-1]
        
        ls_idx, ls_price = ls
        h_idx, h_price = head
        rs_idx, rs_price = rs
        
        # 条件1: 头部必须高于左肩和右肩
        if h_price <= ls_price or h_price <= rs_price:
            continue
        
        # 条件2: 左肩和右肩高度差不超过头部的30%
        shoulder_diff = abs(ls_price - rs_price)
        head_height = h_price - max(ls_price, rs_price)
        if head_height > 0 and shoulder_diff > head_height * 2.5:
            continue
        
        # 条件3: 三个高点之间有间隔（至少间隔2根）
        if h_idx - ls_idx < 2 or rs_idx - h_idx < 2:
            continue
        
        # 颈线 = 左肩和头部之间的低点 与 头部和右肩之间的低点 的较低值
        neckline_left = min(lows[ls_idx:h_idx+1])
        neckline_right = min(lows[h_idx:rs_idx+1])
        neckline = min(neckline_left, neckline_right)
        
        # 条件4: 右肩已形成 — 当前价格已从右肩回落
        current_price = price
        bars_since_rs = n - 1 - rs_idx  # 右肩之后过了多少根K线
        
        # 右肩必须已经形成（至少过了1根K线）
        if bars_since_rs < 1:
            continue
        
        # 当前价格必须低于右肩（说明已从右肩回落）
        if current_price > rs_price:
            continue
        
        # 是否已破颈线
        broke_neckline = current_price < neckline
        
        return True, {
            'left_shoulder': round(ls_price, 2),
            'head': round(h_price, 2),
            'right_shoulder': round(rs_price, 2),
            'neckline': round(neckline, 2),
            'right_shoulder_idx': rs_idx,
            'bars_since_rs': bars_since_rs,
            'broke_neckline': broke_neckline
        }
    
    return False, {}


# ===== 横盘K线计数（v7c新增） =====
def count_consolidation_bars(klines_1h, atr_1h):
    """
    计算最近连续横盘K线数量。
    横盘K线定义：实体波幅 < 0.8 ATR 且整根K线波幅 < 1.2 ATR
    
    返回: 横盘K线根数
    """
    if not klines_1h or atr_1h <= 0:
        return 0
    
    count = 0
    for k in reversed(klines_1h[-6:]):  # 最多看最近6根
        body = abs(float(k[4]) - float(k[1]))
        full_range = float(k[2]) - float(k[3])
        if body < atr_1h * 0.8 and full_range < atr_1h * 1.2:
            count += 1
        else:
            break  # 遇到非横盘K线就中断
    
    return count

# ===== 提前检测快横盘（v7核心） =====
def detect_pre_consolidation(klines_1h, closes_1h, klines_4h, closes_4h, trend_dir, price):
    """
    提前检测快横盘：不用等横盘确认，通过数据分析判断快横盘了。
    
    下跌趋势 → 反弹中，判断反弹是否快到顶了
    上涨趋势 → 回调中，判断回调是否快到底了
    
    评分条件（下跌趋势）：
      1. RSI(1h)从低位回升到50+ = 反弹中
      2. 价格接近EMA25(1h)压力位 = 接近阻力
      3. K线实体逐渐缩小 = 力度减弱
      4. 连续上涨根数 >= 3 = 已经涨了一段
      5. 反弹幅度 >= 30美金 = 回踩幅度够了
      6. RSI(4h)在40-60 = 4小时级别也在反弹
      7. 价格接近布林带(1h)上轨 = 接近阻力
      
    评分 >= 3 = 快横盘了
    
    返回: (is_pre_consolidating, score, conditions, range_high, range_low, breakout_up)
      breakout_up = True 表示横盘已破位往上走，放弃本轮
    """
    if len(klines_1h) < 20 or len(klines_4h) < 10:
        return False, 0, [], 0, 0, False

    conditions = []
    score = 0

    # 1H指标
    rsi_1h = calc_rsi(closes_1h, 14)
    rsi_1h_prev = calc_rsi(closes_1h[-16:-1], 14) if len(closes_1h) > 16 else rsi_1h
    ema25_1h = calc_ema(closes_1h, 25)
    bb_mid_1h, bb_up_1h, bb_low_1h, _ = calc_bb(closes_1h, 20)
    atr_1h = calc_atr(klines_1h, 14)

    # 4H指标
    rsi_4h = calc_rsi(closes_4h, 14)
    ema25_4h = calc_ema(closes_4h, 25)

    # 最近10根1H K线
    last10 = klines_1h[-10:]
    last10_closes = [float(k[4]) for k in last10]
    last10_highs = [float(k[2]) for k in last10]
    last10_lows = [float(k[3]) for k in last10]

    # 横盘区间 = 最近10根K线的高低点（作为参考区间）
    range_high = max(last10_highs)
    range_low = min(last10_lows)

    # ===== 下跌趋势：判断反弹是否快到顶 =====
    if trend_dir == '下跌':
        # 1. RSI(1h)回升到50+
        if rsi_1h >= 50:
            score += 1
            conditions.append(f'RSI(1h)回升到{rsi_1h:.0f}')
        
        # 2. RSI(1h)拐头向上
        if rsi_1h > rsi_1h_prev:
            score += 1
            conditions.append('RSI拐头向上')
        
        # 3. 价格接近EMA25(1h)压力位（距离 < 1.5 ATR）
        dist_ema25 = abs(price - ema25_1h) / atr_1h if atr_1h > 0 else 999
        if dist_ema25 < 1.5:
            score += 1
            conditions.append(f'接近EMA25压力位(距{dist_ema25:.1f}ATR)')
        
        # 4. K线实体逐渐缩小（最近3根实体 < 前3根实体）
        last3_bodies = [abs(float(k[4]) - float(k[1])) for k in klines_1h[-3:]]
        prev3_bodies = [abs(float(k[4]) - float(k[1])) for k in klines_1h[-6:-3]]
        if prev3_bodies and sum(last3_bodies) < sum(prev3_bodies) * 0.8:
            score += 1
            conditions.append('K线实体缩小(力度减弱)')
        
        # 5. 连续上涨根数 >= 3
        consec_up = 0
        for k in reversed(klines_1h[-8:]):
            if float(k[4]) > float(k[1]):
                consec_up += 1
            else:
                break
        if consec_up >= 3:
            score += 1
            conditions.append(f'连涨{consec_up}根')
        
        # 6. 反弹幅度 >= 30美金
        if len(closes_1h) >= 7:
            rebound = price - min(last10_lows)
            if rebound >= 30:
                score += 1
                conditions.append(f'反弹{rebound:.0f}美金')
        
        # 7. RSI(4h)在40-60 = 4小时也在反弹
        if 40 <= rsi_4h <= 65:
            score += 1
            conditions.append(f'RSI(4h)={rsi_4h:.0f}(4H也反弹)')
        
        # 8. 价格接近布林带(1h)上轨
        dist_bb_up = (bb_up_1h - price) / atr_1h if atr_1h > 0 else 999
        if dist_bb_up > -0.5 and dist_bb_up < 1.0:
            score += 1
            conditions.append('接近布林上轨')

    # ===== 上涨趋势：判断回调是否快到底 =====
    elif trend_dir == '上涨':
        # 1. RSI(1h)回落到50以下
        if rsi_1h <= 55:
            score += 1
            conditions.append(f'RSI(1h)回落到{rsi_1h:.0f}')
        
        # 2. RSI(1h)拐头向下
        if rsi_1h < rsi_1h_prev:
            score += 1
            conditions.append('RSI拐头向下')
        
        # 3. 价格接近EMA25(1h)支撑位
        dist_ema25 = abs(price - ema25_1h) / atr_1h if atr_1h > 0 else 999
        if dist_ema25 < 1.5:
            score += 1
            conditions.append(f'接近EMA25支撑位(距{dist_ema25:.1f}ATR)')
        
        # 4. K线实体逐渐缩小
        last3_bodies = [abs(float(k[4]) - float(k[1])) for k in klines_1h[-3:]]
        prev3_bodies = [abs(float(k[4]) - float(k[1])) for k in klines_1h[-6:-3]]
        if prev3_bodies and sum(last3_bodies) < sum(prev3_bodies) * 0.8:
            score += 1
            conditions.append('K线实体缩小(力度减弱)')
        
        # 5. 连续下跌根数 >= 3
        consec_down = 0
        for k in reversed(klines_1h[-8:]):
            if float(k[4]) < float(k[1]):
                consec_down += 1
            else:
                break
        if consec_down >= 3:
            score += 1
            conditions.append(f'连跌{consec_down}根')
        
        # 6. 回调幅度 >= 30美金
        if len(closes_1h) >= 7:
            pullback = max(last10_highs) - price
            if pullback >= 30:
                score += 1
                conditions.append(f'回调{pullback:.0f}美金')
        
        # 7. RSI(4h)在35-60
        if 35 <= rsi_4h <= 60:
            score += 1
            conditions.append(f'RSI(4h)={rsi_4h:.0f}(4H也回调)')
        
        # 8. 价格接近布林带(1h)下轨
        dist_bb_low = (price - bb_low_1h) / atr_1h if atr_1h > 0 else 999
        if dist_bb_low > -0.5 and dist_bb_low < 1.0:
            score += 1
            conditions.append('接近布林下轨')

    # ===== 破位检测 =====
    # 横盘区间被突破往上走 = 放弃本轮
    breakout_up = False
    if range_high > 0 and price > range_high + atr_1h * 0.5:
        breakout_up = True

    # 快横盘 = 评分 >= 3
    is_pre_consolidating = score >= 3

    return is_pre_consolidating, score, conditions, round(range_high, 2), round(range_low, 2), breakout_up

# ===== 回踩横盘检测（v6核心） =====
def detect_pullback_consolidation(klines_1h, closes_1h, trend_dir, price):
    """
    检测回踩横盘：
    方法：用每根1H K线自身的波幅（H-L）来判断横盘，不用整体跨度。
    1. 最近3根1H K线，每根波幅都<12点 = 横盘确认
    2. 之前有一根大波动K线（波幅>20点），说明刚从大波动收敛 = 回踩横盘
    3. 下跌趋势：横盘区间上沿做空 / 上涨趋势：下沿做多

    返回: (is_consolidating, range_high, range_low, range_size, bars_in_range, near_edge, edge_type)
    """
    if len(klines_1h) < 10:
        return False, 0, 0, 0, 0, False, ''

    # 最近3根1H K线，每根的波幅
    last3 = klines_1h[-3:]
    last3_ranges = [float(k[2]) - float(k[3]) for k in last3]  # 每根 H-L
    last3_high = max(float(k[2]) for k in last3)
    last3_low = min(float(k[3]) for k in last3)
    last3_span = last3_high - last3_low  # 3根的高低点跨度

    # 核心：最近3根每根波幅都<12点 = 横盘
    all_small = all(r < 12 for r in last3_ranges)

    # 辅助：之前有波动（前5根中至少有1根波幅>20点 = 刚从波动收敛）
    prev5 = klines_1h[-8:-3]
    prev5_ranges = [float(k[2]) - float(k[3]) for k in prev5]  # 每根波幅
    had_volatility = any(r > 20 for r in prev5_ranges) if len(prev5_ranges) > 0 else False

    # 宽松版：如果最近3根每根<15点且平均<10，也算横盘
    avg3 = sum(last3_ranges) / 3
    loose_check = all(r < 15 for r in last3_ranges) and avg3 < 10

    # 横盘确认：严格模式 or 宽松模式
    is_consolidating = all_small or loose_check

    if not is_consolidating:
        return False, 0, 0, 0, 0, False, ''

    # 横盘区间 = 最近3-5根K线的高低点范围
    # 向前扩展：看更多根K线是否也在这个窄区间内
    range_high = last3_high
    range_low = last3_low
    range_size = last3_span

    # 向前检查更多K线是否也在区间内（扩大横盘确认范围）
    bars_in = 3  # 至少最近3根在区间内
    for k in klines_1h[-8:-3]:  # 往前再检查5根
        h, l = float(k[2]), float(k[3])
        k_range = h - l
        # 这根K线波幅<20且在区间附近 = 属于横盘
        if k_range < 20 and h <= range_high + 3 and l >= range_low - 3:
            bars_in += 1
            range_high = max(range_high, h)
            range_low = min(range_low, l)

    range_size = range_high - range_low

    # 回踩确认：之前有波动（不是一直横盘）
    is_pullback = had_volatility or bars_in <= 8

    # 价格靠近哪一边？
    dist_to_high = abs(price - range_high)
    dist_to_low = abs(price - range_low)
    mid = (range_high + range_low) / 2

    near_edge = False
    edge_type = ''

    if trend_dir == '下跌':
        # 下跌趋势：价格在区间上沿 = 做空位置
        # 价格在上半区（>mid）且离上沿<8点 = 上沿
        if price > mid and dist_to_high < 8:
            near_edge = True
            edge_type = 'upper'
        elif dist_to_high < 3:  # 非常接近上沿
            near_edge = True
            edge_type = 'upper'
    elif trend_dir == '上涨':
        # 上涨趋势：价格在区间下沿 = 做多位置
        if price < mid and dist_to_low < 8:
            near_edge = True
            edge_type = 'lower'
        elif dist_to_low < 3:
            near_edge = True
            edge_type = 'lower'

    # 如果只是横盘但不在边缘，仍然标记横盘但不给信号
    return is_consolidating, round(range_high, 2), round(range_low, 2), round(range_size, 2), bars_in, near_edge, edge_type


# ===== 回测引擎（v6：剥头皮回踩横盘） =====
def backtest(klines_4h, klines_1d, initial_capital=10000):
    """回测v6策略 - 剥头皮模式：止损10点 止盈10点"""
    if len(klines_4h) < 60 or len(klines_1d) < 20:
        return {'total': 0, 'wins': 0, 'win_rate': 0, 'note': '数据不足'}
    closes_4h = [float(k[4]) for k in klines_4h]
    closes_1d = [float(k[4]) for k in klines_1d]
    trades = []
    last_signal_i = -999
    cooldown = 3  # 3根4H冷却（约12小时）

    for i in range(60, len(klines_4h)):
        if i - last_signal_i < cooldown:
            continue

        window_kl = klines_4h[:i+1]
        window_cl = closes_4h[:i+1]
        price_i = closes_4h[i]

        # 日线趋势
        current_ts = int(klines_4h[i][0]) // 1000
        k1d_slice = [k for k in klines_1d if int(k[0])//1000 <= current_ts]
        if len(k1d_slice) < 20:
            continue

        _td_result = judge_daily_trend(k1d_slice, price_i)
        trend_dir = _td_result[0]
        if trend_dir == '无趋势':
            continue

        trend_down = (trend_dir == '下跌')
        trend_up = (trend_dir == '上涨')

        # 模拟横盘检测：最近5根4H K线波幅
        if i < 5:
            continue
        recent_5 = window_kl[-5:]
        r_high = max(float(k[2]) for k in recent_5)
        r_low = min(float(k[3]) for k in recent_5)
        r_range = r_high - r_low

        # 剥头皮条件：波幅<15点 + 顺趋势
        signal = None
        if r_range < 15:
            if trend_down:
                # 下跌趋势，价格在区间上沿做空
                if abs(price_i - r_high) < 5:
                    signal = 'short'
            elif trend_up:
                # 上涨趋势，价格在区间下沿做多
                if abs(price_i - r_low) < 5:
                    signal = 'long'

        if signal is None:
            # 备用：EMA7回踩
            ema7 = calc_ema(window_cl, 7)
            ema25 = calc_ema(window_cl, 25)
            atr = calc_atr(window_kl, 14)
            dist_ema7 = abs(price_i - ema7) / atr if atr > 0 else 999
            if trend_down and dist_ema7 < 1.0 and price_i < ema25:
                signal = 'short'
            elif trend_up and dist_ema7 < 1.0 and price_i > ema25:
                signal = 'long'

        if signal is None:
            continue

        entry = closes_4h[i]
        # 剥头皮：止损10点 止盈10点
        if signal == 'short':
            sl = entry + 10
            tp = entry - 10
        else:
            sl = entry - 10
            tp = entry + 10

        result = None
        for j in range(1, 7):
            if i + j >= len(klines_4h):
                break
            k = klines_4h[i + j]
            h, l = float(k[2]), float(k[3])
            if signal == 'short':
                if h >= sl:
                    result = 'loss'; break
                if l <= tp:
                    result = 'win'; break
            else:
                if l <= sl:
                    result = 'loss'; break
                if h >= tp:
                    result = 'win'; break

        if result is None:
            exit_price = closes_4h[min(i+6, len(closes_4h)-1)]
            result = 'win' if (exit_price < entry if signal == 'short' else exit_price > entry) else 'loss'

        trades.append({'signal': signal, 'result': result})
        last_signal_i = i

    if not trades:
        return {'total': 0, 'wins': 0, 'win_rate': 0, 'note': '回测期间无信号触发'}

    wins = sum(1 for t in trades if t['result'] == 'win')
    win_rate = round(wins / len(trades) * 100, 1)
    return {'total': len(trades), 'wins': wins, 'win_rate': win_rate,
            'note': f'{len(trades)}笔交易,{wins}胜{len(trades)-wins}负,胜率{win_rate}%'}

# ===== 获取数据 =====
tk = fetch('https://api.bitget.com/api/v2/spot/market/tickers?symbol=PAXGUSDT')['data'][0]
price = float(tk['lastPr'])

# 日线数据
k1d = fetch('https://api.bitget.com/api/v2/spot/market/candles?symbol=PAXGUSDT&granularity=1day&limit=60')['data']
k1d.sort(key=lambda x: int(x[0]))
closes_1d = [float(k[4]) for k in k1d]
closes_1d[-1] = price

# 4H数据
k4h = fetch('https://api.bitget.com/api/v2/spot/market/candles?symbol=PAXGUSDT&granularity=4h&limit=200')['data']
k4h.sort(key=lambda x: int(x[0]))
closes_4h = [float(k[4]) for k in k4h]
closes_4h[-1] = price

# 1H数据
k1h = fetch('https://api.bitget.com/api/v2/spot/market/candles?symbol=PAXGUSDT&granularity=1h&limit=100')['data']
k1h.sort(key=lambda x: int(x[0]))
closes_1h = [float(k[4]) for k in k1h]
closes_1h[-1] = price

# ===== 日线指标 =====
ema7_d = calc_ema(closes_1d, 7)
ema25_d = calc_ema(closes_1d, 25)
ema50_d = calc_ema(closes_1d, 50)
rsi_d = calc_rsi(closes_1d, 14)
atr_d = calc_atr(k1d, 14)

# 日线趋势判断
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
atr_1h = calc_atr(k1h, 14)

# ===== 趋势方向 =====
trend_down = (trend_dir == '下跌')
trend_up = (trend_dir == '上涨')

# ===== v7核心：提前检测快横盘 =====
is_pre_consolidating, pre_score, pre_conditions, consol_high, consol_low, breakout_up = \
    detect_pre_consolidation(k1h, closes_1h, k4h, closes_4h, trend_dir, price)

# ===== v7c核心：头肩顶检测 =====
hs_detected, hs_details = detect_head_shoulders_top(k1h, closes_1h, price)

# ===== v7c核心：横盘K线计数 =====
consol_bars_count = count_consolidation_bars(k1h, atr_1h)

# v6备用：横盘确认检测（保留作为备用参考）
is_consolidating, consol_high_v6, consol_low_v6, consol_size_v6, consol_bars_v6, near_edge, edge_type = \
    detect_pullback_consolidation(k1h, closes_1h, trend_dir, price)

# 辅助参考
h1_stable, h1_score, h1_details = check_h1_stabilize(k1h, closes_1h, trend_dir)

# ===== 仓位管理（剥头皮模式：100美金风险，0.01手） =====
account_size = 10000
risk_per_trade = 100  # 每单风险100美金
stop_distance = 10  # 止损10点
position_size = 0.01  # 0.01手
position_pct = (position_size * price / account_size) * 100

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
reasons.append(f'EMA25(d):{ema25_d:.0f} EMA50(d):{ema50_d:.0f}')

# v7核心：快横盘状态
if is_pre_consolidating:
    reasons.append(f'🔍快横盘预警✅ 评分{pre_score}/8 [{" + ".join(pre_conditions)}]')
else:
    reasons.append(f'快横盘:未达标(评分{pre_score}/8)')

# v7c核心：头肩顶状态
if hs_detected:
    hs = hs_details
    reasons.append(f'🤷头肩顶✅ 左肩:{hs["left_shoulder"]} 头:{hs["head"]} 右肩:{hs["right_shoulder"]} 颈线:{hs["neckline"]}')
    reasons.append(f'右肩后横盘:{consol_bars_count}根K线 {"✅≥2" if consol_bars_count >= 2 else "❌<2"}')
    if hs['broke_neckline']:
        reasons.append(f'⚠️已破颈线{hs["neckline"]}')
else:
    reasons.append(f'头肩顶:未检测到')

# 横盘区间
if consol_high > 0:
    reasons.append(f'参考区间:{consol_low:.0f}~{consol_high:.0f}(最高价{consol_high:.0f})')
    if breakout_up:
        reasons.append(f'⚠️破位向上! 价格{price:.0f}突破区间上沿{consol_high:.0f} 放弃本轮等下一轮')

reasons.append(f'1H企稳:{h1_stable}({h1_score}/2)')

# === v7信号触发：提前检测快横盘+推送最高价 ===
sl = 0
tp = 0
entry_price = 0  # 进场参考价（横盘最高价/最低价）

if can_trade and (trend_down or trend_up):
    triggered = False

    # === 破位检测：横盘被突破往上走 → 放弃本轮 ===
    if breakout_up and consol_high > 0:
        signal = 'waiting'
        signal_mode = 'breakout'
        triggered = True  # 触发但不给交易信号，只推送提醒
        reasons.insert(0, f'🔊【破位放弃】价格突破横盘上沿{consol_high:.0f}往上走，放弃本轮等下一轮')
        save_last_signal({
            'time': datetime.datetime.now(datetime.timezone.utc).isoformat(),
            'signal': 'waiting',
            'price': price,
            'mode': 'breakout'
        })

    # === 核心模式：做空必须头肩顶+横盘≥2根，做多保留快横盘逻辑 ===
    elif not triggered:
        
        # ========== 做空逻辑（v7c：头肩顶 + 横盘≥2根） ==========
        if trend_down and hs_detected:
            hs = hs_details
            
            if consol_bars_count >= 2:
                # ✅ 头肩顶 + 横盘≥2根 → 可以做空
                triggered = True
                signal_mode = 'head_shoulders'
                signal = 'short'
                entry_price = hs['right_shoulder']  # 进场参考价 = 右肩价格
                sl = hs['right_shoulder'] + 10  # 止损 = 右肩 + 10点
                tp = hs['right_shoulder'] - 10  # 止盈 = 右肩 - 10点
                reasons.insert(0, f'🔊【头肩顶确认】右肩后横盘{consol_bars_count}根K线，可以做空')
                reasons.append(f'📌进场参考价:右肩 {entry_price:.0f} (等价格回到{entry_price:.0f}附近再进)')
                reasons.append(f'止损:{sl:.0f}(+10点) 止盈:{tp:.0f}(-10点)')
                reasons.append(f'仓位:0.01手(100美金风险) 盈亏比1:1')
                reasons.append(f'💡推动止盈:盈利10点后止损移到进场价(手动操作)')
                reasons.append(f'⚠️破位提醒:如果价格突破{hs["right_shoulder"]}往上走，放弃本轮等下一轮')
                
            else:
                # 头肩顶已出现，但横盘还不够2根 → 观察状态，不发信号
                triggered = True
                signal_mode = 'hs_watching'
                signal = 'waiting'
                reasons.insert(0, f'👀【头肩顶观察】右肩后仅横盘{consol_bars_count}根K线，需≥2根才可做空')
                reasons.append(f'⏳等待更多横盘K线确认后再做空')
                
                # 保存观察状态（不发交易信号）
                if last.get('signal') != 'short':
                    save_last_signal({
                        'time': datetime.datetime.now(datetime.timezone.utc).isoformat(),
                        'signal': 'waiting',
                        'price': price,
                        'mode': 'hs_watching'
                    })
        
        # ========== 做多逻辑（保留原v7快横盘逻辑） ==========
        elif trend_up and is_pre_consolidating and not breakout_up:
            triggered = True
            signal_mode = 'pre_consolidation'
            signal = 'long'
            entry_price = consol_low  # 进场参考价 = 横盘最低价
            sl = entry_price - 10
            tp = entry_price + 10
            reasons.insert(0, f'🔊【快横盘预警】等低位做多')
            reasons.append(f'📌进场参考价:横盘最低价 {entry_price:.0f} (等价格回到{entry_price:.0f}附近再进)')
            reasons.append(f'止损:{sl:.0f}(-10点) 止盈:{tp:.0f}(+10点)')
            reasons.append(f'仓位:0.01手(100美金风险) 盈亏比1:1')
            reasons.append(f'💡推动止盈:盈利10点后止损移到进场价(手动操作)')
            reasons.append(f'⚠️破位提醒:如果价格跌破{consol_low:.0f}往下走，放弃本轮等下一轮')

    # === 备用模式：v6横盘确认 + 价格在边缘（如果提前检测没触发） ===
    elif not triggered and is_consolidating and near_edge:
        triggered = True
        signal_mode = 'scalp'

        if trend_down and edge_type == 'upper' and hs_detected:
            # 备用做空也要有头肩顶
            signal = 'short'
            entry_price = price
            sl = price + 10
            tp = price - 10
            reasons.insert(0, f'🔊【横盘确认】横盘上沿做空(头肩顶)')
            reasons.append(f'止损:{sl:.0f}(+10点) 止盈:{tp:.0f}(-10点)')
            reasons.append(f'仓位:0.01手(100美金风险) 盈亏比1:1')
            reasons.append(f'💡推动止盈:盈利10点后止损移到进场价(手动操作)')

        elif trend_up and edge_type == 'lower':
            signal = 'long'
            entry_price = price
            sl = price - 10
            tp = price + 10
            reasons.insert(0, f'🔊【横盘确认】横盘下沿做多')
            reasons.append(f'止损:{sl:.0f}(-10点) 止盈:{tp:.0f}(+10点)')
            reasons.append(f'仓位:0.01手(100美金风险) 盈亏比1:1')
            reasons.append(f'💡推动止盈:盈利10点后止损移到进场价(手动操作)')

    if triggered and signal != 'waiting':
        save_last_signal({
            'time': datetime.datetime.now(datetime.timezone.utc).isoformat(),
            'signal': signal,
            'price': price,
            'mode': signal_mode,
            'entry_price': entry_price
        })

# ===== 三种提醒逻辑（写入 data.json 供微信bot读取） =====
needs_reminder = ''  # 'duration' = 信号持续超1小时, 'entry' = 价格到进场价附近
last = load_last_signal()
if last.get('signal') in ('short', 'long') and last.get('entry_price') and last.get('entry_price', 0) > 0:
    signal_age = get_signal_age_seconds()
    first_time = last.get('first_time', last.get('time', ''))
    if first_time:
        try:
            signal_total_age = (datetime.datetime.now(datetime.timezone.utc) -
                               datetime.datetime.fromisoformat(first_time)).total_seconds()
        except:
            signal_total_age = 0
    else:
        signal_total_age = 0

    # A：信号持续超过1小时，提醒"信号持续中"
    if signal_total_age > 3600 and not has_reminded('duration'):
        needs_reminder = 'duration'
        mark_reminded('duration')

    # C：价格接近进场参考价（距离<5美金），提醒"进场提醒"
    entry_ref = last.get('entry_price', 0)
    if entry_ref and abs(price - entry_ref) < 5 and not has_reminded('entry'):
        needs_reminder = 'entry'
        mark_reminded('entry')

if skip_event:
    reasons.append(f'⚠️{event_reason}暂停交易')
if in_cooldown:
    # 冷却期间保持上一个信号，不要变回waiting（防止信号闪烁）
    last = load_last_signal()
    if last.get('signal') in ('short', 'long') and last.get('mode') != 'breakout':
        # B：RSI(1h) > 70 时信号降级为"观察"，不再维持
        if rsi_1h > 70:
            signal = 'waiting'
            signal_mode = 'observe'
            reasons.insert(0, f'🔍【信号降级】RSI(1h)={rsi_1h:.0f}过高(>70)，信号转为观察，等RSI回敲再进')
            reasons.append('⏸️等待RSI回敲后再进场')
        else:
            signal = last['signal']
            signal_mode = last.get('mode', '')
            entry_price = last.get('entry_price', 0)
            if signal == 'short':
                sl = entry_price + 10 if entry_price else 0
                tp = entry_price - 10 if entry_price else 0
            elif signal == 'long':
                sl = entry_price - 10 if entry_price else 0
                tp = entry_price + 10 if entry_price else 0
            cooldown_remain = int(900-(datetime.datetime.now(datetime.timezone.utc)-datetime.datetime.fromisoformat(last["time"])).total_seconds())
            reasons.append(f'⏸️信号维持中(冷却{cooldown_remain}s)')
    else:
        reasons.append('⏸️信号冷却中(15min)')

# ===== 回测 =====
bt_result = backtest(k4h, k1d)

print(f'Price={price:.2f} Trend={trend_dir}({trend_strength:.0f}%) RSI4h={rsi_4h:.1f} RSI1h={rsi_1h:.1f} ATR={atr_4h:.0f} Signal={signal}')
print(f'24h={h24_change:+.2f}% PreScore={pre_score}/8 H1stable={h1_stable}({h1_score}/2)')
print(f'PreConsolidation: score={pre_score}/8 is_pre={is_pre_consolidating} breakout_up={breakout_up}')
print(f'Consolidation: {is_consolidating} range={consol_low:.0f}~{consol_high:.0f} edge={edge_type}')
if hs_detected:
    print(f'HeadShoulders: LS={hs_details["left_shoulder"]} Head={hs_details["head"]} RS={hs_details["right_shoulder"]} Neckline={hs_details["neckline"]} BarsSinceRS={hs_details["bars_since_rs"]} ConsolBars={consol_bars_count}')
else:
    print(f'HeadShoulders: not detected (consol_bars={consol_bars_count})')
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
        'needs_reminder': needs_reminder,
        'entry_price': round(entry_price, 2) if entry_price > 0 else 0,
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
            'pullback': is_pre_consolidating,
            'pullback_distance': round((price - ema25_4h) / atr_4h, 2) if atr_4h > 0 else 0,
            'far_from_ema25': abs(price - ema25_4h) / atr_4h > 3 if atr_4h > 0 else False,
            'oversold': rsi_4h < 30,
            'overbought': rsi_4h > 70,
            'pre_consolidating': is_pre_consolidating,
            'pre_score': pre_score,
            'pre_conditions': pre_conditions,
            'h1_stable': h1_stable,
            'h1_score': h1_score,
            'h1_details': h1_details,
            'stopLoss': round(sl, 2) if signal != 'waiting' else 0,
            'takeProfit': round(tp, 2) if signal != 'waiting' else 0,
            'position_size': round(position_size, 2) if signal != 'waiting' else 0,
            'position_pct': round(position_pct, 1) if signal != 'waiting' else 0
        },
        'scalp': {
            'pre_consolidating': is_pre_consolidating,
            'pre_score': pre_score,
            'pre_conditions': pre_conditions,
            'consolidating': is_consolidating,
            'range_high': consol_high,
            'range_low': consol_low,
            'breakout_up': breakout_up,
            'entry_price': round(entry_price, 2) if entry_price > 0 else 0,
            'near_edge': near_edge,
            'edge_type': edge_type,
            'price_position': 'upper' if price > (consol_high + consol_low) / 2 else 'lower' if consol_high > 0 else 'none',
            'stop_loss_points': 10,
            'take_profit_points': 10,
            'trailing_stop': True,
            'head_shoulders': hs_detected,
            'hs_details': hs_details,
            'consol_bars': consol_bars_count
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
        'backtest': bt_result,
        'signal_age': int(get_signal_age_seconds()) if last.get('signal') in ('short', 'long') else 0,
        'needs_reminder': needs_reminder
    },
    'timestamp': int(datetime.datetime.now(datetime.timezone.utc).timestamp() * 1000),
    'source': 'vps-rainyun-v7'
}

out = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data', 'data.json')
with open(out, 'w') as fp:
    json.dump(data, fp, indent=2)
