import os

bind = f"0.0.0.0:{os.getenv('PORT', '5000')}"
workers = int(os.getenv("WEB_CONCURRENCY", "1"))
threads = int(os.getenv("GUNICORN_THREADS", "4"))
timeout = int(os.getenv("GUNICORN_TIMEOUT", "600"))
graceful_timeout = 60
keepalive = 5
if os.path.isdir("/dev/shm"):
    worker_tmp_dir = "/dev/shm"
