from datetime import date, datetime
from fastapi import FastAPI, Depends, HTTPException, Query, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError
from pathlib import Path
from uuid import uuid4
import os, mimetypes
from .database import Base, engine, get_db
from .models import *
from .schemas import *
from .security import *
from .security import create_token, verify_password, hash_password, current_user, require_roles
from .schemas import LoginIn, EmployeeCreate, EmployeeOut, LeaveCreate, DecisionIn, DepartmentIn
from .services.notifications import queue_email

app = FastAPI(title="HRMS Workflow Automation API", version="1.0.0", description="Employee lifecycle, leave and approval workflow APIs")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

@app.on_event("startup")
def startup():
    Base.metadata.create_all(bind=engine)
    db = next(get_db())
    try:
        for name in ["SUPER_ADMIN", "HR_ADMIN", "HR_MANAGER", "MANAGER", "TEAM_LEADER", "EMPLOYEE"]:
            if not db.query(Role).filter_by(name=name).first():
                db.add(Role(name=name))
        db.commit()
        admin_role = db.query(Role).filter_by(name="SUPER_ADMIN").first()
        if not db.query(User).filter_by(email="admin@hrms.local").first():
            user = User(email="admin@hrms.local", password_hash=hash_password("Admin@12345"), role_id=admin_role.id)
            db.add(user); db.commit()
        for name, days in [("Casual Leave", 12), ("Sick Leave", 10), ("Earned Leave", 15), ("Unpaid Leave", 0), ("Maternity/Paternity Leave", 90)]:
            if not db.query(LeaveType).filter_by(name=name).first():
                db.add(LeaveType(name=name, default_days=days))
        db.commit()
    finally:
        db.close()

def audit(db, user, action, entity, entity_id=None):
    db.add(AuditLog(actor_user_id=user.id, action=action, entity=entity, entity_id=entity_id))

def employee_for_user(db, user):
    emp = db.query(Employee).filter_by(user_id=user.id).first()
    if not emp:
        raise HTTPException(404, "Employee profile is not linked to this account")
    return emp

@app.get("/api/health")
def health():
    return {"status": "ok", "service": "HRMS API"}

@app.post("/api/auth/login")
def login(data: LoginIn, db: Session = Depends(get_db)):
    user = db.query(User).filter_by(email=data.email).first()
    if not user or user.locked or not verify_password(data.password, user.password_hash):
        if user:
            user.failed_logins += 1
            if user.failed_logins >= 5: user.locked = True
            db.commit()
        raise HTTPException(401, "Incorrect email or password")
    user.failed_logins = 0
    db.commit()
    return {"access_token": create_token(user.id), "token_type": "bearer", "role": user.role.name, "user_id": user.id}

@app.get("/api/auth/me")
def me(user: User = Depends(current_user)):
    return {"id": user.id, "email": user.email, "role": user.role.name}

@app.get("/api/departments")
def departments(db: Session = Depends(get_db), user: User = Depends(current_user)):
    return db.query(Department).order_by(Department.name).all()

@app.post("/api/departments")
def create_department(data: DepartmentIn, db: Session = Depends(get_db), user: User = Depends(require_roles("SUPER_ADMIN", "HR_ADMIN"))):
    dept = Department(**data.model_dump()); db.add(dept)
    try: db.commit()
    except IntegrityError: db.rollback(); raise HTTPException(409, "Department already exists")
    db.refresh(dept); audit(db,user,"CREATE","department",dept.id); db.commit()
    return dept

@app.get("/api/employees", response_model=list[EmployeeOut])
def list_employees(search: str | None = None, department_id: int | None = None, status: str | None = None,
                   db: Session = Depends(get_db), user: User = Depends(current_user)):
    q = db.query(Employee)
    if search:
        term = f"%{search}%"
        q = q.filter((Employee.first_name.like(term)) | (Employee.last_name.like(term)) | (Employee.email.like(term)) | (Employee.employee_code.like(term)))
    if department_id: q = q.filter(Employee.department_id == department_id)
    if status: q = q.filter(Employee.status == status)
    return q.order_by(Employee.id.desc()).all()

@app.post("/api/employees", response_model=EmployeeOut)
def create_employee(data: EmployeeCreate, db: Session = Depends(get_db), user: User = Depends(require_roles("SUPER_ADMIN", "HR_ADMIN", "HR_MANAGER"))):
    emp = Employee(employee_code=f"EMP-{datetime.utcnow():%y%m%d%H%M%S}", **data.model_dump())
    db.add(emp)
    try: db.commit()
    except IntegrityError: db.rollback(); raise HTTPException(409, "Employee email or department reference is invalid")
    db.refresh(emp)
    tasks = [("Collect and verify identity documents","HR"),("Prepare workstation and system access","IT"),("Assign reporting manager","MANAGER"),("Complete HR orientation","HR")]
    for title, team in tasks: db.add(OnboardingTask(employee_id=emp.id,title=title,owner_team=team))
    # Provision policy balances at employee creation so the employee sees balances immediately.
    for leave_type in db.query(LeaveType).all():
        db.add(LeaveBalance(employee_id=emp.id, leave_type_id=leave_type.id, balance=leave_type.default_days))
    audit(db,user,"CREATE","employee",emp.id); db.commit()
    queue_email(emp.email, "Welcome to the organization",
                f"Your employee profile {emp.employee_code} has been created. HR will share your HRMS account access separately.")
    return emp

@app.get("/api/employees/{employee_id}", response_model=EmployeeOut)
def get_employee(employee_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    emp = db.get(Employee, employee_id)
    if not emp: raise HTTPException(404, "Employee not found")
    return emp

@app.put("/api/employees/{employee_id}", response_model=EmployeeOut)
def update_employee(employee_id: int, data: EmployeeCreate, db: Session = Depends(get_db), user: User = Depends(require_roles("SUPER_ADMIN", "HR_ADMIN", "HR_MANAGER"))):
    emp = db.get(Employee, employee_id)
    if not emp: raise HTTPException(404, "Employee not found")
    for key, value in data.model_dump().items(): setattr(emp,key,value)
    audit(db,user,"UPDATE","employee",emp.id); db.commit(); db.refresh(emp); return emp

@app.delete("/api/employees/{employee_id}")
def deactivate_employee(employee_id: int, db: Session = Depends(get_db), user: User = Depends(require_roles("SUPER_ADMIN", "HR_ADMIN"))):
    emp = db.get(Employee, employee_id)
    if not emp: raise HTTPException(404, "Employee not found")
    emp.status = "INACTIVE"
    if emp.user_id:
        linked = db.get(User, emp.user_id)
        if linked: linked.is_active = False
    audit(db,user,"DEACTIVATE","employee",emp.id); db.commit()
    return {"message":"Employee deactivated"}

@app.get("/api/onboarding/tasks")
def onboarding_tasks(employee_id: int | None = None, db: Session = Depends(get_db), user: User = Depends(current_user)):
    q = db.query(OnboardingTask)
    if employee_id: q = q.filter_by(employee_id=employee_id)
    return q.order_by(OnboardingTask.id.desc()).all()

@app.patch("/api/onboarding/tasks/{task_id}")
def complete_onboarding_task(task_id: int, db: Session = Depends(get_db), user: User = Depends(require_roles("SUPER_ADMIN","HR_ADMIN","HR_MANAGER","MANAGER"))):
    task = db.get(OnboardingTask, task_id)
    if not task: raise HTTPException(404,"Task not found")
    task.completed = True; db.commit()
    remaining = db.query(OnboardingTask).filter_by(employee_id=task.employee_id, completed=False).count()
    if remaining == 0:
        emp = db.get(Employee, task.employee_id); emp.status = "ACTIVE"; db.commit()
    return {"message":"Task completed","remaining_tasks":remaining}

@app.get("/api/leave/types")
def leave_types(db: Session = Depends(get_db), user: User = Depends(current_user)):
    return db.query(LeaveType).all()

@app.get("/api/leave/balance")
def leave_balance(db: Session = Depends(get_db), user: User = Depends(current_user)):
    emp = employee_for_user(db,user)
    return db.query(LeaveBalance,LeaveType).join(LeaveType,LeaveBalance.leave_type_id==LeaveType.id).filter(LeaveBalance.employee_id==emp.id).all()

@app.post("/api/leave")
def apply_leave(data: LeaveCreate, db: Session = Depends(get_db), user: User = Depends(current_user)):
    emp = employee_for_user(db,user)
    if data.end_date < data.start_date: raise HTTPException(400,"End date must be on or after start date")
    overlap = db.query(LeaveRequest).filter(LeaveRequest.employee_id==emp.id,LeaveRequest.status.in_(["PENDING_MANAGER","PENDING_HR","APPROVED"]),LeaveRequest.start_date<=data.end_date,LeaveRequest.end_date>=data.start_date).first()
    if overlap: raise HTTPException(409,"Leave dates overlap an existing request")
    lt = db.get(LeaveType,data.leave_type_id)
    if not lt: raise HTTPException(404,"Leave type not found")
    days = (data.end_date-data.start_date).days+1
    request = LeaveRequest(employee_id=emp.id,leave_type_id=lt.id,start_date=data.start_date,end_date=data.end_date,days=days,reason=data.reason)
    request.status = "PENDING_MANAGER" if emp.manager_id else "PENDING_HR"
    db.add(request); db.commit(); db.refresh(request)
    db.add(Notification(user_id=user.id, message=f"Leave request #{request.id} submitted successfully."))
    if emp.manager_id:
        manager = db.get(Employee, emp.manager_id)
        if manager and manager.user_id:
            manager_user = db.get(User, manager.user_id)
            if manager_user:
                db.add(Notification(user_id=manager_user.id, message=f"Leave request #{request.id} needs your approval."))
                queue_email(manager_user.email, "Leave approval required", f"Leave request #{request.id} is awaiting your review.")
    db.commit()
    return {"id":request.id,"status":request.status,"days":days}

@app.get("/api/leave")
def list_leave(db: Session = Depends(get_db), user: User = Depends(current_user)):
    q = db.query(LeaveRequest)
    if user.role.name == "EMPLOYEE":
        emp = employee_for_user(db,user); q=q.filter_by(employee_id=emp.id)
    return q.order_by(LeaveRequest.created_at.desc()).all()

@app.get("/api/approvals/pending")
def pending_approvals(db: Session = Depends(get_db), user: User = Depends(require_roles("SUPER_ADMIN","HR_ADMIN","HR_MANAGER","MANAGER","TEAM_LEADER"))):
    statuses = ["PENDING_HR"] if user.role.name in ("HR_ADMIN","HR_MANAGER","SUPER_ADMIN") else ["PENDING_MANAGER"]
    return db.query(LeaveRequest).filter(LeaveRequest.status.in_(statuses)).order_by(LeaveRequest.created_at).all()

@app.post("/api/approvals/{request_id}/decision")
def decide_leave(request_id: int, data: DecisionIn, db: Session = Depends(get_db), user: User = Depends(require_roles("SUPER_ADMIN","HR_ADMIN","HR_MANAGER","MANAGER","TEAM_LEADER"))):
    req = db.get(LeaveRequest,request_id)
    if not req: raise HTTPException(404,"Leave request not found")
    if req.status == "PENDING_MANAGER" and user.role.name not in ("MANAGER","TEAM_LEADER","SUPER_ADMIN"):
        raise HTTPException(403,"Manager approval required")
    if req.status == "PENDING_MANAGER" and user.role.name != "SUPER_ADMIN":
        requester = db.get(Employee, req.employee_id)
        approver_employee = db.query(Employee).filter_by(user_id=user.id).first()
        if not requester or not approver_employee or requester.manager_id != approver_employee.id:
            raise HTTPException(403, "Only the employee's assigned reporting manager can approve this request")
    if req.status == "PENDING_HR" and user.role.name not in ("HR_ADMIN","HR_MANAGER","SUPER_ADMIN"):
        raise HTTPException(403,"HR approval required")
    old = req.status
    action = "APPROVE"
    if req.status == "PENDING_MANAGER":
        req.manager_comment=data.comments
        req.status="PENDING_HR"
    elif req.status == "PENDING_HR":
        req.hr_comment=data.comments
        req.status="APPROVED"
        # Leave balance is deducted only after final approval; if no balance row exists, initialize from policy.
        bal = db.query(LeaveBalance).filter_by(employee_id=req.employee_id,leave_type_id=req.leave_type_id).with_for_update().first()
        lt=db.get(LeaveType,req.leave_type_id)
        if not bal:
            bal=LeaveBalance(employee_id=req.employee_id,leave_type_id=req.leave_type_id,balance=lt.default_days); db.add(bal); db.flush()
        if bal.balance < req.days:
            raise HTTPException(400,"Insufficient leave balance")
        bal.balance -= req.days
    else:
        raise HTTPException(409,"This request is not awaiting approval")
    db.add(ApprovalHistory(leave_request_id=req.id,actor_user_id=user.id,action=action,comments=data.comments))
    db.commit()
    employee = db.get(Employee, req.employee_id)
    if employee and employee.user_id:
        employee_user = db.get(User, employee.user_id)
        if employee_user:
            db.add(Notification(user_id=employee_user.id, message=f"Your leave request #{req.id} status is now {req.status}."))
            queue_email(employee_user.email, "Leave request update", f"Your leave request #{req.id} status is now {req.status}.")
            db.commit()
    if req.status == "PENDING_HR":
        hr_users = db.query(User).join(Role).filter(Role.name.in_(["HR_ADMIN","HR_MANAGER"]), User.is_active == True).all()
        for hr_user in hr_users:
            db.add(Notification(user_id=hr_user.id, message=f"Leave request #{req.id} needs HR approval."))
            queue_email(hr_user.email, "HR approval required", f"Leave request #{req.id} is awaiting HR review.")
        db.commit()
    return {"id":req.id,"previous_status":old,"status":req.status}

@app.post("/api/approvals/{request_id}/reject")
def reject_leave(request_id: int, data: DecisionIn, db: Session = Depends(get_db), user: User = Depends(require_roles("SUPER_ADMIN","HR_ADMIN","HR_MANAGER","MANAGER","TEAM_LEADER"))):
    req=db.get(LeaveRequest,request_id)
    if not req: raise HTTPException(404,"Leave request not found")
    if req.status not in ("PENDING_MANAGER","PENDING_HR"): raise HTTPException(409,"Request is not pending")
    old=req.status; req.status="REJECTED"
    db.add(ApprovalHistory(leave_request_id=req.id,actor_user_id=user.id,action="REJECT",comments=data.comments))
    db.commit()
    employee = db.get(Employee, req.employee_id)
    if employee and employee.user_id:
        employee_user = db.get(User, employee.user_id)
        if employee_user:
            db.add(Notification(user_id=employee_user.id, message=f"Your leave request #{req.id} was rejected."))
            queue_email(employee_user.email, "Leave request rejected", f"Your leave request #{req.id} was rejected. Comments: {data.comments or 'No comments provided.'}")
            db.commit()
    return {"id":req.id,"previous_status":old,"status":req.status}

@app.get("/api/attendance")
def attendance_history(db: Session=Depends(get_db),user: User=Depends(current_user)):
    q=db.query(Attendance)
    if user.role.name=="EMPLOYEE": q=q.filter_by(employee_id=employee_for_user(db,user).id)
    return q.order_by(Attendance.work_date.desc()).limit(100).all()

@app.post("/api/attendance/check-in")
def check_in(db: Session=Depends(get_db),user: User=Depends(current_user)):
    emp=employee_for_user(db,user); today=date.today()
    row=db.query(Attendance).filter_by(employee_id=emp.id,work_date=today).first()
    if row and row.check_in: raise HTTPException(409,"Already checked in today")
    if not row: row=Attendance(employee_id=emp.id,work_date=today); db.add(row)
    row.check_in=datetime.now(); db.commit()
    return {"message":"Checked in","check_in":row.check_in}

@app.post("/api/attendance/check-out")
def check_out(db: Session=Depends(get_db),user: User=Depends(current_user)):
    emp=employee_for_user(db,user); row=db.query(Attendance).filter_by(employee_id=emp.id,work_date=date.today()).first()
    if not row or not row.check_in: raise HTTPException(400,"Check in before checking out")
    if row.check_out: raise HTTPException(409,"Already checked out")
    row.check_out=datetime.now(); db.commit()
    hours=round((row.check_out-row.check_in).total_seconds()/3600,2)
    return {"message":"Checked out","hours_worked":hours}

@app.get("/api/dashboard/summary")
def dashboard_summary(db: Session=Depends(get_db),user: User=Depends(current_user)):
    return {
      "total_employees":db.query(Employee).count(),
      "active_employees":db.query(Employee).filter_by(status="ACTIVE").count(),
      "inactive_employees":db.query(Employee).filter_by(status="INACTIVE").count(),
      "pending_leaves":db.query(LeaveRequest).filter(LeaveRequest.status.in_(["PENDING_MANAGER","PENDING_HR"])).count(),
      "approved_leaves":db.query(LeaveRequest).filter_by(status="APPROVED").count(),
      "onboarding_tasks_open":db.query(OnboardingTask).filter_by(completed=False).count(),
      "departments":db.query(Department).count()
    }

@app.get("/api/notifications")
def notifications(db: Session=Depends(get_db),user: User=Depends(current_user)):
    return db.query(Notification).filter_by(user_id=user.id).order_by(Notification.created_at.desc()).limit(50).all()


# Employee account provisioning: HR sets a temporary password; employee should change it after first login.
@app.post("/api/employees/{employee_id}/account")
def provision_employee_account(employee_id: int, payload: dict, db: Session = Depends(get_db),
                               user: User = Depends(require_roles("SUPER_ADMIN", "HR_ADMIN"))):
    emp = db.get(Employee, employee_id)
    if not emp: raise HTTPException(404, "Employee not found")
    if emp.user_id: raise HTTPException(409, "Employee already has a login account")
    password = payload.get("temporary_password", "")
    if len(password) < 12: raise HTTPException(400, "Temporary password must contain at least 12 characters")
    role = db.query(Role).filter_by(name="EMPLOYEE").first()
    account = User(email=emp.email, password_hash=hash_password(password), role_id=role.id)
    db.add(account); db.flush()
    emp.user_id = account.id
    db.add(Notification(user_id=account.id, message="Your HRMS account has been created. Sign in and change your temporary password."))
    audit(db,user,"PROVISION_ACCOUNT","employee",emp.id)
    db.commit()
    queue_email(emp.email, "Your HRMS account is ready", f"Your HRMS account is ready. Sign in using {emp.email} and the temporary password provided by HR. Change it immediately after login.")
    return {"message":"Employee account created","user_id":account.id,"email":emp.email}

@app.post("/api/auth/change-password")
def change_password(payload: dict, db: Session = Depends(get_db), user: User = Depends(current_user)):
    current = payload.get("current_password", "")
    new = payload.get("new_password", "")
    if not verify_password(current, user.password_hash): raise HTTPException(400, "Current password is incorrect")
    if len(new) < 12: raise HTTPException(400, "New password must contain at least 12 characters")
    user.password_hash = hash_password(new)
    db.commit()
    return {"message":"Password changed"}

# Secure employee document storage. Files are stored outside the public frontend directory.
DOCUMENT_ROOT = Path(os.getenv("HRMS_DOCUMENT_DIR", "/app/private_documents"))
ALLOWED_DOCUMENT_TYPES = {
    "application/pdf", "image/jpeg", "image/png",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
}
MAX_DOCUMENT_BYTES = 10 * 1024 * 1024

@app.post("/api/employees/{employee_id}/documents")
async def upload_employee_document(employee_id: int, file: UploadFile = File(...),
                                   document_type: str = Form("OTHER"), expiry_date: date | None = Form(None),
                                   db: Session = Depends(get_db), user: User = Depends(require_roles("SUPER_ADMIN","HR_ADMIN","HR_MANAGER"))):
    emp = db.get(Employee, employee_id)
    if not emp: raise HTTPException(404, "Employee not found")
    if file.content_type not in ALLOWED_DOCUMENT_TYPES: raise HTTPException(415, "Only PDF, JPG, PNG and DOCX files are allowed")
    content = await file.read(MAX_DOCUMENT_BYTES + 1)
    if len(content) > MAX_DOCUMENT_BYTES: raise HTTPException(413, "File exceeds 10 MB limit")
    if not content: raise HTTPException(400, "Empty files are not allowed")
    suffix = Path(file.filename or "document").suffix.lower()
    if suffix not in {".pdf", ".jpg", ".jpeg", ".png", ".docx"}: raise HTTPException(415, "Unsupported file extension")
    DOCUMENT_ROOT.mkdir(parents=True, exist_ok=True)
    stored = f"{uuid4().hex}{suffix}"
    (DOCUMENT_ROOT / stored).write_bytes(content)
    doc = EmployeeDocument(employee_id=employee_id, original_filename=Path(file.filename or "document").name[:255],
                           stored_filename=stored, content_type=file.content_type, size_bytes=len(content),
                           document_type=document_type[:80], expiry_date=expiry_date, uploaded_by=user.id)
    db.add(doc); audit(db,user,"UPLOAD_DOCUMENT","employee_document",None); db.commit(); db.refresh(doc)
    return {"id":doc.id,"filename":doc.original_filename,"document_type":doc.document_type,"size_bytes":doc.size_bytes,"verified":doc.verified}

@app.get("/api/employees/{employee_id}/documents")
def list_employee_documents(employee_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    emp = db.get(Employee, employee_id)
    if not emp: raise HTTPException(404, "Employee not found")
    if user.role.name == "EMPLOYEE" and emp.user_id != user.id: raise HTTPException(403, "Not permitted")
    docs = db.query(EmployeeDocument).filter_by(employee_id=employee_id).order_by(EmployeeDocument.created_at.desc()).all()
    return [{"id":d.id,"filename":d.original_filename,"document_type":d.document_type,"content_type":d.content_type,
             "size_bytes":d.size_bytes,"expiry_date":d.expiry_date,"verified":d.verified,"created_at":d.created_at} for d in docs]

@app.get("/api/documents/{document_id}/download")
def download_employee_document(document_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    from fastapi.responses import FileResponse
    doc = db.get(EmployeeDocument, document_id)
    if not doc: raise HTTPException(404, "Document not found")
    emp = db.get(Employee, doc.employee_id)
    if user.role.name == "EMPLOYEE" and emp.user_id != user.id: raise HTTPException(403, "Not permitted")
    path = DOCUMENT_ROOT / doc.stored_filename
    if not path.is_file(): raise HTTPException(404, "Stored document is missing")
    return FileResponse(path, media_type=doc.content_type, filename=doc.original_filename)

@app.patch("/api/documents/{document_id}/verify")
def verify_employee_document(document_id: int, db: Session = Depends(get_db),
                             user: User = Depends(require_roles("SUPER_ADMIN","HR_ADMIN","HR_MANAGER"))):
    doc = db.get(EmployeeDocument, document_id)
    if not doc: raise HTTPException(404, "Document not found")
    doc.verified = True; audit(db,user,"VERIFY_DOCUMENT","employee_document",doc.id); db.commit()
    return {"message":"Document verified","id":doc.id}

@app.get("/api/audit-logs")
def get_audit_logs(limit: int = Query(100, ge=1, le=500), db: Session = Depends(get_db),
                   user: User = Depends(require_roles("SUPER_ADMIN","HR_ADMIN"))):
    return db.query(AuditLog).order_by(AuditLog.created_at.desc()).limit(limit).all()

@app.post("/api/notifications/{notification_id}/read")
def mark_notification_read(notification_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    item = db.get(Notification, notification_id)
    if not item or item.user_id != user.id: raise HTTPException(404, "Notification not found")
    item.is_read = True; db.commit()
    return {"message":"Notification marked as read"}

