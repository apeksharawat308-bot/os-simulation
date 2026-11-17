"""VM management (hypervisor partitions of the host). The capacity and lifecycle RULES live in the MySQL triggers
(T6 capacity, T7 lifecycle); this router only issues the statements and turns the trigger's message into an HTTP error.

Lifecycle: CREATED -> RUNNING <-> STOPPED, (CREATED|STOPPED) -> DESTROYED. A VM with active containers cannot be
stopped or destroyed. Jobs are only placed into RUNNING VMs, so start a VM after creating it.
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.api.auth import require_admin
from app.database.session import get_db

router = APIRouter(prefix="/api/vms", tags=["VM management"])


def _db_message(exc: Exception) -> str:
    args = getattr(getattr(exc, "orig", None), "args", ())
    return str(args[1]) if len(args) > 1 else str(exc)


class VmCreate(BaseModel):
    name: str = Field(min_length=1, max_length=50)
    vcpu: int = Field(gt=0)
    vram_mb: int = Field(gt=0)
    vdisk_mb: int = Field(gt=0)


class VmResize(BaseModel):
    vcpu: Optional[int] = Field(default=None, gt=0)
    vram_mb: Optional[int] = Field(default=None, gt=0)
    vdisk_mb: Optional[int] = Field(default=None, gt=0)


def _vm(db: Session, vm_id: int) -> dict:
    row = db.execute(text("SELECT * FROM v_vm_status WHERE vm_id = :i"), {"i": vm_id}).mappings().first()
    db.rollback()
    if row is None:
        raise HTTPException(status_code=404, detail=f"VM {vm_id} not found")
    return dict(row)


@router.get("")
def list_vms(db: Session = Depends(get_db)):
    rows = [dict(r) for r in db.execute(text("SELECT * FROM v_vm_status ORDER BY vm_id")).mappings()]
    db.rollback()
    return rows


@router.get("/{vm_id}")
def get_vm(vm_id: int, db: Session = Depends(get_db)):
    return _vm(db, vm_id)


@router.post("", status_code=201)
def create_vm(data: VmCreate, db: Session = Depends(get_db), _admin=Depends(require_admin)):
    try:
        db.execute(text("INSERT INTO vms (name, vcpu, vram_mb, vdisk_mb) VALUES (:n, :c, :r, :d)"),
                   {"n": data.name, "c": data.vcpu, "r": data.vram_mb, "d": data.vdisk_mb})
        vm_id = int(db.execute(text("SELECT LAST_INSERT_ID()")).scalar_one())
        db.commit()
    except DBAPIError as exc:                                # duplicate name, or trigger T6: exceeds host capacity
        db.rollback()
        raise HTTPException(status_code=409, detail=_db_message(exc)) from exc
    return _vm(db, vm_id)


@router.put("/{vm_id}")
def resize_vm(vm_id: int, data: VmResize, db: Session = Depends(get_db), _admin=Depends(require_admin)):
    cur = _vm(db, vm_id)
    new = {"c": data.vcpu or cur["vcpu"], "r": data.vram_mb or cur["vram_mb"], "d": data.vdisk_mb or cur["vdisk_mb"]}
    try:
        db.execute(text("UPDATE vms SET vcpu = :c, vram_mb = :r, vdisk_mb = :d WHERE id = :i"), {**new, "i": vm_id})
        db.commit()
    except DBAPIError as exc:                                # trigger T7 re-checks the host capacity
        db.rollback()
        raise HTTPException(status_code=409, detail=_db_message(exc)) from exc
    return _vm(db, vm_id)


def _set_status(db: Session, vm_id: int, status: str) -> dict:
    _vm(db, vm_id)                                           # 404 if missing
    try:
        db.execute(text("UPDATE vms SET status = :s WHERE id = :i"), {"s": status, "i": vm_id})
        db.commit()
    except DBAPIError as exc:                                # invalid transition / VM still has active containers
        db.rollback()
        raise HTTPException(status_code=409, detail=_db_message(exc)) from exc
    return _vm(db, vm_id)


@router.post("/{vm_id}/start")
def start_vm(vm_id: int, db: Session = Depends(get_db), _admin=Depends(require_admin)):
    return _set_status(db, vm_id, "RUNNING")


@router.post("/{vm_id}/stop")
def stop_vm(vm_id: int, db: Session = Depends(get_db), _admin=Depends(require_admin)):
    return _set_status(db, vm_id, "STOPPED")


@router.post("/{vm_id}/destroy")
def destroy_vm(vm_id: int, db: Session = Depends(get_db), _admin=Depends(require_admin)):
    return _set_status(db, vm_id, "DESTROYED")
