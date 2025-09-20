// ========================
// index.js completo ajustado
// ========================
const { default: makeWASocket, DisconnectReason, useMultiFileAuthState } = require('@whiskeysockets/baileys');
const { Boom } = require('@hapi/boom');
const qrcode = require('qrcode-terminal');
const QRCode = require('qrcode');
const express = require('express');
const fs = require('fs');
const path = require('path');
const { Storage } = require('@google-cloud/storage');
const P = require('pino');

// Configuration
const CONFIG = {
  phoneNumber: '+5511918368812',
  sessionPath: path.join('/tmp', 'whatsapp_session'), // <- Cloud Run usa /tmp
  expressPort: process.env.PORT || 3000,
};

// Google Cloud Storage
const logger = P({ level: 'info' });
const BUCKET_NAME = process.env.SESSION_BUCKET; // defina no Cloud Run
const SESSIONS_PREFIX = (process.env.SESSIONS_PREFIX || 'sessions/whatsapp-bot').replace(/\/+$/, '') + '/';
const storage = BUCKET_NAME ? new Storage() : null;
const bucket = BUCKET_NAME ? storage.bucket(BUCKET_NAME) : null;

async function downloadSessionFromBucket() {
  if (!bucket) return;
  await fs.promises.mkdir(CONFIG.sessionPath, { recursive: true });
  logger.info({ msg: 'Baixando sessão do bucket', bucket: BUCKET_NAME, prefix: SESSIONS_PREFIX });
  const [files] = await bucket.getFiles({ prefix: SESSIONS_PREFIX });
  for (const f of files) {
    const relative = f.name.slice(SESSIONS_PREFIX.length);
    if (!relative) continue;
    const dest = path.join(CONFIG.sessionPath, relative);
    await fs.promises.mkdir(path.dirname(dest), { recursive: true });
    logger.info({ msg: 'baixando arquivo', src: f.name, dest });
    await f.download({ destination: dest });
  }
  logger.info('downloadSessionFromBucket: OK');
}

async function listLocalFiles(dir) {
  const out = [];
  const entries = await fs.promises.readdir(dir, { withFileTypes: true });
  for (const e of entries) {
    const full = path.join(dir, e.name);
    if (e.isDirectory()) {
      const sub = await listLocalFiles(full);
      sub.forEach((s) => out.push(path.relative(dir, path.join(full, s))));
    } else {
      out.push(path.relative(dir, full));
    }
  }
  return out;
}

async function uploadSessionToBucket() {
  if (!bucket) return;
  try {
    const exists = await fs.promises.stat(CONFIG.sessionPath).then(() => true).catch(() => false);
    if (!exists) return;
    const files = await listLocalFiles(CONFIG.sessionPath);
    for (const rel of files) {
      const localPath = path.join(CONFIG.sessionPath, rel);
      const destName = SESSIONS_PREFIX + rel;
      logger.info({ msg: 'uploading session file', localPath, destName });
      await bucket.upload(localPath, { destination: destName });
    }
    logger.info('uploadSessionToBucket: OK');
  } catch (err) {
    logger.error({ msg: 'uploadSessionToBucket erro', err: err.message });
  }
}

// Express app setup
const app = express();
app.use(express.json());
let qrCodeBase64 = null;

class BaileysWhatsAppBot {
  constructor() {
    this.sock = null;
    this.isConnected = false;
    this.authState = null;
    this.saveCreds = null;
    this.setupExpressServer();
  }

  setupExpressServer() {
    // QR Code display route
    app.get('/qr', async (req, res) => {
      try {
        const htmlContent = `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Connect your WhatsApp</title>
<link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
<style>
body { background: linear-gradient(135deg, #25D366 0%, #128C7E 100%); min-height: 100vh; }
.qr-container { background: white; border-radius: 20px; padding: 3rem; margin: 2rem auto; max-width: 500px; text-align: center; box-shadow: 0 10px 30px rgba(0,0,0,0.2); }
.qr-code-img { max-width: 280px; border: 3px solid #25D366; border-radius: 15px; padding: 15px; background: white; }
.title { color: #128C7E; font-weight: 700; margin-bottom: 1rem; }
.subtitle { color: #666; font-size: 1rem; margin-top: 1rem; }
.footer { margin-top: 2rem; font-size: 0.9rem; color: #888; }
.refresh-btn { background: #25D366; border: none; border-radius: 25px; padding: 10px 25px; color: white; font-weight: 600; transition: all 0.3s ease; }
.refresh-btn:hover { background: #128C7E; transform: translateY(-2px); }
.status-connected { color: #28a745; font-size: 1.2rem; font-weight: bold; }
.status-waiting { color: #ffc107; font-size: 1.1rem; font-weight: bold; }
.spinner-border { width: 1rem; height: 1rem; margin-right: 0.5rem; }
</style>
</head>
<body>
<div class="container d-flex justify-content-center align-items-center min-vh-100">
<div class="qr-container">
<h1 class="title">🔗 Connect WhatsApp</h1>
${this.isConnected 
? '<div class="mb-3 status-connected">✅ Conectado com sucesso!</div>'
: '<div class="mb-3 status-waiting"><div class="spinner-border text-warning" role="status"></div>Esperando conectar...</div>'}
${qrCodeBase64 && !this.isConnected
? `<div class="mb-3">
<img src="${qrCodeBase64}" class="qr-code-img" alt="WhatsApp QR Code">
<p class="subtitle">📱 Scan this QR Code with WhatsApp</p>
<small class="text-muted">Open WhatsApp → Settings → Linked Devices → Link a Device</small>
</div>`
: this.isConnected
? '<div class="mb-3"><p class="subtitle">WhatsApp está conectado e pronto!</p></div>'
: '<div class="mb-3"><p class="subtitle">⏳ Gerando QR Code...</p></div>'}
<button class="refresh-btn mt-3" onclick="window.location.reload()">🔄 Refresh</button>
<div class="footer">
<strong>WhatsApp Bot Service</strong><br>
<small>${CONFIG.phoneNumber}</small><br>
<small class="text-muted">Powered by Baileys</small>
</div>
</div>
</div>
</body>
</html>`;
        res.send(htmlContent);
      } catch (error) {
        console.error('❌ Error serving QR page:', error);
        res.status(500).send('Error');
      }
    });

    // API endpoint for QR status
    app.get('/api/qr-status', (req, res) => {
      res.json({
        hasQR: !!qrCodeBase64,
        isConnected: this.isConnected,
        phoneNumber: CONFIG.phoneNumber,
        timestamp: new Date().toISOString(),
        status: this.isConnected ? 'connected' : qrCodeBase64 ? 'waiting_for_scan' : 'generating_qr',
      });
    });

    // Normal send message endpoint
    app.post('/send-message', async (req, res) => {
      try {
        const { to, message } = req.body;
        if (!to || !message) {
          return res.status(400).json({ success: false, error: 'Missing required fields: to, message' });
        }
        if (!this.isConnected) {
          return res.status(503).json({ success: false, error: 'WhatsApp not connected. Please scan QR code first.' });
        }
        const messageId = await this.sendMessage(to, message);
        res.json({ success: true, messageId, to, timestamp: new Date().toISOString() });
      } catch (error) {
        console.error('❌ Error in send-message endpoint:', error);
        res.status(500).json({ success: false, error: error.message || 'Failed to send message' });
      }
    });

    // Health check endpoint
    app.get('/health', (req, res) => {
      res.json({
        status: 'healthy',
        service: 'whatsapp_bot',
        connected: this.isConnected,
        uptime: process.uptime(),
        timestamp: new Date().toISOString(),
      });
    });

    // Start Express server
    app.listen(CONFIG.expressPort, '0.0.0.0', () => {
      console.log(`🌐 Express server running on port ${CONFIG.expressPort}`);
      console.log(`📱 QR Code page: /qr`);
      console.log(`🔍 Health check: /health`);
    });
  }

  async initialize() {
    try {
      console.log('🚀 Initializing Baileys WhatsApp Bot...');
      console.log(`📞 Phone: ${CONFIG.phoneNumber}`);
      console.log(`🌐 Server listening on port: ${CONFIG.expressPort}`);

      if (!fs.existsSync(CONFIG.sessionPath)) {
        fs.mkdirSync(CONFIG.sessionPath, { recursive: true });
        console.log(`📁 Created session directory: ${CONFIG.sessionPath}`);
      }

      // baixa sessão do bucket
      await downloadSessionFromBucket();

      const { state, saveCreds } = await useMultiFileAuthState(CONFIG.sessionPath);
      this.authState = state;
      this.saveCreds = saveCreds;

      await this.connectToWhatsApp();
    } catch (error) {
      console.error('❌ Error initializing WhatsApp bot:', error);
      process.exit(1);
    }
  }

  async connectToWhatsApp() {
    try {
      console.log('🔌 Connecting to WhatsApp Web...');
      this.sock = makeWASocket({
        auth: this.authState,
        // não definir version força usar a detectada automaticamente
        printQRInTerminal: false,
        browser: ['WhatsApp Bot', 'Chrome', '91.0'],
        defaultQueryTimeoutMs: 60000,
        keepAliveIntervalMs: 10000,
        markOnlineOnConnect: true,
      });
      this.setupEventHandlers();
    } catch (error) {
      console.error('❌ Error connecting to WhatsApp:', error);
      throw error;
    }
  }

  setupEventHandlers() {
    this.sock.ev.on('connection.update', async (update) => {
      const { connection, lastDisconnect, qr } = update;

      if (qr) {
        console.log('📱 New QR Code generated!');
        console.log('🌐 Visit /qr to scan');
        qrcode.generate(qr, { small: true });

        try {
          qrCodeBase64 = await QRCode.toDataURL(qr, {
            width: 280,
            margin: 2,
            color: { dark: '#000000', light: '#FFFFFF' },
          });
          console.log('✅ QR Code ready for web display');
        } catch (err) {
          console.error('❌ Error generating QR code for web:', err);
        }
      }

      if (connection === 'close') {
        this.isConnected = false;
        qrCodeBase64 = null;
        const shouldReconnect =
          lastDisconnect?.error instanceof Boom
            ? lastDisconnect.error.output.statusCode !== DisconnectReason.loggedOut
            : true;

        console.log('🔌 Connection closed:', lastDisconnect?.error?.message || 'Unknown reason');
        if (shouldReconnect) {
          console.log('🔄 Reconnecting in 5 seconds...');
          setTimeout(() => {
            this.connectToWhatsApp().catch(console.error);
          }, 5000);
        } else {
          console.log('❌ Logged out. Waiting for new QR code...');
          this.connectToWhatsApp().catch(console.error);
        }
      } else if (connection === 'open') {
        console.log('✅ WhatsApp connected successfully!');
        this.isConnected = true;
        qrCodeBase64 = null;
        const user = this.sock.user;
        if (user) console.log(`👤 Connected as: ${user.name || user.id}`);
      } else if (connection === 'connecting') {
        console.log('🔄 Connecting to WhatsApp...');
      }
    });

    this.sock.ev.on('creds.update', async () => {
      await this.saveCreds();
      await uploadSessionToBucket();
    });

    // Message handler
    this.sock.ev.on('messages.upsert', async (m) => {
      try {
        const msg = m.messages[0];
        if (!msg.key.fromMe && m.type === 'notify') {
          const messageText = msg.message?.conversation || msg.message?.extendedTextMessage?.text || null;
          if (messageText) {
            console.log('📨 New message from', msg.key.remoteJid, ':', messageText.substring(0, 50) + '...');
          }
        }
      } catch (error) {
        console.error('❌ Error processing incoming message:', error);
      }
    });
  }

  async sendMessage(to, message) {
    if (!this.isConnected || !this.sock) throw new Error('WhatsApp not connected');
    try {
      console.log(
        '📤 Sending WhatsApp message:',
        message.substring(0, 100) + (message.length > 100 ? '...' : '')
      );
      const result = await this.sock.sendMessage(to, { text: message });
      console.log('✅ Message sent successfully:', result.key.id);
      return result.key.id;
    } catch (error) {
      console.error('❌ Error sending message:', error);
      throw error;
    }
  }
}

// Initialize bot
const bot = new BaileysWhatsAppBot();
bot.initialize().catch((error) => {
  console.error('💥 Fatal error during initialization:', error);
  process.exit(1);
});

console.log('🤖 Baileys WhatsApp Bot starting...');
console.log(`🌐 QR code page on /qr`);

const gracefulShutdown = (signal) => {
  console.log(`📴 Received ${signal}, shutting down gracefully...`);
  if (bot.sock) {
    try {
      bot.sock.end();
    } catch (error) {
      console.error('Error closing WhatsApp connection:', error);
    }
  }
  process.exit(0);
};

process.on('SIGTERM', () => gracefulShutdown('SIGTERM'));
process.on('SIGINT', () => gracefulShutdown('SIGINT'));
process.on('uncaughtException', (error) => {
  console.error('💥 Uncaught Exception:', error);
  process.exit(1);
});
process.on('unhandledRejection', (reason, promise) => {
  console.error('💥 Unhandled Rejection at:', promise, 'reason:', reason);
  process.exit(1);
});
