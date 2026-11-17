"""Thin Python wrappers around the MySQL stored procedures in database/03_procedures.sql.

The DATABASE enforces the rules (row locks, Banker's safe-state check, triggers); Python only calls it.
Only meant for MySQL (SQLite has no stored procedures). The FastAPI job routes call these wrappers
after the richer MySQL schema has been installed.

Each procedure runs its OWN transaction and COMMITs, so call these when the SQLAlchemy session has no
uncommitted work you still want to roll back.
"""
import functools
import time

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

GRANTED = "GRANTED"
DEFERRED_UNAVAILABLE = "DEFERRED_UNAVAILABLE"
DEFERRED_UNSAFE = "DEFERRED_UNSAFE"
INVALID = "INVALID"

_RETRYABLE = {1213, 1205}       # 1213 = deadlock victim, 1205 = lock wait timeout


def _retry(fn):
    """Re-run a procedure call (up to 3 times) when MySQL picked it as a deadlock victim. The procedures roll back
    their own work on error, so repeating the whole call is safe."""
    @functools.wraps(fn)
    def wrapper(db, *args, **kwargs):
        for attempt in (1, 2, 3):
            try:
                return fn(db, *args, **kwargs)
            except DBAPIError as exc:
                code = (getattr(getattr(exc, "orig", None), "args", None) or [None])[0]
                if code not in _RETRYABLE or attempt == 3:
                    raise
                db.rollback()
                time.sleep(0.05 * attempt)
    return wrapper


@_retry
def submit_job(db: Session, *, user_id: int | None, name: str, cpu: int, ram_mb: int, storage_mb: int,
               est_time: int, priority: int = 5, arrival: int = 0, deadline: int | None = None,
               job_type: str = "CPU_BOUND") -> int:
    """Admission control + insert. Raises if the request exceeds the host capacity or violates a constraint."""
    db.execute(
        text("CALL sp_submit_job(:u, :n, :c, :r, :s, :e, :p, :a, :d, :t, @new_job_id)"),
        {"u": user_id, "n": name, "c": cpu, "r": ram_mb, "s": storage_mb, "e": est_time,
         "p": priority, "a": arrival, "d": deadline, "t": job_type},
    )
    return int(db.execute(text("SELECT @new_job_id")).scalar_one())


@_retry
def allocate_job(db: Session, job_id: int) -> str:
    """Lock resources, check availability + Banker's safety, allocate. Returns one of the result codes above."""
    db.execute(text("CALL sp_allocate_job(:j, @alloc_result)"), {"j": job_id})
    return db.execute(text("SELECT @alloc_result")).scalar_one()


@_retry
def release_job(db: Session, job_id: int, final_status: str = "COMPLETED") -> None:
    """COMPLETED or FAILED. The trigger releases the allocations and closes the container."""
    db.execute(text("CALL sp_release_job(:j, :s)"), {"j": job_id, "s": final_status})


@_retry
def dispatch_waiting(db: Session, policy: str = "FCFS", aging_seconds: int = 60) -> int:
    """Start waiting jobs in policy order (FCFS | SJF | PRIORITY | PRIORITY_AGING). Returns how many started."""
    db.execute(text("CALL sp_dispatch_waiting(:p, :a, @started)"), {"p": policy, "a": aging_seconds})
    return int(db.execute(text("SELECT @started")).scalar_one())


@_retry
def place_job_on_vm(db: Session, job_id: int) -> int | None:
    """Best-fit placement into a RUNNING VM; returns the vm id or None when no VM has room."""
    db.execute(text("CALL sp_place_job_on_vm(:j, @placed_vm)"), {"j": job_id})
    vm = db.execute(text("SELECT @placed_vm")).scalar_one()
    return int(vm) if vm is not None else None


@_retry
def cancel_job_proc(db: Session, job_id: int) -> None:
    """Cancel a SUBMITTED / WAITING / RUNNING job (RUNNING = kill). The trigger frees allocations + closes the container."""
    db.execute(text("CALL sp_cancel_job(:j)"), {"j": job_id})


def resource_usage(db: Session) -> list[dict]:
    """Rows of v_resource_usage: resource_type, total_capacity, allocated, available, utilization_pct."""
    return [dict(r._mapping) for r in db.execute(text("SELECT * FROM v_resource_usage"))]
