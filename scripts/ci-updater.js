const https = require('https');
const http = require('http');
const { execSync } = require('child_process');
const fs = require('fs');
const path = require('path');

const REPO = path.resolve(__dirname, '..');
const DATA_FILE = path.join(REPO, 'data', 'data.json');

function fetch(url) {
  return new Promise((resolve, reject) => {
    const mod = url.startsWith('https') ? https : http;
    mod.get(url, { timeout: 15000 }, (res) => {
      let data = '';
      res.on('data', chunk => data += chunk);
      res.on('end', () => {
        try { resolve(JSON.parse(data)); }
        catch(e) { reject(new Error('JSON parse error')); }
      });
    }).on('error', reject).on('timeout', function() { this.destroy(); reject(new Error('timeout')); });
  });
}

function calcRSI(closes, period = 14) {
  let gains = 0, losses = 0;
  for (let i = closes.length - period; i < closes.length; i++) {
    const d = closes[i] - closes[i - 1];
    if (d > 0) gains += d; else losses -= d;
  }
  return losses > 0 ? 100 - (100 / (1 + gains / losses)) : 50;
}

async function update() {
  try {
    const [ticker, klines] = await Promise.all([
      fetch('https://api1.binance.com/api/v3/ticker/24hr?symbol=PAXGUSDT'),
      fetch('https://api1.binance.com/api/v3/klines?symbol=PAXGUSDT&interval=5m&limit=50')
    ]);
    
    const c = klines.map(k => parseFloat(k[4]));
    const h = klines.map(k => parseFloat(k[2]));
    const l = klines.map(k => parseFloat(k[3]));
    
    const rsi = calcRSI(c);
    const s20 = c.slice(-20);
    const m = s20.reduce((a, b) => a + b) / 20;
    const sd = Math.sqrt(s20.reduce((a, x) => a + (x - m) ** 2, 0) / 20);
    
    const p = parseFloat(ticker.lastPrice);
    const rh = h.slice(-10), rl = l.slice(-10);
    const maxH = Math.max(...rh), minL = Math.min(...rl);
    
    let signal = 'waiting', reason = '監控中';
    if (p > maxH && rsi > 50) { signal = 'long'; reason = '突破近10根K線高點+RSI偏多'; }
    else if (p < minL && rsi < 50) { signal = 'short'; reason = '跌破近10根K線低點+RSI偏空'; }
    
    const data = {
      ticker,
      strategy: {
        signal, price: p, reason,
        indicators: {
          rsi: +rsi.toFixed(2),
          ema7: +(c.slice(-7).reduce((a,b)=>a+b) / 7).toFixed(2),
          ema25: +(c.slice(-25).reduce((a,b)=>a+b) / 25).toFixed(2),
          bbUpper: +(m + 2 * sd).toFixed(2),
          bbMiddle: +m.toFixed(2),
          bbLower: +(m - 2 * sd).toFixed(2)
        }
      },
      timestamp: Date.now()
    };
    
    fs.mkdirSync(path.dirname(DATA_FILE), { recursive: true });
    fs.writeFileSync(DATA_FILE, JSON.stringify(data, null, 2));
    
    // git push
    try {
      process.chdir(REPO);
      execSync('git checkout gh-pages 2>/dev/null', { timeout: 5000 });
      execSync('git add data/data.json', { timeout: 5000 });
      try {
        execSync('git diff --cached --quiet', { timeout: 5000 });
        console.log(new Date().toISOString(), 'No changes');
      } catch(e) {
        execSync(`git commit -m "update ${new Date().toISOString().slice(11,19)}"`, { timeout: 5000 });
        try {
          execSync('git push origin gh-pages', { timeout: 30000 });
        } catch(pushErr) {
          execSync('git pull --rebase origin gh-pages', { timeout: 15000 });
          execSync('git push origin gh-pages', { timeout: 30000 });
        }
        console.log(new Date().toISOString(), `Pushed! Price: $${p} RSI: ${rsi.toFixed(1)}`);
      }
      execSync('git checkout main 2>/dev/null', { timeout: 5000 });
    } catch(e) {
      console.error('Git error:', e.message);
    }
  } catch(e) {
    console.error(new Date().toISOString(), 'Error:', e.message);
  }
}

// 立即更新一次，然后每 55 秒
update();
setInterval(update, 55000);
