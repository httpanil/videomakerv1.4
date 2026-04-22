FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PORT=10000
ENV VIDEO_MAKER_DATA_DIR=/app/data
ENV WEB_CONCURRENCY=1
ENV GUNICORN_THREADS=4
ENV GUNICORN_TIMEOUT=600
ENV VIDEO_MAKER_BG_MUSIC=1
ENV VIDEO_MAKER_SFX=1
ENV VIDEO_MAKER_OVERLAY=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p /app/data

CMD ["sh", "-c", "gunicorn -c gunicorn.conf.py --bind 0.0.0.0:${PORT} app:app"]
