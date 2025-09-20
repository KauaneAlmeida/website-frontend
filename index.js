const { default: makeWASocket, DisconnectReason, useMultiFileAuthState } = require('@whiskeysockets/baileys');
const { Boom } = require('@hapi/boom');
const qrcode = require('qrcode-terminal');
const express = require('express');
const fs = require('fs');
const path = require('path');
const { Storage } = require('@google-cloud/storage');

const storage = new Storage();
const bucketName = 'whatsapp-sessions-exalted-kayak-472517-s4-1758254195';
const authDir = '/tmp/auth_info';

// Utilitários
async function downloadAuthData() {
  console.log('📥 Baixando sessão do bucket...');
  if (!fs.existsSync(authDir)) fs.mkdirSync(authDir, { recursive: true });
  const [files] = await storage.bucket(bucketName).getFiles({ prefix: 'auth/' });
  for (const file of files) {
    const dest = path.join(authDir, file.name.replace('auth/', ''));
    await storage.bucket(bucketName).file(file.name).download({ destination: dest });
  }
}

async function uploadAuthData() {
  console.log('📤 Subindo sessão para o bucket...');
  if (!fs.existsSync(authDir)) return;
  const files = fs.readdirSync(authDir);
  for (const file of files) {
    await storage.bucket(bucketName).upload(path.join(authDir, file), {
      destination: `auth/${file}`,
      overwrite: true,
    });
  }
}

async function clearAuthData() {
  console.log('🗑️ Limpando sessão inválida...');
  if (fs.existsSync(authDir)) fs.rmSync(authDir, { recursive: true, force: true });
  const [files] = await storage.bucket(bucketName).getFiles({ prefix: 'auth/' });
  for (const file of files) {
    await file.delete().catch(() => {});
  }
}

// Conexão WhatsApp
async function connectToWhatsApp() {
  try {
    await downloadAuthData();
  } catch {
    console.log('⚠️ Nenhuma sessão encontrada no bucket, gerando QR novo...');
  }

  const { state, saveCreds } = await useMultiFileAuthState(authDir);

  sock.ev.on('creds.update', async () => {
    await saveCreds();
    await uploadAuthData();
  });

  sock.ev.on('connection.update', async (update) => {
    const { connection, lastDisconnect, qr } = update;

    if (qr) {
      console.log('📸 Escaneie este QR Code:');
      qrcode.generate(qr, { small: true });
    }

    if (connection === 'close') {
      const statusCode = lastDisconnect?.error instanceof Boom
        ? lastDisconnect.error.output.statusCode
        : 0;

      if (statusCode === DisconnectReason.loggedOut) {
        console.log('❌ Sessão inválida! Limpando e pedindo novo QR...');
        await clearAuthData();
        setTimeout(connectToWhatsApp, 2000);
      } else {
        console.log('🔄 Reconectando...');
        setTimeout(connectToWhatsApp, 2000);
      }
    }

    if (connection === 'open') {
      console.log('✅ Conectado ao WhatsApp!');
    }
  });

  return sock;
}

connectToWhatsApp().catch(err => console.error('Erro ao iniciar bot:', err));

// Servidor HTTP para Cloud Run
const app = express();
app.get('/', (req, res) => res.send('Bot WhatsApp rodando'));
app.listen(process.env.PORT || 3000, () => console.log('HTTP Server rodando'));
