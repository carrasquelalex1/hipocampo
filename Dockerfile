FROM pgvector/pgvector:pg15

RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 python3-pip python3-venv \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

ENV PG_MAJOR=15
ENV PGDATA=/var/lib/postgresql/data
ENV DB_HOST=localhost
ENV DB_USER=hipocampo
ENV DB_PASSWORD=hipocampo
ENV DB_NAME=hipocampo_db
ENV NVIDIA_API_KEY=dummy
ENV GOOGLE_API_KEY=dummy

COPY requirements.txt .
RUN pip3 install --no-cache-dir -r requirements.txt

COPY . .
RUN chmod +x docker-entrypoint.sh

EXPOSE 7860

ENTRYPOINT ["/app/docker-entrypoint.sh"]
CMD ["python3", "scripts/hipocampo_mcp_server.py", "--http", "7860", "--host", "0.0.0.0"]