from datetime import date
from app.models import LeaveRequest, EmployeeDocument, AttendanceCorrection

def inclusive_leave_days(start: date, end: date) -> int:
    if end < start:
        raise ValueError("End date must be on or after start date")
    return (end - start).days + 1

def overlaps(start_a, end_a, start_b, end_b):
    return start_a <= end_b and end_a >= start_b

def test_leave_duration_is_inclusive():
    assert inclusive_leave_days(date(2026, 11, 25), date(2026, 11, 27)) == 3

def test_leave_duration_rejects_reversed_dates():
    try:
        inclusive_leave_days(date(2026, 11, 27), date(2026, 11, 25))
    except ValueError:
        pass
    else:
        raise AssertionError("Expected reversed date range to fail")

def test_overlap_detection():
    assert overlaps(date(2026, 11, 1), date(2026, 11, 5), date(2026, 11, 5), date(2026, 11, 8))
    assert not overlaps(date(2026, 11, 1), date(2026, 11, 4), date(2026, 11, 5), date(2026, 11, 8))

def test_pending_feature_models_are_registered():
    assert LeaveRequest.__tablename__ == "leave_requests"
    assert EmployeeDocument.__tablename__ == "employee_documents"
    assert AttendanceCorrection.__tablename__ == "attendance_corrections"
