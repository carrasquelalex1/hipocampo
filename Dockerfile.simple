FROM python:3.12-slim-bookworm

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV DB_HOST=localhost
ENV DB_USER=hipocampo
ENV DB_NAME=hipocampo_db
ENV NVIDIA_API_KEY=dummy
ENV GOOGLE_API_KEY=dummy

EXPOSE 8001

CMD ["python", "scripts/hipocampo_mcp_server.py", "--http", "8001"]