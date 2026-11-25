import os
from celery import Celery

redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
celery_app = Celery("hrms", broker=redis_url, backend=redis_url, include=["app.tasks"])
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone=os.getenv("APP_TIMEZONE", "Asia/Kolkata"),
    enable_utc=True,
    beat_schedule={
        "daily-document-expiry-reminders": {
            "task": "app.tasks.document_expiry_reminders",
            "schedule": 86400.0,
        },
        "hourly-pending-approval-reminders": {
            "task": "app.tasks.pending_approval_reminders",
            "schedule": 3600.0,
        },
    },
)
