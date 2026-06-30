from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.database import get_db
from app.models import SleepLog, User
from app.schemas import SleepLogIn, SleepLogOut

router = APIRouter(prefix="/sleep-logs", tags=["Sleep Logs"])


@router.post("", response_model=SleepLogOut, status_code=201)
def create_log(
    body: SleepLogIn,
    db: Session = Depends(get_db),
    me: User = Depends(get_current_user),
):
    rec = SleepLog(
        user_id=me.id,
        sleep_time=body.sleep_time,
        wake_time=body.wake_time,
        duration_hours=body.duration_hours,
        quality_score=body.quality_score,
        awakenings=body.awakenings,
        notes=body.notes,
        logged_date=body.logged_date,
    )
    db.add(rec)
    db.commit()
    db.refresh(rec)
    return rec


@router.get("", response_model=List[SleepLogOut])
def list_logs(
    page: int = Query(1, ge=1),
    page_size: int = Query(30, ge=1, le=100),
    db: Session = Depends(get_db),
    me: User = Depends(get_current_user),
):
    return (
        db.query(SleepLog)
        .filter(SleepLog.user_id == me.id)
        .order_by(SleepLog.logged_date.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )


@router.get("/{log_id}", response_model=SleepLogOut)
def get_log(
    log_id: UUID,
    db: Session = Depends(get_db),
    me: User = Depends(get_current_user),
):
    rec = db.query(SleepLog).filter(
        SleepLog.id == log_id,
        SleepLog.user_id == me.id,
    ).first()

    if not rec:
        raise HTTPException(status_code=404, detail="log not found")
    return rec


@router.delete("/{log_id}", status_code=204)
def delete_log(
    log_id: UUID,
    db: Session = Depends(get_db),
    me: User = Depends(get_current_user),
):
    rec = db.query(SleepLog).filter(
        SleepLog.id == log_id,
        SleepLog.user_id == me.id,
    ).first()

    if not rec:
        raise HTTPException(status_code=404, detail="log not found")

    db.delete(rec)
    db.commit()
