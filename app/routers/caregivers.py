from typing import List
import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.database import get_db
from app.models import CaregiverLink, CaregiverMessage, CognitiveTest, Prediction, User
from app.routers.predictions import _response_from_prediction
from app.schemas import (
    CaregiverInvite,
    CaregiverLinkOut,
    CaregiverMessageCreate,
    CaregiverMessageOut,
    CaregiverRequestCreate,
    CaregiverSearchResult,
    CaregiverStatsOut,
    CaregiverUserOut,
)

router = APIRouter(prefix="/caregivers", tags=["Caregivers"])
logger = logging.getLogger("adchronotype.caregivers")

ACCEPTED_STATUS = "accepted"
CONNECTED_STATUSES = ("accepted", "active")
ACTIVE_STATUSES = ("pending", "accepted", "active")
PREBUILT_MESSAGES = {
    "sleep_log_reminder": "Please update your sleep log today.",
    "doctor_report_reminder": "Please review your latest doctor report.",
    "cognitive_test_reminder": "Please complete your cognitive tests when you have time.",
    "score_check_in": "Your latest score is ready to review.",
    "great_progress": "Great job staying consistent with your tracking.",
    "general_check_in": "I am checking in and hope you are doing well.",
}


def _user_out(user: User) -> CaregiverUserOut:
    return CaregiverUserOut(
        id=user.id,
        firstName=user.first_name,
        lastName=user.last_name,
        username=user.username,
    )


def _link_out(link: CaregiverLink, me: User, db: Session) -> CaregiverLinkOut:
    other_id = link.caregiver_id if link.patient_id == me.id else link.patient_id
    other_user = db.query(User).filter(User.id == other_id).first() if other_id else None
    return CaregiverLinkOut(
        id=link.id,
        patient_id=link.patient_id,
        caregiver_id=link.caregiver_id,
        invited_email=link.invited_email,
        status=link.status,
        created_at=link.created_at,
        other_user=_user_out(other_user) if other_user else None,
    )


def _existing_link(db: Session, user_a, user_b):
    return db.query(CaregiverLink).filter(
        or_(
            and_(CaregiverLink.caregiver_id == user_a, CaregiverLink.patient_id == user_b),
            and_(CaregiverLink.caregiver_id == user_b, CaregiverLink.patient_id == user_a),
        ),
        CaregiverLink.status.in_(ACTIVE_STATUSES),
    ).first()


def _accepted_link(db: Session, me: User, other_user_id: UUID):
    return db.query(CaregiverLink).filter(
        or_(
            and_(CaregiverLink.caregiver_id == me.id, CaregiverLink.patient_id == other_user_id),
            and_(CaregiverLink.patient_id == me.id, CaregiverLink.caregiver_id == other_user_id),
        ),
        CaregiverLink.status.in_(CONNECTED_STATUSES),
    ).first()


def _personal_bests(db: Session, user_id):
    bests = {}
    for test_type in ["reaction", "digit_span", "memory", "stroop"]:
        rows = db.query(CognitiveTest).filter(
            CognitiveTest.user_id == user_id,
            CognitiveTest.test_type == test_type,
        ).all()
        if not rows:
            bests[test_type] = None
            continue
        bests[test_type] = min(row.score for row in rows) if test_type == "reaction" else max(row.score for row in rows)
    return bests


@router.get("/search", response_model=List[CaregiverSearchResult])
def search_users(
    username: str = Query(..., min_length=2, max_length=50),
    db: Session = Depends(get_db),
    me: User = Depends(get_current_user),
):
    query = username.strip()
    rows = db.query(User).filter(
        User.id != me.id,
        User.caregiver_search_enabled.is_(True),
        User.username.ilike(f"%{query}%"),
    ).order_by(User.username.asc()).limit(10).all()

    results = []
    for user in rows:
        link = _existing_link(db, me.id, user.id)
        results.append(CaregiverSearchResult(
            **_user_out(user).model_dump(),
            request_status=link.status if link else None,
        ))
    logger.info("caregiver_search user_id=%s query=%s results=%s", me.id, query, len(results))
    return results


@router.post("/requests", response_model=CaregiverLinkOut, status_code=201)
def send_request(
    body: CaregiverRequestCreate,
    db: Session = Depends(get_db),
    me: User = Depends(get_current_user),
):
    target = db.query(User).filter(User.username == body.username).first()
    if not target or not target.caregiver_search_enabled:
        raise HTTPException(status_code=404, detail="user not found")
    if target.id == me.id:
        raise HTTPException(status_code=400, detail="you cannot send a request to yourself")
    if _existing_link(db, me.id, target.id):
        raise HTTPException(status_code=409, detail="request or connection already exists")

    link = CaregiverLink(
        caregiver_id=me.id,
        patient_id=target.id,
        invited_email=target.email,
        status="pending",
    )
    db.add(link)
    db.commit()
    db.refresh(link)
    logger.info("caregiver_request_sent from_user_id=%s to_user_id=%s link_id=%s", me.id, target.id, link.id)
    return _link_out(link, me, db)


@router.get("/requests/incoming", response_model=List[CaregiverLinkOut])
def incoming_requests(
    db: Session = Depends(get_db),
    me: User = Depends(get_current_user),
):
    rows = db.query(CaregiverLink).filter(
        CaregiverLink.patient_id == me.id,
        CaregiverLink.status == "pending",
    ).order_by(CaregiverLink.created_at.desc()).all()
    return [_link_out(row, me, db) for row in rows]


@router.get("/requests/outgoing", response_model=List[CaregiverLinkOut])
def outgoing_requests(
    db: Session = Depends(get_db),
    me: User = Depends(get_current_user),
):
    rows = db.query(CaregiverLink).filter(
        CaregiverLink.caregiver_id == me.id,
        CaregiverLink.status == "pending",
    ).order_by(CaregiverLink.created_at.desc()).all()
    return [_link_out(row, me, db) for row in rows]


@router.post("/requests/{link_id}/accept", response_model=CaregiverLinkOut)
def accept_request(
    link_id: UUID,
    db: Session = Depends(get_db),
    me: User = Depends(get_current_user),
):
    link = db.query(CaregiverLink).filter(
        CaregiverLink.id == link_id,
        CaregiverLink.patient_id == me.id,
        CaregiverLink.status == "pending",
    ).first()
    if not link:
        raise HTTPException(status_code=404, detail="request not found")

    link.status = ACCEPTED_STATUS
    db.commit()
    db.refresh(link)
    logger.info("caregiver_request_accepted user_id=%s link_id=%s", me.id, link.id)
    return _link_out(link, me, db)


@router.post("/requests/{link_id}/reject", response_model=CaregiverLinkOut)
def reject_request(
    link_id: UUID,
    db: Session = Depends(get_db),
    me: User = Depends(get_current_user),
):
    link = db.query(CaregiverLink).filter(
        CaregiverLink.id == link_id,
        CaregiverLink.patient_id == me.id,
        CaregiverLink.status == "pending",
    ).first()
    if not link:
        raise HTTPException(status_code=404, detail="request not found")

    link.status = "rejected"
    db.commit()
    db.refresh(link)
    logger.info("caregiver_request_rejected user_id=%s link_id=%s", me.id, link.id)
    return _link_out(link, me, db)


@router.get("/connections", response_model=List[CaregiverLinkOut])
def connections(
    db: Session = Depends(get_db),
    me: User = Depends(get_current_user),
):
    rows = db.query(CaregiverLink).filter(
        or_(CaregiverLink.patient_id == me.id, CaregiverLink.caregiver_id == me.id),
        CaregiverLink.status.in_(CONNECTED_STATUSES),
    ).order_by(CaregiverLink.created_at.desc()).all()
    return [_link_out(row, me, db) for row in rows]


@router.get("/connections/{user_id}/stats", response_model=CaregiverStatsOut)
def connection_stats(
    user_id: UUID,
    db: Session = Depends(get_db),
    me: User = Depends(get_current_user),
):
    link = _accepted_link(db, me, user_id)
    if not link:
        raise HTTPException(status_code=403, detail="accepted connection required")

    other = db.query(User).filter(User.id == user_id).first()
    if not other:
        raise HTTPException(status_code=404, detail="user not found")

    latest = db.query(Prediction).filter(Prediction.user_id == user_id).order_by(Prediction.created_at.desc()).first()
    cognitive = db.query(CognitiveTest).filter(CognitiveTest.user_id == user_id).order_by(CognitiveTest.tested_at.desc()).limit(12).all()
    logger.info("caregiver_stats_viewed viewer_id=%s subject_id=%s", me.id, user_id)
    return CaregiverStatsOut(
        user=_user_out(other),
        latest_prediction=_response_from_prediction(latest) if latest else None,
        cognitive_tests=cognitive,
        personal_bests=_personal_bests(db, user_id),
    )


@router.post("/connections/{user_id}/messages", response_model=CaregiverMessageOut, status_code=201)
def send_message(
    user_id: UUID,
    body: CaregiverMessageCreate,
    db: Session = Depends(get_db),
    me: User = Depends(get_current_user),
):
    link = _accepted_link(db, me, user_id)
    if not link:
        raise HTTPException(status_code=403, detail="accepted connection required")
    if body.message_key not in PREBUILT_MESSAGES:
        raise HTTPException(status_code=422, detail="unsupported message")

    msg = CaregiverMessage(
        link_id=link.id,
        sender_id=me.id,
        recipient_id=user_id,
        message_key=body.message_key,
        message_text=PREBUILT_MESSAGES[body.message_key],
    )
    db.add(msg)
    db.commit()
    db.refresh(msg)
    logger.info("caregiver_message_sent sender_id=%s recipient_id=%s message_key=%s", me.id, user_id, body.message_key)
    return msg


@router.get("/connections/{user_id}/messages", response_model=List[CaregiverMessageOut])
def messages(
    user_id: UUID,
    db: Session = Depends(get_db),
    me: User = Depends(get_current_user),
):
    link = _accepted_link(db, me, user_id)
    if not link:
        raise HTTPException(status_code=403, detail="accepted connection required")
    return db.query(CaregiverMessage).filter(
        CaregiverMessage.link_id == link.id,
    ).order_by(CaregiverMessage.created_at.desc()).limit(50).all()


@router.post("/invite", response_model=CaregiverLinkOut, status_code=201)
def invite(
    body: CaregiverInvite,
    db: Session = Depends(get_db),
    me: User = Depends(get_current_user),
):
    already = db.query(CaregiverLink).filter(
        CaregiverLink.patient_id == me.id,
        CaregiverLink.invited_email == body.caregiver_email,
        CaregiverLink.status.in_(ACTIVE_STATUSES),
    ).first()
    if already:
        raise HTTPException(status_code=409, detail="invite already sent to this email")

    cg_user = db.query(User).filter(User.email == body.caregiver_email).first()
    link = CaregiverLink(
        patient_id=me.id,
        caregiver_id=cg_user.id if cg_user else None,
        invited_email=body.caregiver_email,
        status=ACCEPTED_STATUS if cg_user else "pending",
    )
    db.add(link)
    db.commit()
    db.refresh(link)
    logger.info("caregiver_email_invite_created patient_id=%s link_id=%s status=%s", me.id, link.id, link.status)
    return _link_out(link, me, db)


@router.get("", response_model=List[CaregiverLinkOut])
def my_caregivers(
    db: Session = Depends(get_db),
    me: User = Depends(get_current_user),
):
    rows = db.query(CaregiverLink).filter(
        CaregiverLink.patient_id == me.id,
        CaregiverLink.status != "revoked",
    ).all()
    return [_link_out(row, me, db) for row in rows]


@router.get("/patients", response_model=List[CaregiverLinkOut])
def my_patients(
    db: Session = Depends(get_db),
    me: User = Depends(get_current_user),
):
    rows = db.query(CaregiverLink).filter(
        CaregiverLink.caregiver_id == me.id,
        CaregiverLink.status.in_(CONNECTED_STATUSES),
    ).all()
    return [_link_out(row, me, db) for row in rows]


@router.delete("/{link_id}", status_code=204)
def revoke(
    link_id: UUID,
    db: Session = Depends(get_db),
    me: User = Depends(get_current_user),
):
    link = db.query(CaregiverLink).filter(
        CaregiverLink.id == link_id,
        or_(CaregiverLink.patient_id == me.id, CaregiverLink.caregiver_id == me.id),
    ).first()
    if not link:
        raise HTTPException(status_code=404, detail="link not found")

    link.status = "revoked"
    db.commit()
    logger.info("caregiver_link_revoked user_id=%s link_id=%s", me.id, link_id)
