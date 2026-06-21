FROM python:3.12-slim-bookworm

RUN apt-get update && apt-get install -y postgresql-16 postgresql-server-dev-16 build-essential git libpq-dev \
    && rm -rf /var/lib/apt/lists/*

RUN git clone --branch v0.8.0 --depth 1 https://github.com/pgvector/pgvector.git /tmp/pgvector \
    && cd /tmp/pgvector \
    && make \
    && make install \
    && rm -rf /tmp/pgvector

WORKDIR /app

COPY requirements.txt .
RUN pip install --break-system-packages --no-cache-dir -r requirements.txt

COPY . .

ENV DB_HOST=localhost
ENV DB_PORT=5432
ENV DB_USER=hipocampo
ENV DB_PASSWORD=postgres
ENV DB_NAME=hipocampo_db
ENV NVIDIA_API_KEY=dummy
ENV GOOGLE_API_KEY=dummy
ENV PGDATA=/var/lib/postgresql/data
ENV PG_BIN=/usr/lib/postgresql/16/bin

EXPOSE 7860

RUN chmod +x /app/start.sh

CMD ["/app/start.sh"]
