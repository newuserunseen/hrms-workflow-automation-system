# HRMS Workflow Automation System

Full-stack HRMS MVP using FastAPI, SQLAlchemy, MySQL, React/TypeScript, Redis and Celery.

## Run
1. Install Docker Desktop.
2. Copy `.env.example` to `.env` and configure a real SMTP provider if email delivery is required.
3. Run `docker compose up --build`.
4. Open:
   - Frontend: http://localhost:5173
   - API docs: http://localhost:8000/docs
   - Health: http://localhost:8000/api/health

Demo administrator: `admin@hrms.local` / `Admin@12345`.

## Implemented capabilities
- JWT authentication, password hashing, role guards and account lockout after five failed logins.
- Employee CRUD and deactivation.
- Employee account provisioning endpoint with HR-set temporary password.
- Automatic onboarding task creation and completion tracking.
- Leave applications, overlap checks, manager-to-HR approval routing, final balance deduction, decision history and notifications.
- Attendance check-in/check-out.
- Department management and database-backed dashboard metrics.
- Private employee document upload/download/verification with MIME/extension allowlists and a 10 MB cap.
- In-app notifications and audit log endpoint.
- SMTP email delivery through Celery worker when SMTP environment variables are configured.
- Celery Beat scheduled reminders for pending approvals and expiring documents.
- Docker services for MySQL, Redis, API, frontend, Celery worker and Celery Beat.
- Alembic migration environment.

## Email configuration
Set `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM` and `SMTP_STARTTLS` in `.env`. If SMTP is not configured, in-app notifications still work, but email is not delivered.

## Document storage
Uploaded documents are stored in a private Docker volume, not exposed as static web files. Back up the `hrms_documents` volume. Restrict access to the API and host.

## Database migrations
The current app creates missing tables at startup for convenient local development. For schema evolution, run Alembic from the backend container after creating a migration:
```bash
docker compose exec backend alembic revision --autogenerate -m "describe change"
docker compose exec backend alembic upgrade head
```
Do not use `create_all` as a production migration strategy.

## Tests
Run:
```bash
cd backend
pip install -r requirements.txt
pytest -q
```

## Security and production checklist
This is an implementation baseline, not a security-certified HR platform. Before production:
- Replace demo admin credentials and JWT secret.
- Configure TLS, strict CORS origins, rate limiting and secret management.
- Add password reset/invitation links with single-use expiring tokens; do not send passwords by email.
- Configure SMTP and validate delivery with your mail provider.
- Add Alembic initial migration and run migrations as a release step.
- Add organization-specific leave calendars, holidays, half-day rules and policy configuration.
- Add malware scanning and object storage lifecycle policies for employee documents.
- Add full role/record-level authorization tests and external security review.
- Configure backups and disaster recovery.
