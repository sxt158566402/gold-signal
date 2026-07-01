import re

with open('/app/workspace/gold-signal/scripts/update_v5.py', 'r') as f:
    content = f.read()

# 找到回测函数，替换成跟实际策略一致的版本
old_backtest_start = "# ===== 回测引擎（v5：三种模式）====="
old_backtest_end = "# ===== 获取数据 ====="

# 提取旧的回测函数
idx_start = content.find(old_backtest_start)
idx_end = content.find(old_backtest_end)

if idx_start < 0 or idx_end < 0:
    print("ERROR: cannot find backtest function boundaries")
    exit(1)

# 新的回测引擎 - 跟实际策略一致
new_backtest = '''# ===== 回测引擎（v5：跟实际策略一致）=====
def backtest(klines_4h, klines_1d, initial_capital=10000):
    """回测v5策略历史表现 - 使用日线趋势+三种模式+冷却"""
    if len(klines_4h) < 60 or len(klines_1d) < 20:
        return {'total': 0, 'wins': 0, 'win_rate': 0, 'note': '数据不足'}
    
    closes_4h = [float(k[4]) for k in klines_4h]
    closes_1d = [float(k[4]) for k in klines_1d]
    trades = []
    last_signal_i = -999
    cooldown = 6  # 24小时冷却
    
    for i in range(50, len(closes_4h) - 6):
        # 冷却检查
        if i - last_signal_i < cooldown:
            continue
        
        price_i = closes_4h[i]
        window_closes = closes_4h[:i+1]
        window_kl = klines_4h[:i+1]
        
        if len(window_closes) < 50:
            continue
        
        ema7 = calc_ema(window_closes, 7)
        ema25 = calc_ema(window_closes, 25)
        ema50 = calc_ema(window_closes, 50)
        atr = calc_atr(window_kl, 14)
        rsi = calc_rsi(window_closes, 14)
        
        if atr == 0:
            continue
        
        # 日线趋势判断
        current_ts = int(klines_4h[i][0]) // 1000
        k1d_slice = [k for k in klines_1d if int(k[0])//1000 <= current_ts]
        if len(k1d_slice) < 20:
            continue
        closes_1d_slice = [float(k[4]) for k in k1d_slice]
        trend_dir = judge_daily_trend(closes_1d_slice, price_i)
        
        if trend_dir == '无趋势':
            continue
        
        trend_down = (trend_dir == '下跌')
        trend_up = (trend_dir == '上涨')
        
        signal = None
        
        # 模式A：超卖反弹做空(RSI<10) / 超买回调做多(RSI>90)
        if trend_down and rsi < 10:
            signal = 'short'
        elif trend_up and rsi > 90:
            signal = 'long'
        
        # 模式B：回踩EMA7
        if signal is None:
            dist_ema7 = abs(price_i - ema7) / atr
            if trend_down and dist_ema7 < 1.0 and price_i < ema25:
                signal = 'short'
            elif trend_up and dist_ema7 < 1.0 and price_i > ema25:
                signal = 'long'
        
        # 模式C：回踩EMA25
        if signal is None:
            dist_ema25 = abs(price_i - ema25) / atr
            if trend_down and dist_ema25 < 1.5:
                signal = 'short'
            elif trend_up and dist_ema25 < 1.5:
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
        last_signal_i = i
    
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

'''

# 替换
new_content = content[:idx_start] + new_backtest + content[idx_end:]

# 同时修复 k1d 的排序问题 - 新策略代码里用了 reverse() 但 Bitget 需要 sort
# 找到数据获取部分
old_data = """k1d = fetch('https://api.bitget.com/api/v2/spot/market/candles?symbol=PAXGUSDT&granularity=1day&limit=60')['data']
k1d.reverse()
closes_1d = [float(k[4]) for k in k1d]
closes_1d[-1] = price  # 实时价格替换未收盘日线"""

new_data = """k1d = fetch('https://api.bitget.com/api/v2/spot/market/candles?symbol=PAXGUSDT&granularity=1day&limit=60')['data']
k1d.sort(key=lambda x: int(x[0]))
closes_1d = [float(k[4]) for k in k1d]
closes_1d[-1] = price  # 实时价格替换未收盘日线"""

new_content = new_content.replace(old_data, new_data)

# 4H 和 1H 也改 sort
old_4h = """k4h = fetch('https://api.bitget.com/api/v2/spot/market/candles?symbol=PAXGUSDT&granularity=4h&limit=200')['data']
k4h.reverse()"""
new_4h = """k4h = fetch('https://api.bitget.com/api/v2/spot/market/candles?symbol=PAXGUSDT&granularity=4h&limit=200')['data']
k4h.sort(key=lambda x: int(x[0]))"""
new_content = new_content.replace(old_4h, new_4h)

old_1h = """k1h = fetch('https://api.bitget.com/api/v2/spot/market/candles?symbol=PAXGUSDT&granularity=1h&limit=100')['data']
k1h.reverse()"""
new_1h = """k1h = fetch('https://api.bitget.com/api/v2/spot/market/candles?symbol=PAXGUSDT&granularity=1h&limit=100')['data']
k1h.sort(key=lambda x: int(x[0]))"""
new_content = new_content.replace(old_1h, new_1h)

with open('/app/workspace/gold-signal/scripts/update_v5.py', 'w') as f:
    f.write(new_content)

print("OK - backtest engine updated + sort fixed")
