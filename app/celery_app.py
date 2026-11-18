import os
import ssl

from celery import Celery
from dotenv import load_dotenv

load_dotenv()  # читает переменные из файла .env рядом с проектом

# Ссылка на Redis берётся из .env (строка REDIS_URL=...), в коде её больше нет
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

# SSL нужен только для облачного Redis (адрес начинается с rediss://)
ssl_options = {"ssl_cert_reqs": ssl.CERT_NONE} if REDIS_URL.startswith("rediss://") else None

celery_app = Celery(
    "video_transcriber",
    broker=REDIS_URL,
    backend=REDIS_URL,
    broker_use_ssl=ssl_options,
    redis_backend_use_ssl=ssl_options,
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    result_expires=3600,
)
