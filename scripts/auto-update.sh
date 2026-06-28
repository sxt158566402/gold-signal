#!/bin/bash
cd /app/workspace/gold-signal

while true; do
  # 获取数据
  python3 -c "
import json, urllib.request, datetime, os
  
try:
    t = json.loads(urllib.request.urlopen('https://api1.binance.com/api/v3/ticker/24hr?symbol=PAXGUSDT', timeout=10).read())
    k = json.loads(urllib.request.urlopen('https://api1.binance.com/api/v3/klines?symbol=PAXGUSDT&interval=5m&limit=50', timeout=10).read())
except Exception as e:
    print(f'API error: {e}')
    exit(1)
  
c = [float(x[4]) for x in k]
h = [float(x[2]) for x in k]
l = [float(x[3]) for x in k]
  
g, ls2 = 0, 0
for i in range(len(c)-14, len(c)):
    d = c[i] - c[i-1]
    if d > 0: g += d
    else: ls2 -= d
r = 100 - (100/(1+g/ls2)) if ls2 > 0 else 50
  
s2 = c[-20:]
m = sum(s2)/20
sd = (sum((x-m)**2 for x in s2)/20)**0.5
  
p = float(t['lastPrice'])
rh, rl = h[-10:], l[-10:]
sig, why = 'waiting', '監控中'
if p > max(rh) and r > 50: sig, why = 'long', '突破近10根K線高點+RSI偏多'
elif p < min(rl) and r < 50: sig, why = 'short', '跌破近10根K線低點+RSI偏空'
  
data = {'ticker': t, 'strategy': {'signal': sig, 'price': p, 'reason': why, 'indicators': {'rsi': round(r,2), 'ema7': round(sum(c[-7:])/7,2), 'ema25': round(sum(c[-25:])/25,2), 'bbUpper': round(m+2*sd,2), 'bbMiddle': round(m,2), 'bbLower': round(m-2*sd,2)}}, 'timestamp': int(datetime.datetime.now(datetime.timezone.utc).timestamp()*1000)}
  
os.makedirs('data', exist_ok=True)
with open('data/data.json', 'w') as f: json.dump(data, f, indent=2)
print(f'OK: \${p} RSI={round(r,2)}')
"
  
  if [ $? -eq 0 ]; then
    git checkout gh-pages 2>/dev/null
    git add data/data.json
    if ! git diff --cached --quiet; then
      git commit -m "update $(date -u +%H:%M:%S)" && git push origin gh-pages
      echo "Pushed to GitHub Pages"
    fi
    git checkout main 2>/dev/null
  fi
  
  sleep 55
done
