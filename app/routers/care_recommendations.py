"""Authenticated database integration of the supplied caregiver rules."""
from datetime import datetime, timedelta, timezone
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session
from app.core.deps import get_current_user
from app.database import get_db
from app.models import CarePatientEvent, User
from app.services.caregiver_access import require_active_member
from app.services.care_recommendations import (
    CalmConfig, CalmReport, CircadianConfig, CircadianPlan, LogEntry,
    build_circadian_plan, detect_calm_windows,
)

router = APIRouter(tags=["Caregiver recommendations"])
EVENT_MAP = {"slept": "sleep", "woke": "wake", "napped": "nap_start", "agitated": "agitation"}


class RecommendationRequest(BaseModel):
    timezone: str = Field(min_length=1, max_length=100)
    lookback_days: int = Field(14, ge=1, le=90)
    circadian_config: CircadianConfig | None = None
    calm_config: CalmConfig | None = None

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value):
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError("Use a valid IANA time zone, such as America/Chicago")
        return value


def fetch_patient_logs(db: Session, patient_id: UUID, body: RecommendationRequest) -> list[LogEntry]:
    """Caller checks membership first. Legacy naive timestamps are UTC.

    Read the requested history independently of the UI's 250-row limit.
    """
    now = datetime.now(timezone.utc)
    rows = db.query(CarePatientEvent).filter(
        CarePatientEvent.patient_id == patient_id,
        CarePatientEvent.event_type.in_(EVENT_MAP),
        CarePatientEvent.event_time >= now - timedelta(days=body.lookback_days),
        CarePatientEvent.event_time <= now,
    ).order_by(CarePatientEvent.event_time).limit(10001).all()
    if len(rows) > 10000:
        raise HTTPException(422, "Too many logs; choose a shorter lookback period")
    zone = ZoneInfo(body.timezone)
    return [LogEntry(
        patient_id=str(patient_id), type=EVENT_MAP[row.event_type],
        timestamp=(row.event_time if row.event_time.tzinfo else row.event_time.replace(tzinfo=timezone.utc)).astimezone(zone),
        duration_min=row.duration_min, note=row.note,
    ) for row in rows]


@router.post("/circadian-plan/by-id/{patient_id}", response_model=CircadianPlan)
def circadian_plan_by_id(patient_id: UUID, body: RecommendationRequest,
                         db: Session = Depends(get_db), me: User = Depends(get_current_user)):
    require_active_member(db, patient_id, me)
    return build_circadian_plan(fetch_patient_logs(db, patient_id, body), body.circadian_config or CircadianConfig())


@router.post("/calm-windows/by-id/{patient_id}", response_model=CalmReport)
def calm_windows_by_id(patient_id: UUID, body: RecommendationRequest,
                       db: Session = Depends(get_db), me: User = Depends(get_current_user)):
    require_active_member(db, patient_id, me)
    return detect_calm_windows(fetch_patient_logs(db, patient_id, body), body.calm_config or CalmConfig())
