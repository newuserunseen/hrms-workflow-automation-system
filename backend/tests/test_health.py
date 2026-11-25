from app.main import app

def test_health_route_exists():
    route_paths = {route.path for route in app.routes}
    assert "/api/health" in route_paths
    assert "/api/employees/{employee_id}/documents" in route_paths
    assert "/api/approvals/{request_id}/decision" in route_paths
