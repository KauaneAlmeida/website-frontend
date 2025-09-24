const express = require('express');
const fs = require('fs');
const path = require('path');

// Firebase Admin SDK Integration
let firebaseDb = null;
let firebaseStorage = null;
let storageBucket = null;
let isFirebaseConnected = false;

async function initializeFirebase() {
    try {
        if (!process.env.FIREBASE_KEY) {
            console.log('⚠️ FIREBASE_KEY não encontrada - funcionando sem Firebase');
            return;
        }

        console.log('🔥 Inicializando Firebase Admin...');
        const admin = require('firebase-admin');
        const firebaseKey = JSON.parse(process.env.FIREBASE_KEY);
        const credential = admin.credential.cert(firebaseKey);
        
        if (!admin.apps.length) {
            admin.initializeApp({ 
                credential,
                storageBucket: process.env.FIREBASE_STORAGE_BUCKET || 'whatsapp-sessions-exalted-kayak-472517-s4-1758254195'
            });
        }
        
        firebaseDb = admin.firestore();
        firebaseStorage = admin.storage();
        storageBucket = firebaseStorage.bucket();
        
        // Teste de conexão
        await firebaseDb.collection('_health_check').doc('whatsapp_bot').set({
            timestamp: new Date(),
            service: 'whatsapp_baileys_bot',
            status: 'initialized',
            storage_configured: true
        });
        
        isFirebaseConnected = true;
        console.log('✅ Firebase conectado com sucesso!');
        console.log('📦 Storage bucket:', storageBucket.name);
        
    } catch (error) {
        console.error('❌ Erro ao inicializar Firebase:', error.message);
        isFirebaseConnected = false;
    }
}

// Função para salvar mensagem no Firebase
async function saveMessageToFirebase(from, message, direction = 'received') {
    try {
        if (!firebaseDb) return;
        
        await firebaseDb.collection('whatsapp_messages').add({
            from: from,
            message: message,
            direction: direction, // 'received' ou 'sent'
            timestamp: new Date(),
            bot_service: 'baileys',
            phone_clean: from.replace('@s.whatsapp.net', '')
        });
        
        console.log(`💾 Mensagem ${direction} salva no Firebase`);
    } catch (error) {
        console.error('❌ Erro ao salvar mensagem no Firebase:', error);
    }
}

// Função para buscar dados do usuário no Firebase
async function getUserDataFromFirebase(phoneNumber) {
    try {
        if (!firebaseDb) return null;
        
        const cleanPhone = phoneNumber.replace('@s.whatsapp.net', '');
        
        // Buscar na collection de leads
        const leadsSnapshot = await firebaseDb.collection('leads')
            .where('phone', '==', cleanPhone)
            .limit(1)
            .get();
            
        if (!leadsSnapshot.empty) {
            return leadsSnapshot.docs[0].data();
        }
        
        // Buscar também na collection de sessões
        const sessionSnapshot = await firebaseDb.collection('user_sessions')
            .doc(cleanPhone)
            .get();
            
        if (sessionSnapshot.exists) {
            return sessionSnapshot.data();
        }
        
        return null;
    } catch (error) {
        console.error('❌ Erro ao buscar dados do usuário:', error);
        return null;
    }
}

// Rate limiting para evitar spam de fallback
class MessageRateLimit {
    constructor() {
        this.lastMessages = new Map(); // from -> timestamp
        this.cooldownMs = 30000; // 30 segundos entre mensagens de fallback
    }
    
    canSendFallback(from) {
        const now = Date.now();
        const lastTime = this.lastMessages.get(from);
        
        if (!lastTime || (now - lastTime) > this.cooldownMs) {
            this.lastMessages.set(from, now);
            return true;
        }
        
        console.log('⏳ Rate limit ativo para', from, '- não enviando fallback duplicado');
        return false;
    }
}

// Sistema de persistência de sessão no Cloud Storage
class CloudSessionManager {
    constructor() {
        this.sessionPath = './whatsapp_session';
        this.cloudPath = 'whatsapp-sessions/baileys-session';
        this.backupInterval = 5 * 60 * 1000; // 5 minutos
        this.lastBackup = 0;
    }

    // Baixar sessão do Cloud Storage
    async downloadSession() {
        try {
            if (!storageBucket) {
                console.log('⚠️ Storage não disponível - usando sessão local');
                return false;
            }

            console.log('📥 Tentando baixar sessão do Cloud Storage...');
            
            // Criar diretório local se não existir
            if (!fs.existsSync(this.sessionPath)) {
                fs.mkdirSync(this.sessionPath, { recursive: true });
            }

            // Lista de arquivos de sessão no cloud
            const [files] = await storageBucket.getFiles({
                prefix: this.cloudPath
            });

            if (files.length === 0) {
                console.log('📂 Nenhuma sessão encontrada no cloud - nova sessão será criada');
                return false;
            }

            console.log(`📦 Encontrados ${files.length} arquivos de sessão no cloud`);

            // Baixar cada arquivo
            for (const file of files) {
                const fileName = file.name.replace(`${this.cloudPath}/`, '');
                const localPath = path.join(this.sessionPath, fileName);
                
                try {
                    await file.download({ destination: localPath });
                    console.log(`✅ Baixado: ${fileName}`);
                } catch (downloadError) {
                    console.error(`❌ Erro ao baixar ${fileName}:`, downloadError.message);
                }
            }

            console.log('✅ Sessão restaurada do Cloud Storage!');
            return true;

        } catch (error) {
            console.error('❌ Erro ao baixar sessão:', error.message);
            return false;
        }
    }

    // Upload da sessão para Cloud Storage
    async uploadSession() {
        try {
            if (!storageBucket) {
                console.log('⚠️ Storage não disponível - sessão não será backupeada');
                return false;
            }

            const now = Date.now();
            if (now - this.lastBackup < this.backupInterval) {
                return false; // Rate limiting
            }

            if (!fs.existsSync(this.sessionPath)) {
                console.log('📂 Pasta de sessão local não existe ainda');
                return false;
            }

            console.log('📤 Fazendo backup da sessão para Cloud Storage...');

            const files = fs.readdirSync(this.sessionPath);
            let uploadedFiles = 0;

            for (const fileName of files) {
                const localPath = path.join(this.sessionPath, fileName);
                const cloudPath = `${this.cloudPath}/${fileName}`;

                try {
                    const stats = fs.statSync(localPath);
                    if (stats.isFile()) {
                        await storageBucket.upload(localPath, {
                            destination: cloudPath,
                            metadata: {
                                contentType: 'application/octet-stream',
                                metadata: {
                                    service: 'whatsapp_baileys_bot',
                                    timestamp: new Date().toISOString()
                                }
                            }
                        });
                        uploadedFiles++;
                    }
                } catch (uploadError) {
                    console.error(`❌ Erro ao fazer upload de ${fileName}:`, uploadError.message);
                }
            }

            this.lastBackup = now;
            console.log(`✅ Backup concluído: ${uploadedFiles} arquivos enviados`);
            return true;

        } catch (error) {
            console.error('❌ Erro ao fazer backup da sessão:', error.message);
            return false;
        }
    }

    // Agendar backups automáticos
    startAutoBackup() {
        setInterval(async () => {
            if (isFirebaseConnected) {
                await this.uploadSession();
            }
        }, this.backupInterval);
        
        console.log(`⏰ Backup automático configurado (${this.backupInterval/1000/60}min)`);
    }

    // Limpeza de sessão (para forçar novo QR)
    async clearSession() {
        try {
            console.log('🗑️ Limpando sessão local...');
            
            if (fs.existsSync(this.sessionPath)) {
                fs.rmSync(this.sessionPath, { recursive: true, force: true });
            }

            if (storageBucket) {
                console.log('🗑️ Limpando sessão do cloud...');
                const [files] = await storageBucket.getFiles({
                    prefix: this.cloudPath
                });

                for (const file of files) {
                    await file.delete();
                }
            }

            console.log('✅ Sessão limpa completamente');
        } catch (error) {
            console.error('❌ Erro ao limpar sessão:', error);
        }
    }
}

// Configuration - FIXED for Cloud Run
const CONFIG = {
    phoneNumber: process.env.WHATSAPP_PHONE_NUMBER || '+5511918368812',
    whatsappWebVersion: [2, 3000, 1026946712],
    sessionPath: './whatsapp_session',
    expressPort: process.env.PORT || 8080  // CORRIGIDO: usar PORT do Cloud Run
};

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
        this.server = null;
        this.rateLimit = new MessageRateLimit();
        this.sessionManager = new CloudSessionManager();
        this.setupExpressServer();
    }

    setupExpressServer() {
        // Health check primeiro
        app.get('/health', (req, res) => {
            res.status(200).json({
                status: 'healthy',
                service: 'whatsapp_baileys_bot',
                connected: this.isConnected,
                firebase_connected: isFirebaseConnected,
                storage_configured: !!storageBucket,
                uptime: process.uptime(),
                timestamp: new Date().toISOString(),
                port: CONFIG.expressPort,
                firebase_key_configured: !!process.env.FIREBASE_KEY,
                backend_url: process.env.FASTAPI_WEBHOOK_URL || 'https://law-firm-backend-936902782519-936902782519.us-central1.run.app/api/v1/whatsapp/webhook',
                session_backup_enabled: !!storageBucket
            });
        });

        app.get('/', (req, res) => {
            res.json({
                service: 'WhatsApp Baileys Bot with Cloud Persistence',
                status: 'running',
                connected: this.isConnected,
                firebase_connected: isFirebaseConnected,
                storage_configured: !!storageBucket,
                endpoints: {
                    qr: '/qr',
                    health: '/health',
                    sendMessage: '/send-message',
                    sendWithContext: '/send-to-whatsapp-with-context',
                    qrStatus: '/api/qr-status',
                    clearSession: '/clear-session',
                    backupSession: '/backup-session'
                }
            });
        });

        app.get('/qr', async (req, res) => {
            try {
                const htmlContent = `
<!DOCTYPE html>
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
        .firebase-status { margin-top: 1rem; font-size: 0.9rem; }
        .firebase-connected { color: #28a745; }
        .firebase-disconnected { color: #dc3545; }
        .cloud-status { margin-top: 1rem; font-size: 0.9rem; }
        .cloud-enabled { color: #17a2b8; }
    </style>
</head>
<body>
    <div class="container d-flex justify-content-center align-items-center min-vh-100">
        <div class="qr-container">
            <h1 class="title">Connect WhatsApp</h1>
            ${this.isConnected 
                ? '<div class="mb-3 status-connected">✅ Conectado com sucesso!</div>'
                : '<div class="mb-3 status-waiting"><div class="spinner-border text-warning" role="status"></div>Esperando conectar...</div>'}
            ${qrCodeBase64 && !this.isConnected
                ? `<div class="mb-3">
                     <img src="${qrCodeBase64}" class="qr-code-img" alt="WhatsApp QR Code">
                     <p class="subtitle">Scan this QR Code with WhatsApp</p>
                     <small class="text-muted">Open WhatsApp → Settings → Linked Devices → Link a Device</small>
                   </div>`
                : this.isConnected
                ? '<div class="mb-3"><p class="subtitle">WhatsApp conectado e sessão persistente!</p></div>'
                : '<div class="mb-3"><p class="subtitle">Carregando sessão...</p></div>'}
            <button class="refresh-btn mt-3" onclick="window.location.reload()">Refresh</button>
            <div class="firebase-status">
                <strong>Firebase:</strong> 
                <span class="${isFirebaseConnected ? 'firebase-connected' : 'firebase-disconnected'}">
                    ${isFirebaseConnected ? '✅ Conectado' : '❌ Desconectado'}
                </span>
            </div>
            <div class="cloud-status">
                <strong>Cloud Persistence:</strong> 
                <span class="cloud-enabled">
                    ${storageBucket ? '☁️ Ativo' : '❌ Inativo'}
                </span>
            </div>
            <div class="footer">
                <strong>WhatsApp Baileys Bot</strong><br>
                <small>${CONFIG.phoneNumber}</small><br>
                <small class="text-muted">Sessão persistente no Cloud</small>
            </div>
        </div>
    </div>
</body>
</html>`;
                res.send(htmlContent);
            } catch (error) {
                console.error('Error serving QR page:', error);
                res.status(500).send("Error");
            }
        });

        app.get('/api/qr-status', (req, res) => {
            res.json({
                hasQR: !!qrCodeBase64,
                isConnected: this.isConnected,
                phoneNumber: CONFIG.phoneNumber,
                firebase_connected: isFirebaseConnected,
                storage_configured: !!storageBucket,
                timestamp: new Date().toISOString(),
                status: this.isConnected ? 'connected' : qrCodeBase64 ? 'waiting_for_scan' : 'generating_qr'
            });
        });

        // Endpoint para limpar sessão e forçar novo QR
        app.post('/clear-session', async (req, res) => {
            try {
                await this.sessionManager.clearSession();
                
                // Reiniciar bot após limpeza
                setTimeout(async () => {
                    await this.initializeBailey();
                }, 2000);
                
                res.json({ 
                    success: true, 
                    message: 'Sessão limpa - novo QR será gerado em breve' 
                });
            } catch (error) {
                res.status(500).json({ 
                    success: false, 
                    error: error.message 
                });
            }
        });

        // Endpoint para forçar backup manual
        app.post('/backup-session', async (req, res) => {
            try {
                const success = await this.sessionManager.uploadSession();
                res.json({ 
                    success, 
                    message: success ? 'Backup realizado' : 'Backup não necessário ou falhou' 
                });
            } catch (error) {
                res.status(500).json({ 
                    success: false, 
                    error: error.message 
                });
            }
        });

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
                
                // Salvar no Firebase
                await saveMessageToFirebase(to, message, 'sent');
                
                res.json({ success: true, messageId, to, timestamp: new Date().toISOString() });
            } catch (error) {
                console.error('Error in send-message endpoint:', error);
                res.status(500).json({ success: false, error: error.message || 'Failed to send message' });
            }
        });

        app.post('/send-to-whatsapp-with-context', async (req, res) => {
            try {
                const { to, message, userData } = req.body;
                if (!to || !message || !userData) {
                    return res.status(400).json({ success: false, error: 'Missing required fields: to, message, userData' });
                }
                if (!this.isConnected) {
                    return res.status(503).json({ success: false, error: 'WhatsApp not connected. Please scan QR code first.' });
                }

                const contextMsg = `
Dados do cliente (via Landing Page):
- Nome: ${userData.name || 'Não informado'}
- Email: ${userData.email || 'Não informado'}
- Telefone: ${userData.phone || 'Não informado'}
- Área de interesse: ${userData.area || 'Não informado'}
- Descrição: ${userData.description || 'Não informado'}

Primeira mensagem do cliente:
${message}
                `;

                const messageId = await this.sendMessage(to, contextMsg);
                
                // Salvar no Firebase
                await saveMessageToFirebase(to, contextMsg, 'sent');
                
                res.json({ success: true, messageId, to, timestamp: new Date().toISOString() });
            } catch (error) {
                console.error('Error in send-to-whatsapp-with-context endpoint:', error);
                res.status(500).json({ success: false, error: error.message || 'Failed to send message with context' });
            }
        });

        // CRÍTICO: Iniciar servidor HTTP IMEDIATAMENTE
        this.server = app.listen(CONFIG.expressPort, '0.0.0.0', () => {
            console.log(`🌐 Express server running on PORT ${CONFIG.expressPort}`);
            console.log(`📱 QR Code page: http://localhost:${CONFIG.expressPort}/qr`);
            console.log(`❤️ Health check: http://localhost:${CONFIG.expressPort}/health`);
            console.log('✅ Server ready - inicializando serviços com persistência...');
            
            // Inicializar Firebase primeiro, depois Baileys
            this.initializeServices();
        });

        this.server.on('error', (error) => {
            console.error('❌ Server error:', error);
            if (error.code === 'EADDRINUSE') {
                console.error(`Port ${CONFIG.expressPort} is already in use`);
                process.exit(1);
            }
        });
    }

    // Verificar se o backend está online
    async checkBackendHealth() {
        try {
            const webhookUrl = process.env.FASTAPI_WEBHOOK_URL || 'https://law-firm-backend-936902782519-936902782519.us-central1.run.app/api/v1/whatsapp/webhook';
            const baseUrl = webhookUrl.split('/api')[0]; // Pega só a base URL
            const healthUrl = `${baseUrl}/health`; // Tenta endpoint de health
            
            console.log('🏥 Verificando saúde do backend:', healthUrl);
            
            const fetch = globalThis.fetch || require('node-fetch');
            const response = await fetch(healthUrl, {
                method: 'GET',
                timeout: 10000
            });
            
            if (response.ok) {
                console.log('✅ Backend está online e respondendo');
                return true;
            } else {
                console.warn('⚠️ Backend health check respondeu com erro:', response.status);
                
                // Tentar apenas a URL base se health não funcionar
                const baseResponse = await fetch(baseUrl, {
                    method: 'GET',
                    timeout: 10000
                });
                
                if (baseResponse.ok) {
                    console.log('✅ Backend URL base responde (sem endpoint /health)');
                    return true;
                }
                
                return false;
            }
        } catch (error) {
            console.error('❌ Backend não está acessível:', error.message);
            return false;
        }
    }

    // Inicializar serviços na ordem correta com persistência
    async initializeServices() {
        console.log('🚀 Inicializando serviços com persistência...');
        
        // 1. Primeiro Firebase
        await initializeFirebase();
        
        // 2. Inicializar manager de sessão
        if (isFirebaseConnected) {
            this.sessionManager.startAutoBackup();
            await this.sessionManager.downloadSession(); // Restaurar sessão
        }
        
        // 3. Verificar backend
        const backendHealthy = await this.checkBackendHealth();
        if (!backendHealthy) {
            console.warn('⚠️ ATENÇÃO: Backend pode não estar acessível!');
        }
        
        // 4. Pequeno delay para estabilizar
        setTimeout(async () => {
            // 5. Depois Baileys
            await this.initializeBailey();
        }, 2000);
    }

    // Separar a inicialização do Baileys (CORRIGIDO)
    async initializeBailey() {
        console.log('📱 Carregando dependências do Baileys...');
        
        try {
            // IMPORTAÇÃO CORRIGIDA DO BAILEYS
            const baileys = require('@whiskeysockets/baileys');
            console.log('🔍 Baileys object keys:', Object.keys(baileys));
            
            // Tentar diferentes formas de importar makeWASocket
            const makeWASocket = baileys.default?.default || baileys.default || baileys.makeWASocket || baileys;
            const DisconnectReason = baileys.DisconnectReason || baileys.default?.DisconnectReason;
            const useMultiFileAuthState = baileys.useMultiFileAuthState || baileys.default?.useMultiFileAuthState;
            
            // Verificar se conseguimos as funções necessárias
            if (typeof makeWASocket !== 'function') {
                throw new Error(`makeWASocket não é uma função. Tipo: ${typeof makeWASocket}. Baileys keys: ${Object.keys(baileys)}`);
            }
            
            if (!DisconnectReason) {
                throw new Error('DisconnectReason não encontrado');
            }
            
            if (typeof useMultiFileAuthState !== 'function') {
                throw new Error('useMultiFileAuthState não é uma função');
            }
            
            const { Boom } = require('@hapi/boom');
            const qrcode = require('qrcode-terminal');
            const QRCode = require('qrcode');
            
            console.log('✅ Dependências do Baileys carregadas com sucesso');
            console.log('📋 makeWASocket:', typeof makeWASocket);
            console.log('📋 DisconnectReason:', typeof DisconnectReason);
            console.log('📋 useMultiFileAuthState:', typeof useMultiFileAuthState);
            
            if (!fs.existsSync(CONFIG.sessionPath)) {
                fs.mkdirSync(CONFIG.sessionPath, { recursive: true });
            }

            const { state, saveCreds } = await useMultiFileAuthState(CONFIG.sessionPath);
            this.authState = state;
            this.saveCreds = saveCreds;

            await this.connectToWhatsApp(makeWASocket, DisconnectReason, Boom, qrcode, QRCode);
            
        } catch (error) {
            console.error('❌ Erro ao inicializar Baileys:', error);
            console.error('🔍 Stack trace completo:', error.stack);
            
            // Retry após 10 segundos
            setTimeout(() => {
                console.log('🔄 Tentando reinicializar Baileys...');
                this.initializeBailey();
            }, 10000);
        }
    }

    async connectToWhatsApp(makeWASocket, DisconnectReason, Boom, qrcode, QRCode) {
        try {
            console.log('🔌 Conectando ao WhatsApp Web com sessão persistente...');
            
            // Configurações otimizadas para evitar timeout de QR
            this.sock = makeWASocket({
                auth: this.authState,
                version: CONFIG.whatsappWebVersion,
                printQRInTerminal: false,
                browser: ['WhatsApp Baileys Bot', 'Chrome', '110.0.5481.77'],
                defaultQueryTimeoutMs: 30000,
                connectTimeoutMs: 30000,
                keepAliveIntervalMs: 30000,
                markOnlineOnConnect: false,
                generateHighQualityLinkPreview: false,
                syncFullHistory: false,
                shouldSyncHistoryMessage: () => false,
                shouldIgnoreJid: () => false,
                patchMessageBeforeSending: (msg) => msg,
                retryRequestDelayMs: 250,
                maxMsgRetryCount: 3,
                // Configurações específicas para QR code
                qrTimeout: 120000, // 2 minutos
                connectCooldownMs: 5000
            });
            
            this.setupEventHandlers(DisconnectReason, Boom, qrcode, QRCode);
        } catch (error) {
            console.error('❌ Erro ao conectar WhatsApp:', error);
            console.error('🔍 Stack trace:', error.stack);
            
            // Retry conexão após delay
            setTimeout(() => {
                console.log('🔄 Tentando reconectar...');
                this.connectToWhatsApp(makeWASocket, DisconnectReason, Boom, qrcode, QRCode);
            }, 10000);
        }
    }

    setupEventHandlers(DisconnectReason, Boom, qrcode, QRCode) {
        // Contador para QR code attempts
        let qrAttempts = 0;
        const maxQRAttempts = 5;
        
        this.sock.ev.on('connection.update', async (update) => {
            const { connection, lastDisconnect, qr } = update;

            if (qr) {
                qrAttempts++;
                console.log(`📱 QR Code gerado (tentativa ${qrAttempts}/${maxQRAttempts})`);
                console.log(`🔗 Acesse IMEDIATAMENTE: http://localhost:${CONFIG.expressPort}/qr`);
                
                // Mostrar QR no terminal
                qrcode.generate(qr, { small: true });

                try {
                    // Gerar QR para web com configurações otimizadas
                    qrCodeBase64 = await QRCode.toDataURL(qr, {
                        width: 320,
                        margin: 3,
                        color: { dark: '#000000', light: '#FFFFFF' },
                        errorCorrectionLevel: 'M'
                    });
                    console.log('✅ QR Code pronto para display web - ESCANEIE AGORA!');
                    
                    // Log de urgência
                    console.log('⚠️ IMPORTANTE: QR Code expira em ~40 segundos!');
                    
                } catch (err) {
                    console.error('❌ Erro ao gerar QR code para web:', err);
                }
                
                // Se muitas tentativas de QR, limpar sessão
                if (qrAttempts >= maxQRAttempts) {
                    console.log('⚠️ Muitas tentativas de QR. Limpando sessão...');
                    try {
                        // Limpar arquivos de sessão
                        if (fs.existsSync(CONFIG.sessionPath)) {
                            fs.rmSync(CONFIG.sessionPath, { recursive: true, force: true });
                        }
                        qrAttempts = 0;
                        
                        // Reinicializar após limpar
                        setTimeout(() => {
                            this.initializeBailey();
                        }, 5000);
                    } catch (cleanError) {
                        console.error('❌ Erro ao limpar sessão:', cleanError);
                    }
                }
            }

            if (connection === 'close') {
                this.isConnected = false;
                qrCodeBase64 = null;
                qrAttempts = 0; // Reset QR attempts on close
                
                const shouldReconnect = (lastDisconnect?.error instanceof Boom)
                    ? lastDisconnect.error.output.statusCode !== DisconnectReason.loggedOut
                    : true;

                console.log('❌ Conexão fechada:', lastDisconnect?.error?.message || 'Motivo desconhecido');
                
                // Log detalhado do erro
                if (lastDisconnect?.error) {
                    console.log('🔍 Código do erro:', lastDisconnect.error.output?.statusCode);
                    console.log('🔍 Detalhes:', lastDisconnect.error.message);
                }
                
                if (shouldReconnect) {
                    const reconnectDelay = lastDisconnect?.error?.message?.includes('QR refs attempts ended') ? 30000 : 10000;
                    console.log(`🔄 Reconectando em ${reconnectDelay/1000} segundos...`);
                    
                    setTimeout(() => {
                        // Limpar socket antigo
                        if (this.sock) {
                            try {
                                this.sock.end();
                            } catch (e) {
                                console.log('⚠️ Erro ao fechar socket antigo:', e.message);
                            }
                        }
                        this.initializeBailey();
                    }, reconnectDelay);
                } else {
                    console.log('❌ Não reconectando (usuário foi deslogado)');
                    // Limpar sessão quando deslogado
                    setTimeout(() => this.sessionManager.clearSession(), 2000);
                }
            } else if (connection === 'open') {
                console.log('✅ WhatsApp conectado com sucesso!');
                this.isConnected = true;
                qrCodeBase64 = null;
                qrAttempts = 0; // Reset QR attempts on successful connection
                
                // Fazer backup da sessão quando conectar
                setTimeout(async () => {
                    await this.sessionManager.uploadSession();
                    console.log('💾 Sessão backupeada no Cloud Storage');
                }, 5000);
                
                const user = this.sock.user;
                if (user) {
                    console.log(`👤 Conectado como: ${user.name || user.id}`);
                    console.log(`📞 Número: ${user.id?.split('@')[0] || 'Desconhecido'}`);
                }
            } else if (connection === 'connecting') {
                console.log('🔄 Conectando ao WhatsApp...');
            }
        });

        // Melhor tratamento de erro para credentials com backup
        this.sock.ev.on('creds.update', async () => {
            try {
                await this.saveCreds();
                console.log('💾 Credenciais salvas');
                
                // Backup automático quando credenciais mudam
                if (this.isConnected) {
                    setTimeout(() => this.sessionManager.uploadSession(), 1000);
                }
            } catch (error) {
                console.error('❌ Erro ao salvar credenciais:', error);
            }
        });

        this.sock.ev.on('messages.upsert', async (m) => {
            try {
                const msg = m.messages[0];
                if (!msg.key.fromMe && m.type === 'notify') {
                    const messageText = msg.message?.conversation || msg.message?.extendedTextMessage?.text || null;
                    if (messageText) {
                        console.log('📩 Nova mensagem de', msg.key.remoteJid, ':', messageText.substring(0, 50) + '...');
                        
                        // Salvar mensagem recebida no Firebase
                        await saveMessageToFirebase(msg.key.remoteJid, messageText, 'received');
                        
                        // Processar comandos especiais para Firebase
                        await this.processSpecialCommands(msg.key.remoteJid, messageText);
                        
                        // Encaminhar para backend
                        await this.forwardToBackend(msg.key.remoteJid, messageText, msg.key.id);
                    }
                }
            } catch (error) {
                console.error('❌ Erro ao processar mensagem recebida:', error);
            }
        });
    }

    // Processar comandos especiais relacionados ao Firebase
    async processSpecialCommands(from, message) {
        try {
            const lowerMessage = message.toLowerCase().trim();
            
            if (lowerMessage === '!meusdados' || lowerMessage === '!dados') {
                const userData = await getUserDataFromFirebase(from);
                
                if (userData) {
                    const answers = userData.answers || [];
                    let dataText = '📋 *Seus dados cadastrados:*\n\n';
                    
                    answers.forEach((answer, index) => {
                        dataText += `${index + 1}. ${answer}\n`;
                    });
                    
                    dataText += `\n📅 Cadastrado em: ${userData.created_at?.toDate?.() || userData.timestamp?.toDate?.() || 'Data não disponível'}`;
                    
                    await this.sendMessage(from, dataText);
                } else {
                    await this.sendMessage(from, '❌ Não encontrei seus dados cadastrados. Você já preencheu nosso formulário de captação?\n\nPara se cadastrar, entre em contato conosco.');
                }
                return;
            }
            
            if (lowerMessage === '!firebase' || lowerMessage === '!status') {
                const statusMsg = `🔥 *Status Firebase:* ${isFirebaseConnected ? '✅ Conectado' : '❌ Desconectado'}\n📱 *WhatsApp:* ✅ Conectado\n☁️ *Cloud Storage:* ${storageBucket ? '✅ Ativo' : '❌ Inativo'}\n⏰ *Timestamp:* ${new Date().toLocaleString('pt-BR')}`;
                await this.sendMessage(from, statusMsg);
                return;
            }
            
        } catch (error) {
            console.error('❌ Erro ao processar comandos especiais:', error);
        }
    }

    async forwardToBackend(from, message, messageId) {
        try {
            const webhookUrl = process.env.FASTAPI_WEBHOOK_URL || 'https://law-firm-backend-936902782519-936902782519.us-central1.run.app/api/v1/whatsapp/webhook';
            
            if (!process.env.FASTAPI_WEBHOOK_URL) {
                console.log('⚠️ FASTAPI_WEBHOOK_URL não definida, usando URL padrão do Cloud Run');
            }
            console.log('🎯 Webhook URL:', webhookUrl);
            
            const sessionId = `whatsapp_${from.replace('@s.whatsapp.net', '')}`;
            const payload = { 
                from, 
                message, 
                messageId, 
                sessionId, 
                timestamp: new Date().toISOString(), 
                platform: 'whatsapp',
                firebase_available: isFirebaseConnected
            };

            console.log('🔗 Encaminhando para backend:', message.substring(0, 50) + '...');
            console.log('📤 Payload completo:', JSON.stringify(payload, null, 2));
            
            const fetch = globalThis.fetch || require('node-fetch');
            
            const controller = new AbortController();
            const timeoutId = setTimeout(() => controller.abort(), 60000);
            
            const response = await fetch(webhookUrl, {
                method: 'POST',
                headers: { 
                    'Content-Type': 'application/json',
                    'User-Agent': 'WhatsApp-Bot/1.0'
                },
                body: JSON.stringify(payload),
                signal: controller.signal
            });
            
            clearTimeout(timeoutId);
            
            console.log('📊 Status da resposta:', response.status);
            console.log('📊 Status text:', response.statusText);
            console.log('📊 Headers:', Object.fromEntries(response.headers));
            
            if (response.ok) {
                const responseText = await response.text();
                console.log('📨 Resposta raw:', responseText);
                
                let responseData;
                try {
                    responseData = JSON.parse(responseText);
                } catch (parseError) {
                    console.error('❌ Erro ao fazer parse da resposta JSON:', parseError);
                    console.error('📄 Resposta que causou erro:', responseText);
                    // Só retorna, sem enviar mensagem automática
                    return;
                }
                
                console.log('✅ Mensagem encaminhada com sucesso');
                console.log('📋 Dados da resposta:', responseData);
                
                // Só envia resposta válida do backend
                if (responseData && responseData.response) {
                    await this.sendMessage(from, responseData.response);
                    await saveMessageToFirebase(from, responseData.response, 'sent');
                } else {
                    console.warn('⚠️ Backend não retornou campo "response"');
                    console.warn('📋 Estrutura recebida:', Object.keys(responseData || {}));
                }
            } else {
                const errorText = await response.text();
                console.error('❌ Erro HTTP:', response.status, response.statusText);
                console.error('📄 Erro detalhado:', errorText);
                
                // Só registra erro, não envia mensagem automática
                console.log('🔇 Erro HTTP registrado - nenhuma mensagem automática enviada');
            }
        } catch (error) {
            console.error('❌ Erro ao encaminhar para backend:', error.name);
            console.error('📋 Mensagem do erro:', error.message);
            console.error('🔍 Stack trace:', error.stack);
            
            let errorType = 'Erro desconhecido';
            if (error.name === 'AbortError') {
                errorType = 'Timeout de conexão (60s)';
            } else if (error.code === 'ECONNREFUSED') {
                errorType = 'Conexão recusada pelo servidor';
            } else if (error.code === 'ENOTFOUND') {
                errorType = 'Servidor não encontrado (DNS)';
            } else if (error.code === 'ECONNRESET') {
                errorType = 'Conexão resetada pelo servidor';
            } else if (error.code === 'ETIMEDOUT') {
                errorType = 'Timeout de conexão';
            }
            
            console.error('🏷️ Tipo de erro identificado:', errorType);
            
            // Só registra erro, não envia mensagem automática
            console.log('🔇 Erro de conexão registrado - nenhuma mensagem automática enviada');
        }
    }

    async sendMessage(to, message) {
        if (!this.isConnected || !this.sock) throw new Error('WhatsApp not connected');
        try {
            const result = await this.sock.sendMessage(to, { text: message });
            console.log('✅ Mensagem enviada com sucesso:', result.key.id);
            return result.key.id;
        } catch (error) {
            console.error('❌ Erro ao enviar mensagem:', error);
            throw error;
        }
    }
}

// Inicialização
console.log('🚀 WhatsApp Bot com Persistência Cloud iniciando...');
console.log(`🌐 Servidor iniciará na PORTA ${CONFIG.expressPort}`);
console.log(`🔥 Firebase: ${process.env.FIREBASE_KEY ? 'Configurado' : 'Não configurado'}`);
console.log(`🎯 Backend URL: ${process.env.FASTAPI_WEBHOOK_URL || 'https://law-firm-backend-936902782519-936902782519.us-central1.run.app/api/v1/whatsapp/webhook'}`);

const bot = new BaileysWhatsAppBot();

process.on('SIGTERM', () => {
    console.log('🔄 Finalizando... fazendo backup final');
    if (bot.sessionManager && bot.isConnected) {
        bot.sessionManager.uploadSession().finally(() => process.exit(0));
    } else {
        process.exit(0);
    }
});

process.on('SIGINT', () => {
    console.log('🔄 Finalizando... fazendo backup final');
    if (bot.sessionManager && bot.isConnected) {
        bot.sessionManager.uploadSession().finally(() => process.exit(0));
    } else {
        process.exit(0);
    }
});

console.log('✅ Inicialização do bot com persistência cloud concluída');