FROM node:18-slim

WORKDIR /app

# Copiar lockfile e package.json
COPY package*.json ./

# Instalar dependências de produção conforme lockfile
RUN apt-get update && apt-get install -y curl git \
    && npm ci --omit=dev && npm cache clean --force \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# Copiar o código fonte
COPY whatsapp_baileys.js ./

# Criar usuário não-root
RUN addgroup --system appuser && \
    adduser --system --ingroup appuser appuser && \
    mkdir -p /app/whatsapp_session && \
    chown -R appuser:appuser /app

USER appuser

EXPOSE 8080
ENV PORT=8080

HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:8080/health || exit 1

CMD ["node", "whatsapp_baileys.js"]
