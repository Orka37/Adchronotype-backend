from typing import List
import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.database import get_db
from app.models import CognitiveTest, User
from app.schemas import CogTestIn, CogTestOut

router = APIRouter(prefix="/cognitive-tests", tags=["Cognitive Tests"])
logger = logging.getLogger("adchronotype.cognitive_tests")


@router.post("", response_model=CogTestOut, status_code=201)
def submit_result(
    body: CogTestIn,
    db: Session = Depends(get_db),
    me: User = Depends(get_current_user),
):
    rec = CognitiveTest(
        user_id=me.id,
        test_type=body.test_type,
        score=body.score,
        unit=body.unit,
        duration_seconds=body.duration_seconds,
        tested_at=body.tested_at,
    )
    db.add(rec)
    db.commit()
    db.refresh(rec)
    logger.info(
        "cognitive_test_saved user_id=%s cognitive_test_id=%s test_type=%s score=%s",
        me.id,
        rec.id,
        rec.test_type,
        rec.score,
    )
    return rec


@router.get("", response_model=List[CogTestOut])
def list_results(
    test_type: str = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(30, ge=1, le=100),
    db: Session = Depends(get_db),
    me: User = Depends(get_current_user),
):
    q = db.query(CognitiveTest).filter(CognitiveTest.user_id == me.id)
    if test_type:
        q = q.filter(CognitiveTest.test_type == test_type)
    return q.order_by(CognitiveTest.tested_at.desc()).offset((page - 1) * page_size).limit(page_size).all()


@router.get("/personal-bests")
def personal_bests(
    db: Session = Depends(get_db),
    me: User = Depends(get_current_user),
):
    out = {}
    for t in ["reaction", "digit_span", "memory", "stroop"]:
        # reaction = lower is better, everything else = higher is better
        agg = func.min if t == "reaction" else func.max
        val = db.query(agg(CognitiveTest.score)).filter(
            CognitiveTest.user_id == me.id,
            CognitiveTest.test_type == t,
        ).scalar()
        out[t] = val
    return out


@router.get("/{tid}", response_model=CogTestOut)
def get_result(
    tid: UUID,
    db: Session = Depends(get_db),
    me: User = Depends(get_current_user),
):
    rec = db.query(CognitiveTest).filter(
        CognitiveTest.id == tid,
        CognitiveTest.user_id == me.id,
    ).first()
    if not rec:
        raise HTTPException(status_code=404, detail="test not found")
    return rec
