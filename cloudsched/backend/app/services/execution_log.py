"""Writes the REAL schedule into job_executions (the table behind v_gantt / v_job_metrics, which used to hold seed data only).

One row per finished job: start_time = simulation units since the first job was created, end_time = start + est_time,
algorithm = the dispatch policy that was active. Because v_job_metrics compares end_time with jobs.deadline,
deadline misses of live jobs now show up in the analytics automatically.
"""
import logging
from typing import Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import settings

log = logging.getLogger("cloudsched.execution_log")
VALID = ("FCFS", "SJF", "PRIORITY", "RR", "PRIORITY_AGING")

_SQL = """
INSERT INTO job_executions (job_id, vm_id, algorithm, start_time, end_time)
SELECT t.job_id, t.vm_id, :algo, t.st, t.st + t.est_time
FROM (
  SELECT j.id AS job_id, c.vm_id AS vm_id, j.est_time AS est_time,
         GREATEST(0, FLOOR(TIMESTAMPDIFF(SECOND, (SELECT MIN(x.created_at) FROM jobs x), c.started_at) / :scale)) AS st
  FROM jobs j JOIN containers c ON c.job_id = j.id
  WHERE j.id = :job AND c.started_at IS NOT NULL
) t
WHERE NOT EXISTS (SELECT 1 FROM job_executions e WHERE e.job_id = t.job_id AND e.algorithm = :algo)
"""


def record_execution(db: Session, job_id: int, algorithm: Optional[str] = None) -> bool:
    """Best effort: never raises. Returns True when a row was written (job had a started container)."""
    algo = algorithm if algorithm in VALID else "FCFS"
    try:
        res = db.execute(text(_SQL), {"algo": algo, "job": job_id, "scale": max(float(settings.time_scale), 0.001)})
        db.commit()
        return bool(res.rowcount)
    except Exception:
        db.rollback()
        log.exception("could not record the execution of job %s", job_id)
        return False
