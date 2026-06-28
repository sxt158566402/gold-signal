const http = require('http');
const https = require('https');
const fs = require('fs');
const path = require('path');
const url = require('url');

const PORT = 10888;

// ===== 幣安 API 代理 =====
function fetchBinance(symbol, endpoint) {
  return new Promise((resolve, reject) => {
    const reqUrl = `https://api.binance.com${endpoint}?symbol=${symbol}`;
    https.get(reqUrl, { timeout: 8000 }, (res) => {
      let data = '';
      res.on('data', c => data += c);
      res.on('end', () => {
        try { resolve(JSON.parse(data)); } catch(e) { reject(e); }
      });
    }).on('error', reject).on('timeout', function() { this.destroy(); reject(new Error('timeout')); });
  });
}

// ===== 策略引擎 =====
let priceHistory = [];
let lastSignal = null;
let lastSignalTime = 0;

function calcRSI(closes, period) {
  if (closes.length < period + 1) return 50;
  let gains = 0, losses = 0;
  for (let i = closes.length - period; i < closes.length; i++) {
    const diff = closes[i] - closes[i-1];
    if (diff > 0) gains += diff; else losses -= diff;
  }
  if (losses === 0) return 100;
  const rs = gains / losses;
  return 100 - (100 / (1 + rs));
}

function calcEMA(closes, period) {
  if (closes.length < period) return closes[closes.length - 1] || 0;
  let ema = closes.slice(0, period).reduce((a,b) => a+b, 0) / period;
  const k = 2 / (period + 1);
  for (let i = period; i < closes.length; i++) {
    ema = closes[i] * k + ema * (1 - k);
  }
  return ema;
}

function calcBB(closes, period) {
  if (closes.length < period) return { upper: 0, middle: 0, lower: 0 };
  const slice = closes.slice(-period);
  const middle = slice.reduce((a,b) => a+b, 0) / period;
  const variance = slice.reduce((a,b) => a + Math.pow(b - middle, 2), 0) / period;
  const std = Math.sqrt(variance);
  return { upper: middle + 2 * std, middle, lower: middle - 2 * std };
}

function runStrategy(klines) {
  if (!klines || klines.length < 30) return { signal: null, error: 'K線不足' };
  
  const closes = klines.map(k => k.close);
  const highs = klines.map(k => k.high);
  const lows = klines.map(k => k.low);
  const currentPrice = closes[closes.length - 1];
  
  // 技術指標
  const rsi = calcRSI(closes, 14);
  const ema7 = calcEMA(closes, 7);
  const ema25 = calcEMA(closes, 25);
  const bb = calcBB(closes, 20);
  
  // 近期波動（最近3根K線）
  const recentHigh = Math.max(...highs.slice(-3));
  const recentLow = Math.min(...lows.slice(-3));
  const priceChange = recentHigh - recentLow;
  
  // 條件判斷
  const isBigMoveUp = priceChange > 8;   // 漲超過8美金
  const isBigMoveDown = priceChange > 8;
  const isStable = Math.abs(currentPrice - (recentHigh + recentLow) / 2) < 3; // 價格在中間
  
  let signal = null;
  let reason = '';
  
  // 做空條件：大跌後企穩
  if (isBigMoveDown && isStable && rsi < 40 && currentPrice > bb.lower) {
    signal = 'short';
    reason = `大跌${priceChange.toFixed(1)}後企穩 | RSI=${rsi.toFixed(1)}`;
  }
  // 做多條件：大漲後企穩
  else if (isBigMoveUp && isStable && rsi > 60 && currentPrice < bb.upper) {
    signal = 'long';
    reason = `大漲${priceChange.toFixed(1)}後企穩 | RSI=${rsi.toFixed(1)}`;
  }
  
  // 限時（5分鐘內同一方向不重複）
  if (signal && lastSignal === signal && Date.now() - lastSignalTime < 300000) {
    signal = null;
    reason = '5分鐘內已提示過';
  }
  
  if (signal) {
    lastSignal = signal;
    lastSignalTime = Date.now();
  }
  
  return {
    signal,
    reason,
    price: currentPrice,
    indicators: { rsi, ema7, ema25, bbUpper: bb.upper, bbMiddle: bb.middle, bbLower: bb.lower },
    priceRange: { recentHigh, recentLow, change: priceChange }
  };
}

// ===== HTTP 伺服器 =====
const server = http.createServer(async (req, res) => {
  const parsedUrl = url.parse(req.url, true);
  const pathname = parsedUrl.pathname;
  
  // CORS
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'GET, POST, OPTIONS');
  
  // API: 獲取完整數據
  if (pathname === '/api/data') {
    try {
      const [ticker, klines] = await Promise.all([
        fetchBinance('PAXGUSDT', '/api/v3/ticker/24hr'),
        fetchBinance('PAXGUSDT', '/api/v3/klines')
      ]);
      
      const strategy = runStrategy(klines.map(k => ({
        open: +k[1], high: +k[2], low: +k[3], close: +k[4], volume: +k[5]
      })));
      
      res.writeHead(200, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({
        ticker: {
          lastPrice: ticker.lastPrice,
          priceChange: ticker.priceChange,
          priceChangePercent: ticker.priceChangePercent,
          highPrice: ticker.highPrice,
          lowPrice: ticker.lowPrice,
          volume: ticker.volume
        },
        strategy,
        timestamp: Date.now()
      }));
    } catch(e) {
      res.writeHead(500, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ error: e.message }));
    }
    return;
  }
  
  // 靜態文件
  let filePath;
  if (pathname === '/' || pathname === '/index.html') {
    filePath = path.join(__dirname, 'public', 'index.html');
  } else {
    filePath = path.join(__dirname, 'public', pathname);
  }
  
  const ext = path.extname(filePath);
  const mimeTypes = { '.html': 'text/html', '.css': 'text/css', '.js': 'application/javascript' };
  
  try {
    const content = fs.readFileSync(filePath);
    res.writeHead(200, { 'Content-Type': mimeTypes[ext] || 'text/plain' });
    res.end(content);
  } catch(e) {
    res.writeHead(404);
    res.end('Not found');
  }
});

server.listen(PORT, '0.0.0.0', () => {
  console.log(`GoldSniper server running on port ${PORT}`);
});
