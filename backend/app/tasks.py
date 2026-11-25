import os
import smtplib
from email.message import EmailMessage
from datetime import date, datetime, timedelta
from sqlalchemy.orm import Session
from .database import SessionLocal
from .models import Employee, EmployeeDocument, Notification, LeaveRequest, User

def _send_smtp(to_email: str, subject: str, body: str):
    host = os.getenv("SMTP_HOST")
    if not host:
        # No SMTP provider configured: do not pretend an email was delivered.
        return {"sent": False, "reason": "SMTP_HOST is not configured"}
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = os.getenv("SMTP_FROM", os.getenv("SMTP_USER", "hrms@localhost"))
    msg["To"] = to_email
    msg.set_content(body)
    port = int(os.getenv("SMTP_PORT", "587"))
    with smtplib.SMTP(host, port, timeout=20) as server:
        if os.getenv("SMTP_STARTTLS", "true").lower() == "true":
            server.starttls()
        if os.getenv("SMTP_USER"):
            server.login(os.environ["SMTP_USER"], os.getenv("SMTP_PASSWORD", ""))
        server.send_message(msg)
    return {"sent": True}

try:
    from .services.celery_app import celery_app
except ImportError:
    from celery import Celery
    celery_app = Celery("hrms")

@celery_app.task(name="app.tasks.send_email", autoretry_for=(Exception,), retry_backoff=True, max_retries=3)
def send_email(to_email: str, subject: str, body: str):
    return _send_smtp(to_email, subject, body)

@celery_app.task(name="app.tasks.document_expiry_reminders")
def document_expiry_reminders():
    db: Session = SessionLocal()
    try:
        today = date.today()
        docs = db.query(EmployeeDocument).filter(
            EmployeeDocument.expiry_date.is_not(None),
            EmployeeDocument.expiry_date <= today + timedelta(days=30),
            EmployeeDocument.expiry_date >= today
        ).all()
        count = 0
        for doc in docs:
            emp = db.get(Employee, doc.employee_id)
            if emp and emp.user_id:
                user = db.get(User, emp.user_id)
                if user:
                    db.add(Notification(user_id=user.id, message=f"Document '{doc.original_filename}' expires on {doc.expiry_date}."))
                    send_email.delay(user.email, "Employee document expiry reminder",
                                     f"Your document {doc.original_filename} expires on {doc.expiry_date}.")
                    count += 1
        db.commit()
        return {"reminders_created": count}
    finally:
        db.close()

@celery_app.task(name="app.tasks.pending_approval_reminders")
def pending_approval_reminders():
    db: Session = SessionLocal()
    try:
        cutoff = datetime.utcnow() - timedelta(hours=24)
        requests = db.query(LeaveRequest).filter(
            LeaveRequest.status.in_(["PENDING_MANAGER", "PENDING_HR"]),
            LeaveRequest.created_at <= cutoff
        ).all()
        # HR and manager roles are notified in-app; email delivery is queued when configured.
        from .models import Role
        target_roles = ["MANAGER", "TEAM_LEADER"] if requests and requests[0].status == "PENDING_MANAGER" else ["HR_ADMIN", "HR_MANAGER"]
        users = db.query(User).join(Role).filter(Role.name.in_(target_roles), User.is_active == True).all()
        for req in requests:
            roles = ["MANAGER", "TEAM_LEADER"] if req.status == "PENDING_MANAGER" else ["HR_ADMIN", "HR_MANAGER"]
            for user in db.query(User).join(Role).filter(Role.name.in_(roles), User.is_active == True).all():
                reminder_text = f"Leave request #{req.id} is awaiting approval."
                already_notified = db.query(Notification).filter(
                    Notification.user_id == user.id,
                    Notification.message == reminder_text,
                    Notification.created_at >= datetime.utcnow() - timedelta(hours=24)
                ).first()
                if not already_notified:
                    db.add(Notification(user_id=user.id, message=reminder_text))
                    send_email.delay(user.email, "Pending leave approval", f"Leave request #{req.id} is awaiting your review.")
        db.commit()
        return {"requests_checked": len(requests)}
    finally:
        db.close()
