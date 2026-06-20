FROM pgvector/pgvector:pg15

# Instalar Python 3 y pip
RUN apt-get update && apt-get install -y python3 python3-pip \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip3 install --no-cache-dir -r requirements.txt

COPY . .

ENV DB_HOST=localhost
ENV DB_USER=hipocampo
ENV DB_PASSWORD=postgres
ENV DB_NAME=hipocampo_db
ENV NVIDIA_API_KEY=dummy
ENV GOOGLE_API_KEY=dummy

EXPOSE 7860

# Copiar y configurar el entrypoint que inicia PostgreSQL y la app
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["python3", "scripts/hipocampo_mcp_server.py", "--http", "7860", "--host", "0.0.0.0"]
