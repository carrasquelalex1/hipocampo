FROM python:3.12-slim-bookworm

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    postgresql-16 postgresql-16-pgvector postgresql-client-16 \
    && rm -rf /var/lib/apt/lists/*

ENV PG_MAJOR=16
ENV PGDATA=/var/lib/postgresql/data
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