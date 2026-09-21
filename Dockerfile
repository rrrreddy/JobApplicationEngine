FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/

# .env, data/ (sqlite db, telethon session, resume) are mounted at runtime, not baked into the image
VOLUME ["/app/data"]

CMD ["python", "-m", "app.main"]
