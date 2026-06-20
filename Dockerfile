FROM python:3.12-slim-bookworm

RUN apt-get update && apt-get install -y \
    postgresql-15 postgresql-server-dev-15 \
    build-essential git libpq-dev \
    supervisor \
    && rm -rf /var/lib/apt/lists/*

RUN git clone --branch v0.5.1 --depth 1 https://github.com/pgvector/pgvector.git /tmp/pgvector \
    && cd /tmp/pgvector \
    && make \
    && make install \
    && rm -rf /tmp/pgvector

WORKDIR /app

COPY requirements.txt .
RUN pip install --break-system-packages --no-cache-dir -r requirements.txt

COPY . .

RUN chmod +x /app/init-db.sh /app/start-supervised.sh

ENV DB_HOST=localhost
ENV DB_PORT=5432
ENV DB_USER=hipocampo
ENV DB_PASSWORD=postgres
ENV DB_NAME=hipocampo_db
ENV NVIDIA_API_KEY=dummy
ENV GOOGLE_API_KEY=dummy
ENV PGDATA=/var/lib/postgresql/data

RUN mkdir -p /var/lib/postgresql/data && chown -R postgres:postgres /var/lib/postgresql

EXPOSE 7860

CMD ["/app/start-supervised.sh"]
