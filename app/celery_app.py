import os

from celery import Celery

celery_app = Celery(
    "gp_converter",
    broker=os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/0"),
)
celery_app.conf.update(task_ignore_result=True)
