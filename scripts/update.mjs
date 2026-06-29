const token = process.env.GH_TOKEN;
if (!token) { console.error('No token'); process.exit(1); }

const [ticker, klines] = await Promise.all([
  fetch('https://api.binance.com/api/v3/ticker/24hr?symbol=PAXGUSDT').then(r=>r.json()),
  fetch('https://api.binance.com/api/v3/klines?symbol=PAXGUSDT&interval=5m&limit=50').then(r=>r.json())
]);

const closes = klines.map(k => parseFloat(k[4]));
console.log(`Got ${closes.length} closes, price=${closes[closes.length-1]}`);

// RSI
let gains = 0, losses = 0;
for (let i = closes.length - 14; i < closes.length; i++) {
  const d = closes[i] - closes[i-1];
  if (d > 0) gains += d; else losses -= d;
}
const rsi = losses === 0 ? 100 : 100 - 100/(1 + gains/losses);

// EMA7
let ema7 = closes[closes.length-1];
for (const c of closes.slice(-7)) ema7 = c * 2/8 + ema7 * 6/8;

// EMA25
let ema25 = closes[closes.length-1];
for (const c of closes.slice(-25)) ema25 = c * 2/26 + ema25 * 24/26;

// Bollinger Bands
const s20 = closes.slice(-20);
const sma20 = s20.reduce((a,b)=>a+b,0)/20;
const std20 = Math.sqrt(s20.reduce((a,c)=>a+(c-sma20)**2,0)/20);

// 5min move
const lb = Math.min(5, closes.length-1);
const cpct = (closes[closes.length-1]-closes[closes.length-lb-1])/closes[closes.length-lb-1]*100;
let mt = null, st = false;
if (cpct > 0.15) mt = 'big_up';
else if (cpct < -0.15) mt = 'big_down';
if (mt) {
  const r3 = closes.slice(-3);
  st = (Math.max(...r3)-Math.min(...r3))/r3.reduce((a,b)=>a+b,0)*300 < 0.5;
}

let sig = 'waiting', rsn = 'monitoring';
if (mt==='big_up'&&(st||rsi>55)) { sig='short'; rsn='5min up '+cpct.toFixed(2)+'% RSI='+rsi.toFixed(1); }
else if (mt==='big_down'&&(st||rsi<45)) { sig='long'; rsn='5min down '+cpct.toFixed(2)+'% RSI='+rsi.toFixed(1); }
else if (rsi>75) { sig='short'; rsn='RSI overbought '+rsi.toFixed(1); }
else if (rsi<25) { sig='long'; rsn='RSI oversold '+rsi.toFixed(1); }

console.log(`RSI=${rsi.toFixed(2)} EMA7=${ema7.toFixed(2)} EMA25=${ema25.toFixed(2)} Signal=${sig}`);

const data = {
  ticker, klines,
  strategy: {
    signal: sig, price: ticker.lastPrice, reason: rsn,
    indicators: {
      rsi: Math.round(rsi*100)/100,
      ema7: Math.round(ema7*100)/100,
      ema25: Math.round(ema25*100)/100,
      bbUpper: Math.round((sma20+2*std20)*100)/100,
      bbMiddle: Math.round(sma20*100)/100,
      bbLower: Math.round((sma20-2*std20)*100)/100
    }
  },
  timestamp: Date.now()
};

const content = Buffer.from(JSON.stringify(data)).toString('base64');
const resp = await fetch('https://api.github.com/repos/sxt158566402/gold-signal/contents/data/data.json?ref=gh-pages', {
  headers: { 'Authorization': 'token '+token, 'Accept': 'application/vnd.github.v3+json' }
});
const { sha } = await resp.json();

const put = await fetch('https://api.github.com/repos/sxt158566402/gold-signal/contents/data/data.json', {
  method: 'PUT',
  headers: { 'Authorization': 'token '+token, 'Content-Type': 'application/json', 'Accept': 'application/vnd.github.v3+json' },
  body: JSON.stringify({ message: 'update', content, sha, branch: 'gh-pages' })
});
const result = await put.json();
console.log(result.content ? 'SUCCESS' : 'FAIL: ' + JSON.stringify(result).slice(0,200));
