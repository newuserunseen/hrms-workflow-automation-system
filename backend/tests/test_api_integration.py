from fastapi.testclient import TestClient
from app.main import app

def admin_client():
    client = TestClient(app)
    client.__enter__()
    response = client.post("/api/auth/login", json={"email":"admin@hrms.local","password":"Admin@12345"})
    assert response.status_code == 200, response.text
    client.headers.update({"Authorization": f"Bearer {response.json()['access_token']}"})
    return client

def test_admin_login_and_dashboard():
    with TestClient(app) as client:
        login = client.post("/api/auth/login", json={"email":"admin@hrms.local","password":"Admin@12345"})
        assert login.status_code == 200
        client.headers.update({"Authorization": f"Bearer {login.json()['access_token']}"})
        summary = client.get("/api/dashboard/summary")
        assert summary.status_code == 200
        assert "total_employees" in summary.json()

def test_employee_creation_generates_onboarding_and_leave_balances():
    with TestClient(app) as client:
        login = client.post("/api/auth/login", json={"email":"admin@hrms.local","password":"Admin@12345"})
        assert login.status_code == 200
        client.headers.update({"Authorization": f"Bearer {login.json()['access_token']}"})
        payload = {
            "first_name":"Integration","last_name":"Test",
            "email":f"integration.{uuid4().hex}@example.test",
            "phone":"9000000000","designation":"QA Engineer",
            "joining_date":"2026-11-25","status":"ACTIVE"
        }
        created = client.post("/api/employees", json=payload)
        assert created.status_code == 200, created.text
        employee_id = created.json()["id"]
        tasks = client.get(f"/api/onboarding/tasks?employee_id={employee_id}")
        assert tasks.status_code == 200
        assert len(tasks.json()) >= 4

def test_unauthenticated_employee_list_is_rejected():
    with TestClient(app) as client:
        response = client.get("/api/employees")
        assert response.status_code in (401, 403)
