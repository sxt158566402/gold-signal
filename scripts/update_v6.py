#!/usr/bin/env python3
"""Gold Sniper v6 - 回踩横盘剥头皮策略

核心逻辑：
  1. 日线定方向：找最近18+根K线的盘整区间，破位确认趋势
  2. 回踩横盘检测：价格反弹后，1H连续3根+K线波幅收窄(<15点) = 横盘
  3. 剥头皮入场：横盘区间上沿做空/下沿做多
  4. 止损10点，止盈10点，推动止盈
  5. 只顺趋势方向做单
  6. 多头趋势反过来做（在横盘下沿做多）

v6改进：
  - 核心从EMA回踩改为横盘区间检测
  - 止损止盈改为固定10点（剥头皮模式）
  - 冷却从1小时改为15分钟（剥头皮需要更高频率）
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
        return elapsed < 900  # 15分钟冷却（剥头皮模式）
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

# ===== 趋势方向 =====
trend_down = (trend_dir == '下跌')
trend_up = (trend_dir == '上涨')

# ===== v6核心：回踩横盘检测 =====
is_consolidating, consol_high, consol_low, consol_size, consol_bars, near_edge, edge_type = \
    detect_pullback_consolidation(k1h, closes_1h, trend_dir, price)

# ===== 辅助：三种入场模式判断（保留作为参考） =====
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

# 模式C：回踩EMA25
mode_c = False
mode_c_reason = ''
dist_ema25 = abs(price - ema25_4h) / atr_4h if atr_4h > 0 else 999
if trend_down and dist_ema25 < 1.5:
    mode_c = True
    mode_c_reason = f'模式C:回踩EMA25做空(距{dist_ema25:.1f}ATR)'
elif trend_up and dist_ema25 < 1.5:
    mode_c = True
    mode_c_reason = f'模式C:回踩EMA25做多(距{dist_ema25:.1f}ATR)'

# 1H企稳确认（辅助参考，不再是必须条件）
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

# v6核心：横盘状态
if is_consolidating:
    edge_str = '上沿(做空位)' if edge_type == 'upper' else ('下沿(做多位)' if edge_type == 'lower' else '中间')
    reasons.append(f'🔍回踩横盘✅ 区间{consol_low:.0f}~{consol_high:.0f}({consol_size:.1f}点) {consol_bars}根 价格在{edge_str}')
else:
    reasons.append(f'回踩横盘:未形成(1H波幅未收窄)')

# 辅助模式状态
mode_status = []
if mode_a: mode_status.append('A✅')
if mode_b: mode_status.append('B✅')
if mode_c: mode_status.append('C✅')
if not mode_status: mode_status.append('等待中')
reasons.append(f'辅助模式:{"|".join(mode_status)}')

if mode_a: reasons.append(mode_a_reason)
if mode_b: reasons.append(mode_b_reason)
if mode_c: reasons.append(mode_c_reason)

# 1H企稳状态
if h1_stable:
    reasons.append(f'1H企稳✅({",".join(h1_details)})')
else:
    reasons.append(f'1H未企稳({h1_score}/2)')

reasons.append(f'距EMA7(4h):{dist_ema7:.1f}ATR 距EMA25(4h):{dist_ema25:.1f}ATR')

# === v6信号触发：回踩横盘剥头皮 ===
sl = 0
tp = 0

if can_trade and (trend_down or trend_up):
    triggered = False

    # 核心模式：回踩横盘 + 价格在区间边缘
    if not triggered and is_consolidating and near_edge:
        triggered = True
        signal_mode = 'scalp'

        if trend_down and edge_type == 'upper':
            # 下跌趋势 + 价格在横盘上沿 = 做空
            signal = 'short'
            sl = price + 10  # 止损10点
            tp = price - 10  # 止盈10点
            reasons.insert(0, f'🔊【剥头皮】回踩横盘上沿做空')
            reasons.append(f'止损:{sl:.0f}(+10点) 止盈:{tp:.0f}(-10点)')
            reasons.append(f'仓位:0.01手(100美金风险) 盈亏比1:1')
            reasons.append(f'💡推动止盈:盈利10点后止损移到进场价')

        elif trend_up and edge_type == 'lower':
            # 上涨趋势 + 价格在横盘下沿 = 做多
            signal = 'long'
            sl = price - 10
            tp = price + 10
            reasons.insert(0, f'🔊【剥头皮】回踩横盘下沿做多')
            reasons.append(f'止损:{sl:.0f}(-10点) 止盈:{tp:.0f}(+10点)')
            reasons.append(f'仓位:0.01手(100美金风险) 盈亏比1:1')
            reasons.append(f'💡推动止盈:盈利10点后止损移到进场价')

    # 备用模式A：超卖/超买 + 1H企稳
    if not triggered and mode_a and h1_stable:
        triggered = True
        signal_mode = 'A'
        if trend_down:
            signal = 'short'
            sl = price + 10
            tp = price - 10
            reasons.insert(0, f'🔊【模式A】超卖反弹做空')
        else:
            signal = 'long'
            sl = price - 10
            tp = price + 10
            reasons.insert(0, f'🔊【模式A】超买回调做多')
        reasons.append(f'止损:{sl:.0f} 止盈:{tp:.0f}')
        reasons.append(f'仓位:0.01手(100美金风险) 盈亏比1:1')
        reasons.append(f'💡推动止盈:盈利10点后止损移到进场价')

    # 备用模式B：回踩EMA7 + 1H企稳
    if not triggered and mode_b and h1_stable:
        triggered = True
        signal_mode = 'B'
        if trend_down:
            signal = 'short'
            sl = price + 10
            tp = price - 10
            reasons.insert(0, f'🔊【模式B】回踩EMA7做空')
        else:
            signal = 'long'
            sl = price - 10
            tp = price + 10
            reasons.insert(0, f'🔊【模式B】回踩EMA7做多')
        reasons.append(f'止损:{sl:.0f} 止盈:{tp:.0f}')
        reasons.append(f'仓位:0.01手(100美金风险) 盈亏比1:1')
        reasons.append(f'💡推动止盈:盈利10点后止损移到进场价')

    if triggered:
        save_last_signal({
            'time': datetime.datetime.now(datetime.timezone.utc).isoformat(),
            'signal': signal,
            'price': price,
            'mode': signal_mode
        })

if skip_event:
    reasons.append(f'⚠️{event_reason}暂停交易')
if in_cooldown:
    reasons.append('⏸️信号冷却中(15min)')

# ===== 回测 =====
bt_result = backtest(k4h, k1d)

print(f'Price={price:.2f} Trend={trend_dir}({trend_strength:.0f}%) RSI4h={rsi_4h:.1f} RSI1h={rsi_1h:.1f} ATR={atr_4h:.0f} Signal={signal}')
print(f'24h={h24_change:+.2f}% ModeA={mode_a} ModeB={mode_b} ModeC={mode_c} H1stable={h1_stable}({h1_score}/2)')
print(f'Consolidation: {is_consolidating} range={consol_low:.0f}~{consol_high:.0f}({consol_size:.1f}pts) bars={consol_bars} edge={edge_type}')
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
        'scalp': {
            'consolidating': is_consolidating,
            'range_high': consol_high,
            'range_low': consol_low,
            'range_size': consol_size,
            'bars_in_range': consol_bars,
            'near_edge': near_edge,
            'edge_type': edge_type,
            'price_position': 'upper' if price > (consol_high + consol_low) / 2 else 'lower' if is_consolidating else 'none',
            'stop_loss_points': 10,
            'take_profit_points': 10,
            'trailing_stop': True
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
    'source': 'vps-rainyun-v6'
}

out = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data', 'data.json')
with open(out, 'w') as fp:
    json.dump(data, fp, indent=2)
