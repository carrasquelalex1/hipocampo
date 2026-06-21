FROM python:3.12-slim-bookworm

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV NVIDIA_API_KEY=dummy
ENV GOOGLE_API_KEY=dummy

EXPOSE 7860

CMD ["python", "scripts/hipocampo_mcp_server.py", "--http", "7860", "--host", "0.0.0.0"]
