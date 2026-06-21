FROM pgvector/pgvector:pg16

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

COPY start.sh /app/start.sh
RUN chmod +x /app/start.sh

CMD ["/app/start.sh"]
