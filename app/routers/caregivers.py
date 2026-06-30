from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.database import get_db
from app.models import CaregiverLink, User
from app.schemas import CaregiverInvite, CaregiverLinkOut

router = APIRouter(prefix="/caregivers", tags=["Caregivers"])


@router.post("/invite", response_model=CaregiverLinkOut, status_code=201)
def invite(
    body: CaregiverInvite,
    db: Session = Depends(get_db),
    me: User = Depends(get_current_user),
):
    # block duplicate active/pending invites to the same address
    already = db.query(CaregiverLink).filter(
        CaregiverLink.patient_id == me.id,
        CaregiverLink.invited_email == body.caregiver_email,
        CaregiverLink.status.in_(["pending", "active"]),
    ).first()

    if already:
        raise HTTPException(status_code=409, detail="invite already sent to this email")

    cg_user = db.query(User).filter(User.email == body.caregiver_email).first()

    link = CaregiverLink(
        patient_id=me.id,
        caregiver_id=cg_user.id if cg_user else None,
        invited_email=body.caregiver_email,
        # if they're already registered, go straight to active
        status="active" if cg_user else "pending",
    )
    db.add(link)
    db.commit()
    db.refresh(link)
    return link


@router.get("", response_model=List[CaregiverLinkOut])
def my_caregivers(
    db: Session = Depends(get_db),
    me: User = Depends(get_current_user),
):
    return db.query(CaregiverLink).filter(
        CaregiverLink.patient_id == me.id,
        CaregiverLink.status != "revoked",
    ).all()


@router.get("/patients", response_model=List[CaregiverLinkOut])
def my_patients(
    db: Session = Depends(get_db),
    me: User = Depends(get_current_user),
):
    return db.query(CaregiverLink).filter(
        CaregiverLink.caregiver_id == me.id,
        CaregiverLink.status == "active",
    ).all()


@router.delete("/{link_id}", status_code=204)
def revoke(
    link_id: UUID,
    db: Session = Depends(get_db),
    me: User = Depends(get_current_user),
):
    link = db.query(CaregiverLink).filter(
        CaregiverLink.id == link_id,
        CaregiverLink.patient_id == me.id,
    ).first()

    if not link:
        raise HTTPException(status_code=404, detail="link not found")

    link.status = "revoked"
    db.commit()
