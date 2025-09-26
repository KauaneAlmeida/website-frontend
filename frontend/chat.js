(function () {  
  console.log("📩 Script chat.js carregado...");  
  let chatInitialized = false;  
  let chatBot = null;  

  // API Service
  const API_BASE_URL = 'https://law-firm-backend-936902782519-936902782519.us-central1.run.app';  

  class ErrorHandler {  
    static handle(error, context = '') {  
      console.error(`Error in ${context}:`, error);  

      let userMessage = 'Ocorreu um erro inesperado. Tente novamente.';  

      if (error.name === 'TypeError' && error.message.includes('fetch')) {  
        userMessage = 'Problema de conexão. Verifique sua internet e tente novamente.';  
      } else if (error.message.includes('404')) {  
        userMessage = 'Serviço temporariamente indisponível. Tente novamente em alguns minutos.';  
      } else if (error.message.includes('500')) {  
        userMessage = 'Erro interno do servidor. Nossa equipe foi notificada.';  
      } else if (error.message.includes('timeout')) {  
        userMessage = 'A requisição demorou muito para responder. Tente novamente.';  
      }  

      return userMessage;  
    }  

    static showNotification(message, type = 'error') {  
      const notification = document.createElement('div');  
      notification.style.cssText = `  
        position: fixed;  
        top: 20px;  
        right: 20px;  
        background: ${type === 'error' ? '#ff4757' : '#2ed573'};  
        color: white;  
        padding: 12px 20px;  
        border-radius: 8px;  
        box-shadow: 0 4px 16px rgba(0, 0, 0, 0.2);  
        z-index: 100000;  
        font-family: 'Poppins', sans-serif;  
        font-size: 14px;  
        max-width: 300px;  
        opacity: 0;  
        transform: translateX(100%);  
        transition: all 0.3s ease;  
      `;  

      notification.textContent = message;  

      try {  
        document.body.appendChild(notification);  

        requestAnimationFrame(() => {  
          notification.style.opacity = '1';  
          notification.style.transform = 'translateX(0)';  
        });  

        setTimeout(() => {  
          notification.style.opacity = '0';  
          notification.style.transform = 'translateX(100%)';  
          setTimeout(() => {  
            if (notification.parentNode) {  
              notification.parentNode.removeChild(notification);  
            }  
          }, 300);  
        }, 5000);  
      } catch (error) {  
        console.error('Failed to show notification:', error);  
      }  
    }  
  }  

  // API Service
  class ApiService {  
    constructor() {  
      this.baseURL = API_BASE_URL;  
    }  

    async request(endpoint, options = {}) {  
      const url = `${this.baseURL}${endpoint}`;  
      const config = {  
        headers: {  
          'Content-Type': 'application/json',  
          ...options.headers,  
        },  
        ...options,  
      };  

      try {  
        const response = await fetch(url, config);  

        if (!response.ok) {  
          throw new Error(`HTTP error! status: ${response.status}`);  
        }  

        return await response.json();  
      } catch (error) {  
        console.error(`API request failed: ${endpoint}`, error);  
        ErrorHandler.showNotification(ErrorHandler.handle(error, `API ${endpoint}`));  
        throw error;  
      }  
    }  

    async checkHealth() {  
      return this.request('/health');  
    }  

    async startConversation() {  
      return this.request('/api/v1/conversation/start', {  
        method: 'POST',  
      });  
    }  

    async sendMessage(sessionId, message) {  
      return this.request('/api/v1/conversation/respond', {  
        method: 'POST',  
        body: JSON.stringify({  
          session_id: sessionId,  
          message: message,  
        }),  
      });  
    }  

    async getConversationStatus(sessionId) {  
      return this.request(`/api/v1/conversation/status/${sessionId}`);  
    }  
  }  

  // Session Manager
  class SessionManager {  
    constructor() {  
      this.SESSION_KEY = 'law_firm_session_id';  
      this.CONVERSATION_KEY = 'law_firm_conversation';  
    }  

    getSessionId() {  
      return localStorage.getItem(this.SESSION_KEY);  
    }  

    setSessionId(sessionId) {  
      localStorage.setItem(this.SESSION_KEY, sessionId);  
    }  

    clearSession() {  
      localStorage.removeItem(this.SESSION_KEY);  
      localStorage.removeItem(this.CONVERSATION_KEY);  
    }  

    saveConversation(messages) {  
      localStorage.setItem(this.CONVERSATION_KEY, JSON.stringify(messages));  
    }  

    getConversation() {  
      const saved = localStorage.getItem(this.CONVERSATION_KEY);  
      return saved ? JSON.parse(saved) : [];  
    }  

    hasActiveSession() {  
      return !!this.getSessionId();  
    }  
  }  

  // ChatBot Class
  class ChatBot {  
    constructor() {  
      this.isOpen = false;  
      this.messages = [];  
      this.isTyping = false;  
      this.sessionId = null;  
      this.conversationState = {  
        step: 'initial',  
        userData: {}  
      };  

      this.apiService = new ApiService();  
      this.sessionManager = new SessionManager();  
      this.hookedElements = new Set();  
      this.chatContainerExists = false;  

      this.init();  
    }  

    async init() {  
      this.createChatInterfaceInstantly();  
      this.setupEventListeners();  
      this.loadSavedConversation();  
      this.hookExistingElements();  

      // 🔹 Limpar sessão ao atualizar/recarregar a página
      window.addEventListener("beforeunload", () => {  
        this.sessionManager.clearSession();  
      });  
    }  

    createChatInterfaceInstantly() {  
      if (document.getElementById('chat-root')) {  
        this.chatContainerExists = true;  
        return;  
      }  

      const chatContainer = document.createElement('div');  
      chatContainer.id = 'chat-root';  
      chatContainer.innerHTML = `  
        <div class="chat-container">  
          <div class="chat-header">  
            <span>💬 Chat Advocacia - Escritório m.lima</span>  
            <button class="chat-close-btn" id="chat-close">×</button>  
          </div>  
          <div class="messages" id="chat-messages"></div>  
          <div class="input-area">  
            <input type="text" id="chat-input" placeholder="Digite sua mensagem..." />  
            <button id="chat-send">Enviar</button>  
          </div>  
        </div>  
      `;  

      document.body.appendChild(chatContainer);  
      this.chatContainerExists = true;  

      console.log('✅ Chat container criado instantaneamente');  
    }  

    setupEventListeners() {  
      document.addEventListener('click', (e) => {  
        if (e.target && e.target.id === 'chat-close') {  
          e.preventDefault();  
          this.closeChat();  
        }  
        else if (e.target && e.target.id === 'chat-send') {  
          e.preventDefault();  
          this.sendMessage();  
        }  
        else if (e.target && (  
          e.target.id === 'chat-launcher' ||   
          e.target.closest('#chat-launcher') ||  
          e.target.classList.contains('chat-launcher-icon') ||  
          e.target.classList.contains('chat-launcher-text')  
        )) {  
          e.preventDefault();  
          e.stopPropagation();  
          this.toggleChat();  
        }  
      }, true);  

      document.addEventListener('keypress', (e) => {  
        if (e.target.id === 'chat-input' && e.key === 'Enter') {  
          e.preventDefault();  
          this.sendMessage();  
        }  
      });  
    }  

    hookExistingElements() {  
      const hookElements = () => {  
        const launcher = document.getElementById('chat-launcher');  
        if (launcher && !this.hookedElements.has('chat-launcher')) {  
          this.hookedElements.add('chat-launcher');  

          launcher.addEventListener('click', (e) => {  
            e.preventDefault();  
            e.stopPropagation();  
            this.toggleChat();  
          });  

          console.log('✅ Chat launcher conectado');  
        }  
      };  

      hookElements();  
      setInterval(hookElements, 2000);  
    }  

    toggleChat() {  
      console.log('🔄 Toggle chat, estado atual:', this.isOpen);  
      if (this.isOpen) {  
        this.closeChat();  
      } else {  
        this.openChat();  
      }  
    }  

    openChat() {  
      console.log('📂 Abrindo chat...');  
      const chatRoot = document.getElementById('chat-root');  
      if (chatRoot) {  
        chatRoot.classList.add('active');  
        this.isOpen = true;  

        setTimeout(() => {  
          const input = document.getElementById('chat-input');  
          if (input) input.focus();  
        }, 100);  

        console.log('✅ Chat aberto');  
      }  
    }  

    closeChat() {  
      console.log('📁 Fechando chat...');  
      const chatRoot = document.getElementById('chat-root');  
      if (chatRoot) {  
        chatRoot.classList.remove('active');  
        this.isOpen = false;  

        // 🔹 Limpar sessão e conversa ao fechar chat
        this.sessionManager.clearSession();  
        this.messages = [];  
        console.log('✅ Chat fechado e conversa limpa');  
      }  
    }  

    loadSavedConversation() {  
      const savedMessages = this.sessionManager.getConversation();  
      const savedSessionId = this.sessionManager.getSessionId();  

      if (savedMessages.length > 0) {  
        this.messages = savedMessages;  
        this.sessionId = savedSessionId;  
        this.renderMessages();  
      } else {  
        this.startWelcomeMessage();  
      }  
    }  

    startWelcomeMessage() {  
      const welcomeMessage = {  
        type: 'bot',  
        text: 'Olá! Sou seu assistente jurídico. Como posso ajudá-lo hoje?',  
        timestamp: new Date()  
      };  

      this.addMessage(welcomeMessage);  
      this.conversationState.step = 'conversation';  
    }  

    async sendMessage() {  
      const input = document.getElementById('chat-input');  
      if (!input) return;  

      const message = input.value.trim();  

      if (!message || this.isTyping) return;  

      this.addMessage({  
        type: 'user',  
        text: message,  
        timestamp: new Date()  
      });  

      input.value = '';  
      this.showTyping();  

      try {  
        if (!this.sessionId) {  
          await this.startConversation();  
        }  

        const response = await this.apiService.sendMessage(this.sessionId, message);  

        this.hideTyping();  

        if (response.response) {  
          this.addMessage({  
            type: 'bot',  
            text: response.response,  
            timestamp: new Date()  
          });  
        }  

        this.updateConversationState(response);  

      } catch (error) {  
        console.error('Erro ao enviar mensagem:', error);  
        this.hideTyping();  
        this.addMessage({  
          type: 'bot',  
          text: 'Desculpe, ocorreu um erro. Tente novamente.',  
          timestamp: new Date()  
        });  
      }  
    }  

    async startConversation() {  
      try {  
        const response = await this.apiService.startConversation();  
        this.sessionId = response.session_id;  
        this.sessionManager.setSessionId(this.sessionId);  
      } catch (error) {  
        console.error('Erro ao iniciar conversa:', error);  
      }  
    }  

    updateConversationState(response) {  
      if (response.user_data) {  
        this.conversationState.userData = {   
          ...this.conversationState.userData,   
          ...response.user_data   
        };  
      }  

      if (response.step) {  
        this.conversationState.step = response.step;  
      }  
    }  

    addMessage(message) {  
      this.messages.push(message);  
      this.renderMessages();  
      this.saveConversation();  
    }  

    renderMessages() {  
      const messagesContainer = document.getElementById('chat-messages');  
      if (!messagesContainer) return;  

      messagesContainer.innerHTML = '';  

      this.messages.forEach(message => {  
        const messageEl = document.createElement('div');  
        messageEl.className = `message ${message.type}`;  

        const avatar = document.createElement('img');  
        avatar.className = 'avatar';  
        avatar.src = message.type === 'user' ? './assets/user.png' : './assets/bot.png';  
        avatar.alt = message.type === 'user' ? 'Usuário' : 'Assistente';  

        const bubble = document.createElement('div');  
        bubble.className = 'bubble';  

        const formattedText = this.formatMessageText(message.text);  
        bubble.innerHTML = formattedText;  

        if (message.type === 'user') {  
          messageEl.appendChild(bubble);  
          messageEl.appendChild(avatar);  
        } else {  
          messageEl.appendChild(avatar);  
          messageEl.appendChild(bubble);  
        }  

        messagesContainer.appendChild(messageEl);  
      });  

      messagesContainer.scrollTop = messagesContainer.scrollHeight;  
    }  

    formatMessageText(text) {  
      if (!text) return "";  

      console.log('🔍 DEBUG Frontend - Mensagem recebida:', text);  

      // Substitui placeholders por dados reais do usuário
      const userData = this.conversationState?.userData || {};  
      text = text.replace(/\{([^}]+)\}/g, (match, key) => {  
        const cleanKey = key.trim().toLowerCase();  
        if (userData[cleanKey]) {  
          return userData[cleanKey];  
        }  
        return ''; // remove se não encontrar  
      });  

      return text  
        .replace(/\\n/g, '<br>')  
        .replace(/\n/g, '<br>')  
        .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')  
        .replace(/\*(.*?)\*/g, '<em>$1</em>')  
        .replace(/`(.*?)`/g, '<code>$1</code>');  
    }  

    showTyping() {  
      if (this.isTyping) return;  

      this.isTyping = true;  
      const messagesContainer = document.getElementById('chat-messages');  
      if (!messagesContainer) return;  

      const typingEl = document.createElement('div');  
      typingEl.className = 'message bot typing-message';  
      typingEl.innerHTML = `  
        <img class="avatar" src="./assets/bot.png" alt="Assistente" />  
        <div class="typing-indicator">  
          <span></span>  
          <span></span>  
          <span></span>  
        </div>  
      `;  

      messagesContainer.appendChild(typingEl);  
      messagesContainer.scrollTop = messagesContainer.scrollHeight;  
    }  

    hideTyping() {  
      this.isTyping = false;  
      const typingMessage = document.querySelector('.typing-message');  
      if (typingMessage) {  
        typingMessage.remove();  
      }  
    }  

    saveConversation() {  
      this.sessionManager.saveConversation(this.messages);  
    }  

    destroy() {  
      this.hookedElements.clear();  
      this.chatContainerExists = false;  

      const chatRoot = document.getElementById('chat-root');  
      if (chatRoot && chatRoot.parentNode) {  
        chatRoot.parentNode.removeChild(chatRoot);  
      }  
    }  
  }  

  // Inicialização instantânea do chat
  function initChat() {  
    if (chatInitialized) return;  
    chatInitialized = true;  

    console.log("🚀 Inicializando chat instantaneamente...");  

    if (window.chatBot && typeof window.chatBot.destroy === 'function') {  
      window.chatBot.destroy();  
    }  

    try {  
      chatBot = new ChatBot();  
      window.chatBot = chatBot;  

      console.log("✅ Chat inicializado com sucesso!");  
    } catch (error) {  
      console.error("❌ Erro ao inicializar chat:", error);  
      chatInitialized = false;  
    }  
  }  

  if (document.readyState === 'loading') {  
    document.addEventListener('DOMContentLoaded', initChat);  
  } else {  
    initChat();  
  }  

  window.addEventListener('load', () => {  
    if (!chatInitialized) {  
      setTimeout(initChat, 100);  
    }  
  });  
})();  
