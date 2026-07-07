from celery import Celery

from app.config import Settings

celery_app = Celery(
    "gp_converter",
    broker=Settings().celery_broker_url,
)
celery_app.conf.update(task_ignore_result=True)
