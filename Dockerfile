FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/
COPY docker-entrypoint.sh .
RUN chmod +x docker-entrypoint.sh

# .env, data/ (sqlite db, telethon session, resume) are mounted at runtime, not baked into the image
VOLUME ["/app/data"]

ENTRYPOINT ["./docker-entrypoint.sh"]
