import os
# Set a disposable SQLite database before importing the application modules.
os.environ.setdefault("DATABASE_URL", "sqlite:////tmp/hrms_pytest_integration.db")
os.environ.setdefault("JWT_SECRET", "pytest-only-secret-that-must-never-be-used-in-production")
