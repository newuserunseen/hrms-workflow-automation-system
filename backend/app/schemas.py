from datetime import date
from pydantic import BaseModel, EmailStr, ConfigDict, Field

class LoginIn(BaseModel):
    email: EmailStr
    password: str

class EmployeeCreate(BaseModel):
    first_name: str = Field(min_length=1, max_length=80)
    last_name: str = Field(min_length=1, max_length=80)
    email: EmailStr
    phone: str | None = None
    designation: str | None = None
    department_id: int | None = None
    manager_id: int | None = None
    joining_date: date
    status: str = "ACTIVE"

class EmployeeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    employee_code: str
    first_name: str
    last_name: str
    email: str
    phone: str | None
    designation: str | None
    department_id: int | None
    joining_date: date
    status: str

class LeaveCreate(BaseModel):
    leave_type_id: int
    start_date: date
    end_date: date
    reason: str = Field(min_length=3, max_length=2000)

class DecisionIn(BaseModel):
    comments: str | None = None

class DepartmentIn(BaseModel):
    name: str
    description: str | None = None
