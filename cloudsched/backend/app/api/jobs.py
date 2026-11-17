from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.auth import Principal, require_admin, require_user
from app.core.config import settings
from app.database.session import get_db
from app.models.job import JobStatus
from app.repositories import job_repo
from app.schemas.job import JobCreate, JobOut
from app.services import job_service
from app.services.automation import POLICIES, cleanup_job_container
from app.services.execution_log import record_execution
from app.services.mysql_procedures import (allocate_job, cancel_job_proc, dispatch_waiting, place_job_on_vm,
                                           release_job, submit_job)

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


def _policy() -> str:
    p = settings.automation_policy.upper()
    return p if p in POLICIES else "PRIORITY_AGING"


def _authorize(db: Session, user: Optional[Principal], job_id: int) -> None:
    """With AUTH_REQUIRED, a normal user may only act on his own jobs (ADMIN: any job; anonymous jobs: anyone)."""
    if user is None or user.role == "ADMIN":
        return
    owner = db.execute(text("SELECT user_id FROM jobs WHERE id = :j"), {"j": job_id}).scalar()
    db.rollback()
    if owner is not None and owner != user.user_id:
        raise HTTPException(status_code=403, detail="this job belongs to another user")


def _check_fits_some_vm(db: Session, data: JobCreate) -> None:
    """A job bigger than the biggest VM could be granted host resources but never placed. Reject it up front.
    Best effort: if the vms table cannot be read (e.g. the SQLite unit tests) the check is skipped."""
    try:
        max_cpu, max_ram = db.execute(text("SELECT MAX(vcpu), MAX(vram_mb) FROM vms WHERE status <> 'DESTROYED'")).one()
        db.rollback()
    except Exception:
        db.rollback()
        return
    if max_cpu is None:
        raise HTTPException(status_code=422, detail="no VM exists yet: create one with POST /api/vms and start it")
    if data.cpu_cores > max_cpu or data.ram_mb > max_ram:
        raise HTTPException(status_code=422, detail=(
            f"job needs {data.cpu_cores} cpu / {data.ram_mb} MB but the biggest VM has {max_cpu} cpu / {max_ram} MB"))


@router.post("", response_model=JobOut, status_code=201)
def create(data: JobCreate, db: Session = Depends(get_db), user: Optional[Principal] = Depends(require_user)):
    """Create a job through MySQL admission control; triggers create history and Banker rows."""
    _check_fits_some_vm(db, data)
    try:
        job_id = submit_job(
            db, user_id=user.user_id if user else None, name=data.name, cpu=data.cpu_cores, ram_mb=data.ram_mb,
            storage_mb=data.storage_mb, est_time=data.est_time, priority=data.priority,
            arrival=data.arrival_time, deadline=data.deadline, job_type=data.job_type.value,
        )
        if data.description:
            db.execute(text("UPDATE jobs SET description=:description WHERE id=:job_id"),
                       {"description": data.description, "job_id": job_id})
            db.commit()
        job = job_repo.get(db, job_id)
        if job is None:
            raise HTTPException(status_code=500, detail="MySQL created the job but it could not be reloaded")
        return job
    except HTTPException:
        raise
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=f"MySQL rejected job submission: {exc}") from exc


@router.get("", response_model=list[JobOut])
def list_all(status: JobStatus | None = None, limit: int = Query(100, ge=1, le=500),
             offset: int = Query(0, ge=0), db: Session = Depends(get_db)):
    return job_repo.list_jobs(db, status, limit, offset)


@router.get("/{job_id}", response_model=JobOut)
def get_one(job_id: int, db: Session = Depends(get_db)):
    return job_service.get_job(db, job_id)


@router.post("/{job_id}/cancel", response_model=JobOut)
def cancel(job_id: int, db: Session = Depends(get_db), user: Optional[Principal] = Depends(require_user)):
    """Cancel a job that has not started. A RUNNING job is stopped with POST /{job_id}/kill instead."""
    _authorize(db, user, job_id)
    return job_service.cancel_job(db, job_id)


@router.post("/{job_id}/kill")
def kill(job_id: int, db: Session = Depends(get_db), user: Optional[Principal] = Depends(require_user)):
    """Stop a RUNNING (or waiting) job now: status CANCELLED, resources freed, real container removed, queue re-dispatched."""
    _authorize(db, user, job_id)
    try:
        cancel_job_proc(db, job_id)
        started = dispatch_waiting(db, _policy(), settings.aging_seconds)
        db.commit()
        cleanup_job_container(db, job_id)
        return {"job_id": job_id, "status": "CANCELLED", "waiting_jobs_started": started}
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=f"Could not kill job: {exc}") from exc


@router.post("/{job_id}/allocate")
def allocate(job_id: int, db: Session = Depends(get_db), user: Optional[Principal] = Depends(require_user)):
    """Run MySQL admission control + Banker's safety check; best-fit place in a VM if granted."""
    _authorize(db, user, job_id)
    try:
        result = allocate_job(db, job_id)
        vm_id = place_job_on_vm(db, job_id) if result == "GRANTED" else None
        db.commit()
        return {"job_id": job_id, "result": result, "vm_id": vm_id,
                "message": ("Resources allocated; VM/container placement attempted." if result == "GRANTED"
                            else "Job remains in WAITING state until resources become available.")}
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=f"Allocation failed: {exc}") from exc


@router.post("/{job_id}/complete")
def complete(job_id: int, db: Session = Depends(get_db), user: Optional[Principal] = Depends(require_user)):
    _authorize(db, user, job_id)
    try:
        record_execution(db, job_id, _policy())   # Gantt segment for the live schedule (skipped if never started)
        release_job(db, job_id, "COMPLETED")
        started = dispatch_waiting(db, _policy(), settings.aging_seconds)
        db.commit()
        cleanup_job_container(db, job_id)  # stop a real container if one is still running
        return {"job_id": job_id, "status": "COMPLETED", "waiting_jobs_started": started}
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=f"Could not complete job: {exc}") from exc


@router.post("/{job_id}/fail")
def fail(job_id: int, db: Session = Depends(get_db), user: Optional[Principal] = Depends(require_user)):
    _authorize(db, user, job_id)
    try:
        release_job(db, job_id, "FAILED")
        started = dispatch_waiting(db, _policy(), settings.aging_seconds)
        db.commit()
        cleanup_job_container(db, job_id)  # stop a real container if one is still running
        return {"job_id": job_id, "status": "FAILED", "waiting_jobs_started": started}
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=f"Could not fail job: {exc}") from exc


@router.post("/dispatch")
def dispatch(policy: str = Query("PRIORITY_AGING", pattern="^(FCFS|SJF|PRIORITY|PRIORITY_AGING)$"),
             aging_seconds: int = Query(60, ge=1), db: Session = Depends(get_db), _admin=Depends(require_admin)):
    try:
        started = dispatch_waiting(db, policy, aging_seconds)
        db.commit()
        return {"policy": policy, "started_jobs": started}
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=f"Dispatch failed: {exc}") from exc
