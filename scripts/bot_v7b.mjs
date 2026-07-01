import crypto from "node:crypto";
import { mkdirSync, readFileSync, writeFileSync, existsSync, appendFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import http from "node:http";

// === Paths ===
const APP_DIR = dirname(fileURLToPath(import.meta.url));
const STATE_DIR = join(APP_DIR, "state");
mkdirSync(STATE_DIR, { recursive: true });

const ACCOUNT_FILE = join(STATE_DIR, "account.json");
const UPDATES_BUF_FILE = join(STATE_DIR, "get-updates-buf.txt");
const LOG_FILE = join(STATE_DIR, "bot.log");
const SUBSCRIBERS_FILE = join(STATE_DIR, "subscribers.json");
const SIGNAL_STATE_FILE = join(STATE_DIR, "last-signal.json");

function log(msg) {
  const line = `[${new Date().toISOString()}] ${msg}\n`;
  appendFileSync(LOG_FILE, line);
  process.stdout.write(line);
}

// === iLink Config ===
const ILINK_APP_ID = "bot";
const OPENCLAW_WEIXIN_VERSION = "2.4.1";
const [major, minor, patch] = OPENCLAW_WEIXIN_VERSION.split(".").map(Number);
const ILINK_APP_CLIENT_VERSION = ((major & 255) << 16) | ((minor & 255) << 8) | (patch & 255);

function randomWechatUin() {
  return Buffer.from(String(crypto.randomBytes(4).readUInt32BE(0)), "utf-8").toString("base64");
}

function commonHeaders() {
  return {
    "iLink-App-Id": ILINK_APP_ID,
    "iLink-App-ClientVersion": String(ILINK_APP_CLIENT_VERSION),
  };
}

function postHeaders(body, token) {
  return {
    "Content-Type": "application/json",
    AuthorizationType: "ilink_bot_token",
    "Content-Length": String(Buffer.byteLength(body, "utf-8")),
    "X-WECHAT-UIN": randomWechatUin(),
    ...commonHeaders(),
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  };
}

function buildBaseInfo() {
  return {
    channel_version: OPENCLAW_WEIXIN_VERSION,
    bot_agent: "GoldSignalBot/2.0.0",
  };
}

// === Subscribers ===
function loadSubscribers() {
  if (existsSync(SUBSCRIBERS_FILE)) {
    try { return JSON.parse(readFileSync(SUBSCRIBERS_FILE, "utf-8")); } catch (e) { return {}; }
  }
  return {};
}

function saveSubscribers(subs) {
  writeFileSync(SUBSCRIBERS_FILE, JSON.stringify(subs, null, 2));
}

function addSubscriber(wechatId, email) {
  const subs = loadSubscribers();
  subs[wechatId] = { email, addedAt: Date.now() };
  saveSubscribers(subs);
  return subs;
}

// === QR Login ===
let login = {
  sessionKey: crypto.randomUUID(),
  qrcode: null,
  qrcodeUrl: null,
  startedAt: null,
  currentApiBaseUrl: "https://ilinkai.weixin.qq.com",
  pendingVerifyCode: null,
  botToken: null,
  accountId: null,
  baseUrl: null,
  userId: null,
};

let status = "none";

async function startQr() {
  const body = JSON.stringify({ local_token_list: [] });
  const res = await fetch("https://ilinkai.weixin.qq.com/ilink/bot/get_bot_qrcode?bot_type=3", {
    method: "POST",
    headers: postHeaders(body),
    body,
  });
  const text = await res.text();
  if (!res.ok) throw new Error(`QR HTTP ${res.status}: ${text}`);
  const qr = JSON.parse(text);
  login.sessionKey = crypto.randomUUID();
  login.qrcode = qr.qrcode;
  login.qrcodeUrl = qr.qrcode_img_content;
  login.startedAt = Date.now();
  login.currentApiBaseUrl = "https://ilinkai.weixin.qq.com";
  login.pendingVerifyCode = null;
  status = "wait";
  log(`QR generated: ${qr.qrcode_img_content}`);
  return login.qrcodeUrl;
}

async function pollQrStatus() {
  let endpoint = `/ilink/bot/get_qrcode_status?qrcode=${encodeURIComponent(login.qrcode)}`;
  if (login.pendingVerifyCode) endpoint += `&verify_code=${encodeURIComponent(login.pendingVerifyCode)}`;
  const res = await fetch(`${login.currentApiBaseUrl}${endpoint}`, { headers: commonHeaders() });
  const text = await res.text();
  if (!res.ok) throw new Error(`status HTTP ${res.status}: ${text}`);
  const st = JSON.parse(text);
  log(`Status poll: ${st.status}`);

  if (st.status === "scaned_but_redirect" && st.redirect_host) {
    login.currentApiBaseUrl = `https://${st.redirect_host}`;
  }
  if (st.status === "confirmed") {
    if (!st.ilink_bot_id) throw new Error(`confirmed without ilink_bot_id: ${text}`);
    login.botToken = st.bot_token;
    login.accountId = st.ilink_bot_id;
    login.baseUrl = st.baseurl || login.currentApiBaseUrl;
    login.userId = st.ilink_user_id;
    status = "confirmed";
    writeFileSync(ACCOUNT_FILE, JSON.stringify({
      accountId: login.accountId,
      token: login.botToken,
      baseUrl: login.baseUrl,
      userId: login.userId,
      savedAt: Date.now(),
    }, null, 2));
    log(`Login confirmed! Account: ${login.accountId}`);
  } else if (st.status === "need_verifycode") {
    status = "need_verifycode";
  } else if (st.status === "expired") {
    status = "expired";
  } else {
    status = st.status || "wait";
  }
  return st;
}

// === Gold Price ===
async function goldPrice() {
  try {
    const res = await fetch("https://api.binance.com/api/v3/ticker/price?symbol=PAXGUSDT");
    if (res.ok) {
      const d = await res.json();
      return { price: parseFloat(d.price), source: "Binance-PAXG" };
    }
  } catch (e) {}
  try {
    const res = await fetch("https://api.gold-api.com/price/XAU");
    if (res.ok) {
      const d = await res.json();
      return { price: d.price, source: "Gold-API" };
    }
  } catch (e) {}
  throw new Error("所有金价接口均不可用");
}

// === Fetch Signal Data (改进：直接读本地文件，不走HTTP) ===
const GOLD_DATA_FILE = "/opt/gold-signal/data/data.json";

async function fetchSignalData() {
  try {
    const raw = readFileSync(GOLD_DATA_FILE, "utf-8");
    return JSON.parse(raw);
  } catch (e) {
    log(`Failed to read signal data file: ${e.message}`);
    return null;
  }
}

// === Send Message ===
function clientId() {
  return `gold-signal-${Date.now()}-${crypto.randomBytes(4).toString("hex")}`;
}

async function sendText(toUserId, text, contextToken) {
  const account = JSON.parse(readFileSync(ACCOUNT_FILE, "utf-8"));
  const body = JSON.stringify({
    msg: {
      from_user_id: "",
      to_user_id: toUserId,
      client_id: clientId(),
      message_type: 2,
      message_state: 2,
      item_list: [{ type: 1, text_item: { text } }],
      ...(contextToken ? { context_token: contextToken } : {}),
    },
    base_info: buildBaseInfo(),
  });
  const res = await fetch(`${account.baseUrl}/ilink/bot/sendmessage`, {
    method: "POST",
    headers: postHeaders(body, account.token),
    body,
  });
  const raw = await res.text();
  if (!res.ok) throw new Error(`sendmessage HTTP ${res.status}: ${raw}`);
  return raw ? JSON.parse(raw) : {};
}

// === Broadcast to all subscribers ===
async function broadcastToSubscribers(text) {
  const subs = loadSubscribers();
  const ids = Object.keys(subs);
  if (ids.length === 0) {
    log("No subscribers to broadcast to");
    return;
  }
  log(`Broadcasting to ${ids.length} subscribers...`);
  for (const wechatId of ids) {
    try {
      await sendText(wechatId, text);
      log(`Sent to ${subs[wechatId].email || wechatId}`);
    } catch (e) {
      log(`Failed to send to ${wechatId}: ${e.message}`);
    }
  }
}

// === Signal Monitor — 每30秒检查信号变化 ===
let lastSignal = null;

async function checkSignal() {
  try {
    if (existsSync(SIGNAL_STATE_FILE)) {
      try { lastSignal = JSON.parse(readFileSync(SIGNAL_STATE_FILE, "utf-8")); } catch (e) {}
    }

    const data = await fetchSignalData();
    if (!data || !data.strategy) return;

    const currentSignal = data.strategy.signal;
    const price = data.strategy.price;
    const reason = data.strategy.reason || "";
    const h4 = data.strategy.h4 || {};
    const rsi = h4.rsi || data.strategy.indicators?.rsi || 0;
    const trend = h4.trend || "";
    const stopLoss = h4.stopLoss || 0;
    const takeProfit = h4.takeProfit || 0;
    const positionSize = h4.position_size || 0;
    const positionPct = h4.position_pct || 0;

    // 只在信号变化时推送
    if (lastSignal && lastSignal.signal === currentSignal) {
      // 信号没变，但检查是否需要发提醒
      const needsReminder = data.strategy.needs_reminder || '';
      const signalAge = data.strategy.signal_age || 0;
      const entryPrice = data.strategy.scalp?.entry_price || data.strategy.entry_price || 0;
      
      if (needsReminder === 'duration' && (lastSignal.signal === 'short' || lastSignal.signal === 'long')) {
        // A：信号持续超过1小时
        const hours = Math.floor(signalAge / 3600);
        const mins = Math.floor((signalAge % 3600) / 60);
        const dir = lastSignal.signal === 'short' ? '做空' : '做多';
        const msg = `⏰ 信号持续提醒\n\n📊 当前信号: ${dir}\n⏱️ 已持续: ${hours}小时${mins}分钟\n💰 当前价: $${price}\n📌 进场参考价: $${entryPrice}\n\n💡 信号已持续较长时间，请注意:\n- 如果已进场，关注是否触及止盈/止损\n- 如果未进场，可能趋势已变化\n- 破位则放弃本轮`;
        await broadcastToSubscribers(msg);
        log(`REMINDER: duration (${hours}h${mins}m) signal=${lastSignal.signal}`);
      } else if (needsReminder === 'entry' && (lastSignal.signal === 'short' || lastSignal.signal === 'long')) {
        // C：价格接近进场参考价
        const dir = lastSignal.signal === 'short' ? '做空' : '做多';
        const dist = Math.abs(price - entryPrice).toFixed(1);
        const sl = data.strategy.h4?.stopLoss || 0;
        const tp = data.strategy.h4?.takeProfit || 0;
        const msg = `🎯 进场提醒！\n\n📊 当前信号: ${dir}\n💰 当前价: $${price}\n📌 进场参考价: $${entryPrice}\n📏 距离进场价: ${dist}点\n\n🛑 止损: $${sl}\n🎯 止盈: $${tp}\n\n💡 价格已接近进场参考价，可考虑进场\n💡 进场后盈利10点移止损到进场价`;
        await broadcastToSubscribers(msg);
        log(`REMINDER: entry price=$${price} entry=$${entryPrice} dist=${dist}`);
      }
      return;
    }

    // 首次启动不推送，只记录
    if (!lastSignal) {
      lastSignal = { signal: currentSignal, price };
      writeFileSync(SIGNAL_STATE_FILE, JSON.stringify(lastSignal));
      log(`Signal monitor started: ${currentSignal} @ $${price}`);
      return;
    }

    // 信号变了！推送通知
    if (currentSignal === "long") {
      const entryPrice = data.strategy.entry_price || price;
      const preScore = data.strategy.scalp?.pre_score || 0;
      const rangeLow = data.strategy.scalp?.range_low || 0;
      let msg = `🟢 做多信号！\n\n📊 当前价: $${price}\n📌 进场参考价: $${entryPrice} (横盘最低价)\n📈 趋势: ${trend}\n📉 RSI(4h): ${rsi}\n🔍 快横盘评分: ${preScore}/8\n💰 仓位: ${positionSize}手 (${positionPct}%)\n🛑 止损: $${stopLoss} (-10点)\n🎯 止盈: $${takeProfit} (+10点)\n\n💡 等价格回到${entryPrice}附近再进场做多\n💡 盈利10点后止损移到进场价\n\n⚠️ 破位${rangeLow}往下走则放弃本轮`;
      await broadcastToSubscribers(msg);
      log(`SIGNAL: LONG @ $${price} entry=$${entryPrice}`);
    } else if (currentSignal === "short") {
      const entryPrice = data.strategy.entry_price || price;
      const preScore = data.strategy.scalp?.pre_score || 0;
      const rangeHigh = data.strategy.scalp?.range_high || 0;
      let msg = `🔴 做空信号！\n\n📊 当前价: $${price}\n📌 进场参考价: $${entryPrice} (横盘最高价)\n📉 趋势: ${trend}\n📈 RSI(4h): ${rsi}\n🔍 快横盘评分: ${preScore}/8\n💰 仓位: ${positionSize}手 (${positionPct}%)\n🛑 止损: $${stopLoss} (+10点)\n🎯 止盈: $${takeProfit} (-10点)\n\n💡 等价格回到${entryPrice}附近再进场做空\n💡 盈利10点后止损移到进场价\n\n⚠️ 破位${rangeHigh}往上走则放弃本轮`;
      await broadcastToSubscribers(msg);
      log(`SIGNAL: SHORT @ $${price} entry=$${entryPrice}`);
    } else if (currentSignal === "waiting" && (lastSignal.signal === "long" || lastSignal.signal === "short")) {
      const msg = `⏸️ 信号已结束，回到监控中\n\n📊 当前价: $${price}\n📉 趋势: ${trend}\n💡 等待下一个信号...`;
      await broadcastToSubscribers(msg);
      log(`SIGNAL: back to waiting @ $${price}`);
    } else if (currentSignal === lastSignal.signal && currentSignal !== "waiting") {
      // 信号维持不变，不重复推送
      return;
    }

    lastSignal = { signal: currentSignal, price, updatedAt: Date.now() };
    writeFileSync(SIGNAL_STATE_FILE, JSON.stringify(lastSignal));

  } catch (e) {
    log(`Signal check error: ${e.message}`);
  }
}

// === Get Updates (Long Poll) with auto-reconnect ===
let getUpdatesBuf = "";

async function getUpdates() {
  const account = JSON.parse(readFileSync(ACCOUNT_FILE, "utf-8"));
  const body = JSON.stringify({
    get_updates_buf: getUpdatesBuf,
    base_info: buildBaseInfo(),
  });
  const res = await fetch(`${account.baseUrl}/ilink/bot/getupdates`, {
    method: "POST",
    headers: postHeaders(body, account.token),
    body,
  });
  const text = await res.text();
  if (!res.ok) throw new Error(`getupdates HTTP ${res.status}: ${text}`);
  const data = JSON.parse(text);
  if (data.ret && data.ret !== 0) throw new Error(`getupdates ret=${data.ret} err=${data.errmsg || ""}`);
  if (data.get_updates_buf) {
    getUpdatesBuf = data.get_updates_buf;
    writeFileSync(UPDATES_BUF_FILE, getUpdatesBuf);
  }
  return data.msgs || [];
}

function textFromMsg(msg) {
  for (const item of msg.item_list || []) {
    if (item.type === 1 && item.text_item?.text != null) return String(item.text_item.text).trim();
    if (item.type === 3 && item.voice_item?.text) return String(item.voice_item.text).trim();
  }
  return "";
}

// === Handle Commands ===
async function handleMessage(msg) {
  const text = textFromMsg(msg);
  const from = msg.from_user_id;
  if (!from || !text) return;

  log(`Received from ${from}: ${text}`);

  if (text === "/price" || text === "金价" || text === "价格") {
    try {
      const { price, source } = await goldPrice();
      await sendText(from, `📊 当前金价: $${price.toFixed(2)}\n数据来源: ${source}`, msg.context_token);
    } catch (e) {
      await sendText(from, `❌ 获取金价失败: ${e.message}`, msg.context_token);
    }

  } else if (text === "/signal" || text === "信号") {
    try {
      const data = await fetchSignalData();
      if (data && data.strategy) {
        const s = data.strategy;
        const h4 = s.h4 || {};
        let msg = `📊 当前信号状态\n\n信号: ${s.signal === 'long' ? '🟢做多' : s.signal === 'short' ? '🔴做空' : '⏳等待中'}\n价格: $${s.price}\n趋势: ${h4.trend || '未知'}\nRSI(4h): ${h4.rsi || 'N/A'}\n距EMA25: ${(h4.pullback_distance || 0).toFixed(1)} ATR\n横盘: ${h4.oscillating ? '✅确认' : '❌未确认'} (${h4.osc_score || 0}/4)`;
        if (data.strategy.backtest) {
          msg += `\n\n📋 回测: ${data.strategy.backtest.note || ''}`;
        }
        await sendText(from, msg, msg.context_token);
      } else {
        await sendText(from, `❌ 获取信号数据失败`, msg.context_token);
      }
    } catch (e) {
      await sendText(from, `❌ 获取信号失败: ${e.message}`, msg.context_token);
    }

  } else if (text === "/help" || text === "帮助") {
    await sendText(from, `📢 ARK智能AI乾金策 - 微信信号机器人\n\n指令:\n/price 或 金价 - 查看当前金价\n/signal 或 信号 - 查看当前策略信号\n/register <邮箱> - 注册接收信号通知\n/status - 查看机器人状态\n/help 或 帮助 - 显示此帮助\n\n⚠️ 注册后，出现做多/做空信号时会自动通知你！`, msg.context_token);

  } else if (text === "status" || text === "/status") {
    const subs = loadSubscribers();
    const subCount = Object.keys(subs).length;
    try {
      const { price } = await goldPrice();
      await sendText(from, `✅ 机器人运行中\n当前金价: $${price.toFixed(2)}\n已注册用户: ${subCount} 人\n信号监控: 每30秒检查一次\n运行环境: VPS云服务器(24小时在线)`, msg.context_token);
    } catch (e) {
      await sendText(from, `✅ 机器人运行中\n已注册用户: ${subCount} 人`, msg.context_token);
    }

  } else if (text.startsWith("/register")) {
    const email = text.replace("/register", "").trim();
    if (!email || !email.includes("@")) {
      await sendText(from, `❌ 用法: /register 邮箱地址\n\n例如: /register 158566402@qq.com`, msg.context_token);
      return;
    }
    addSubscriber(from, email);
    log(`New subscriber: ${from} -> ${email}`);
    await sendText(from, `✅ 注册成功！\n\n邮箱: ${email}\n\n以后出现做多/做空信号时，我会自动通知你！\n\n你可以继续发 /price 查看实时金价，或 /signal 查看当前信号状态。`, msg.context_token);

  } else if (text === "/unsubscribe") {
    const subs = loadSubscribers();
    if (subs[from]) {
      const email = subs[from].email;
      delete subs[from];
      saveSubscribers(subs);
      await sendText(from, `✅ 已取消订阅\n邮箱: ${email}\n\n如需重新订阅，发 /register 邮箱`, msg.context_token);
    } else {
      await sendText(from, `你还没有注册过订阅\n\n发送 /register 邮箱 来注册`, msg.context_token);
    }

  } else {
    await sendText(from, `我不太理解"${text}"\n\n试试发送:\n/price - 查看金价\n/signal - 查看信号\n/register 邮箱 - 注册信号通知\n/help - 帮助`, msg.context_token);
  }
}

// === QR Status Polling Loop ===
let qrPollInterval = null;

function startQrPolling() {
  if (qrPollInterval) clearInterval(qrPollInterval);
  qrPollInterval = setInterval(async () => {
    try {
      if (!login.qrcode || status === "confirmed") {
        clearInterval(qrPollInterval);
        return;
      }
      await pollQrStatus();
      if (status === "confirmed") {
        clearInterval(qrPollInterval);
        startCommandLoop();
      } else if (status === "expired") {
        log("QR expired, refreshing...");
        await startQr();
      }
    } catch (e) {
      log(`QR poll error: ${e.message}`);
    }
  }, 5000);
}

// === Command Loop with auto-reconnect ===
let commandLoopRunning = false;
let reconnectAttempts = 0;
const MAX_RECONNECT_ATTEMPTS = 999; // 几乎无限重连

async function startCommandLoop() {
  if (commandLoopRunning) return;
  commandLoopRunning = true;
  log("Starting command loop...");

  if (existsSync(UPDATES_BUF_FILE)) {
    getUpdatesBuf = readFileSync(UPDATES_BUF_FILE, "utf-8").trim();
  }

  // Start signal monitor
  setInterval(checkSignal, 30000);
  checkSignal();

  async function loop() {
    while (true) {
      try {
        const msgs = await getUpdates();
        reconnectAttempts = 0; // 成功则重置重连计数
        for (const msg of msgs) {
          await handleMessage(msg);
        }
      } catch (e) {
        reconnectAttempts++;
        log(`getupdates error (attempt ${reconnectAttempts}/${MAX_RECONNECT_ATTEMPTS}): ${e.message}`);

        if (reconnectAttempts >= 5 && reconnectAttempts % 5 === 0) {
          // 每5次失败尝试重新登录
          log(`Connection lost ${reconnectAttempts} times, attempting re-login...`);
          try {
            // 尝试用保存的token重连
            if (existsSync(ACCOUNT_FILE)) {
              const account = JSON.parse(readFileSync(ACCOUNT_FILE, "utf-8"));
              log(`Using saved account: ${account.accountId}`);
            }
          } catch (e2) {
            log(`Re-login prep failed: ${e2.message}`);
          }
        }

        if (reconnectAttempts >= MAX_RECONNECT_ATTEMPTS) {
          log(`Max reconnect attempts reached, giving up. Manual restart needed.`);
          break;
        }

        // 退避等待：前5次等5秒，之后等10秒
        const waitTime = reconnectAttempts <= 5 ? 5000 : 10000;
        await new Promise(r => setTimeout(r, waitTime));
      }
    }
  }
  loop();
}

// === HTTP Server (local only) ===
const PORT = 9867;

const server = http.createServer(async (req, res) => {
  res.setHeader("Content-Type", "application/json; charset=utf-8");

  if (req.url === "/api/qr") {
    try {
      const url = await startQr();
      startQrPolling();
      res.end(JSON.stringify({ ok: true, qrcodeUrl: url, status: "wait" }));
    } catch (e) {
      res.end(JSON.stringify({ ok: false, error: e.message }));
    }
  } else if (req.url === "/api/status") {
    const subs = loadSubscribers();
    res.end(JSON.stringify({
      ok: true,
      status,
      qrcodeUrl: login.qrcodeUrl,
      accountId: login.accountId || null,
      hasToken: !!login.botToken,
      subscribers: Object.keys(subs).length,
      lastSignal: lastSignal || null,
      reconnectAttempts,
    }));
  } else if (req.url === "/api/subscribers") {
    const subs = loadSubscribers();
    res.end(JSON.stringify({ ok: true, subscribers: subs }));
  } else if (req.url === "/api/signal") {
    try {
      const data = await fetchSignalData();
      if (data && data.strategy) {
        res.end(JSON.stringify({ ok: true, strategy: data.strategy }));
      } else {
        res.end(JSON.stringify({ ok: false, error: "无法获取信号数据" }));
      }
    } catch (e) {
      res.end(JSON.stringify({ ok: false, error: e.message }));
    }
  } else {
    res.end(JSON.stringify({ ok: true, message: "ARK智能AI乾金策 - WeChat Signal Bot", status, version: "2.0.0" }));
  }
});

server.listen(PORT, "127.0.0.1", () => {
  log(`Helper server running on http://127.0.0.1:${PORT}`);
});

// === Main ===
async function main() {
  log("ARK智能AI乾金策 - WeChat Signal Bot v2.0 starting...");

  if (existsSync(ACCOUNT_FILE)) {
    try {
      const account = JSON.parse(readFileSync(ACCOUNT_FILE, "utf-8"));
      login.accountId = account.accountId;
      login.botToken = account.token;
      login.baseUrl = account.baseUrl;
      login.userId = account.userId;
      status = "confirmed";
      log("Loaded saved account, starting command loop...");
      startCommandLoop();
    } catch (e) {
      log(`Failed to load account: ${e.message}`);
      await startQr();
      startQrPolling();
    }
  } else {
    await startQr();
    startQrPolling();
  }
}

main().catch(e => {
  log(`Fatal: ${e.message}`);
  process.exit(1);
});
