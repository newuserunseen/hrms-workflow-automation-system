from .celery_app import celery_app

def queue_email(to_email: str, subject: str, body: str):
    """Queue email without making business requests depend on SMTP availability."""
    try:
        celery_app.send_task("app.tasks.send_email", args=[to_email, subject, body])
    except Exception:
        # The in-app notification remains persisted; email can be retried by operations.
        pass
