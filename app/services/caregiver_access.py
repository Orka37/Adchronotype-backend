from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models import CarePatient, CarePatientMember, User


def require_active_member(db: Session, patient_id: UUID, user: User) -> tuple[CarePatient, CarePatientMember]:
    patient = db.query(CarePatient).filter(CarePatient.id == patient_id).first()
    if not patient:
        raise HTTPException(status_code=404, detail="patient record not found")
    member = db.query(CarePatientMember).filter(
        CarePatientMember.patient_id == patient_id,
        CarePatientMember.user_id == user.id,
        CarePatientMember.status == "active",
    ).first()
    if not member:
        raise HTTPException(status_code=403, detail="active patient access required")
    return patient, member


def require_primary(db: Session, patient_id: UUID, user: User) -> tuple[CarePatient, CarePatientMember]:
    patient, member = require_active_member(db, patient_id, user)
    if member.role != "primary" or patient.primary_caregiver_id != user.id:
        raise HTTPException(status_code=403, detail="primary caregiver access required")
    return patient, member
