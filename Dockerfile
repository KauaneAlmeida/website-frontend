# Imagem base Node.js
FROM node:20-alpine

# Instalar curl (para healthcheck) e git (se precisar para dependências npm)
RUN apk add --no-cache curl git

# Criar diretório da aplicação
WORKDIR /app

# Criar usuário não-root
RUN addgroup -g 1001 -S appuser && \
    adduser -S -D -H -u 1001 -h /app -s /sbin/nologin -G appuser appuser

# Copiar package.json e package-lock.json
COPY package*.json ./

# Instalar dependências
RUN npm install --omit=dev && npm cache clean --force

# Copiar o restante do código
COPY . .

# Dar permissão ao usuário
RUN mkdir -p /app/whatsapp_session && \
    chown -R appuser:appuser /app

# Trocar para usuário não-root
USER appuser

# Expor a porta que o Cloud Run usa (8080)
EXPOSE 8080

# Healthcheck opcional (ping no endpoint /health)
HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=3 \
  CMD curl -f http://localhost:${PORT:-8080}/health || exit 1

# Comando para rodar o bot
CMD ["node", "whatsapp_baileys.js"]
