from typing import List
import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.database import get_db
from app.models import Prediction, User
from app.schemas import PredictRequest, PredictResponse, FactorContributions
from app.services.prediction_service import risk_label_for_score, run_prediction

router = APIRouter(prefix="/predictions", tags=["Predictions"])
logger = logging.getLogger("adchronotype.predictions")


def _response_from_prediction(row: Prediction) -> PredictResponse:
    body = PredictRequest(
        age=row.age,
        bmi=row.bmi,
        ethnicity=row.ethnicity,
        chronotype=row.chronotype,
        family_history=row.family_history,
        sleep_time=row.sleep_time,
        wake_time=row.wake_time,
        sleep_duration=row.sleep_duration,
    )
    result = run_prediction(body)

    return PredictResponse(
        prediction=row.prediction_value,
        risk_label=risk_label_for_score(row.prediction_value),
        message="",
        prediction_id=row.id,
        age=row.age,
        bmi=row.bmi,
        ethnicity=row.ethnicity,
        chronotype=row.chronotype,
        family_history=row.family_history,
        sleep_time=row.sleep_time,
        wake_time=row.wake_time,
        sleep_duration=row.sleep_duration,
        baseline=result["baseline"],
        factor_contributions=FactorContributions(**result["factor_contributions"]),
    )


@router.post("", response_model=PredictResponse, status_code=201)
def predict(
    body: PredictRequest,
    db: Session = Depends(get_db),
    me: User = Depends(get_current_user),
):
    result = run_prediction(body)

    score    = result["score"]
    label    = result["risk_label"]
    baseline = result["baseline"]
    fc       = result["factor_contributions"]

    rec = Prediction(
        user_id=me.id,
        age=body.age,
        bmi=body.bmi,
        sleep_duration=body.sleep_duration,
        sleep_time=body.sleep_time,
        wake_time=body.wake_time,
        chronotype=body.chronotype,
        ethnicity=body.ethnicity,
        family_history=body.family_history,
        prediction_value=score,
    )
    db.add(rec)
    db.commit()
    db.refresh(rec)

    logger.info(
        "prediction_created user_id=%s prediction_id=%s score=%s risk=%s",
        me.id,
        rec.id,
        score,
        label,
    )

    return PredictResponse(
        prediction=score,
        risk_label=label,
        message="score generated",
        prediction_id=rec.id,
        age=body.age,
        bmi=body.bmi,
        ethnicity=body.ethnicity,
        chronotype=body.chronotype,
        family_history=body.family_history,
        sleep_time=body.sleep_time,
        wake_time=body.wake_time,
        sleep_duration=body.sleep_duration,
        baseline=baseline,
        factor_contributions=FactorContributions(**fc),
    )


@router.get("", response_model=List[PredictResponse])
def list_predictions(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    me: User = Depends(get_current_user),
):
    rows = (
        db.query(Prediction)
        .filter(Prediction.user_id == me.id)
        .order_by(Prediction.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return [_response_from_prediction(row) for row in rows]


@router.get("/{pid}", response_model=PredictResponse)
def get_prediction(
    pid: str,
    db: Session = Depends(get_db),
    me: User = Depends(get_current_user),
):
    rec = db.query(Prediction).filter(
        Prediction.id == pid,
        Prediction.user_id == me.id,
    ).first()

    if not rec:
        raise HTTPException(status_code=404, detail="prediction not found")

    return _response_from_prediction(rec)
