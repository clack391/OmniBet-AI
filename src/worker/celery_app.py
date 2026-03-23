from celery import Celery

celery_app = Celery(
    "omnibet",
    broker="redis://localhost:6379/0",
    backend="redis://localhost:6379/0",
    include=["src.worker.tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="Africa/Lagos",
    enable_utc=True,
    task_track_started=True,
    worker_prefetch_multiplier=1,
)
