FROM pgvector/pgvector:pg15

RUN apt-get update && apt-get install -y python3 python3-pip \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip3 install --break-system-packages --no-cache-dir -r requirements.txt

COPY . .

ENV DB_HOST=localhost
ENV DB_USER=hipocampo
ENV DB_PASSWORD=postgres
ENV DB_NAME=hipocampo_db
ENV NVIDIA_API_KEY=dummy
ENV GOOGLE_API_KEY=dummy

EXPOSE 7860

RUN chmod +x /app/docker-entrypoint.sh

ENTRYPOINT ["/app/docker-entrypoint.sh"]
CMD ["python3", "scripts/hipocampo_mcp_server.py", "--http", "7860", "--host", "0.0.0.0"]
