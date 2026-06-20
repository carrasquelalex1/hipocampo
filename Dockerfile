FROM python:3.12-slim-bookworm

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    postgresql-15 postgresql-client-15 postgresql-server-dev-15 \
    build-essential git \
    && rm -rf /var/lib/apt/lists/*

RUN git clone --depth 1 https://github.com/pgvector/pgvector.git /tmp/pgvector \
    && cd /tmp/pgvector && make && make install && rm -rf /tmp/pgvector

ENV PG_MAJOR=15
ENV PGDATA=/var/lib/postgresql/15/main
ENV DB_HOST=localhost
ENV DB_USER=hipocampo
ENV DB_PASSWORD=hipocampo
ENV DB_NAME=hipocampo_db
ENV NVIDIA_API_KEY=dummy
ENV GOOGLE_API_KEY=dummy

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN chmod +x docker-entrypoint.sh

EXPOSE 7860

ENTRYPOINT ["/app/docker-entrypoint.sh"]
CMD ["python", "scripts/hipocampo_mcp_server.py", "--http", "7860", "--host", "0.0.0.0"]