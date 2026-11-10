import ssl
from celery import Celery

# ВСТАВЬТЕ СВОЮ ССЫЛКУ СЮДА (внутри кавычек)
REDIS_URL = "rediss://default:gQAAAAAAAugGAAIgcDFjMGY4ZjMxNDMzMmQ0MmU4OGNiMTg1OTFjYzRmMDNiNA@leading-puma-190470.upstash.io:6379" 

celery_app = Celery(
    "video_transcriber",
    broker=REDIS_URL,
    backend=REDIS_URL,
    broker_use_ssl={"ssl_cert_reqs": ssl.CERT_NONE},
    redis_backend_use_ssl={"ssl_cert_reqs": ssl.CERT_NONE},
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    result_expires=3600,
)
