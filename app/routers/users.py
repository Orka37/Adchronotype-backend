import logging

from fastapi import APIRouter, Depends, HTTPException
from passlib.context import CryptContext
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.database import get_db
from app.models import (
    CaregiverLink,
    CaregiverMessage,
    CognitiveTest,
    PasswordResetToken,
    Prediction,
    RefreshToken,
    SleepLog,
    User,
)
from app.schemas import ChangePwRequest, PublicUser, UpdatePrivacyRequest, UpdateProfileRequest

router = APIRouter(prefix="/users", tags=["Users"])
_pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")
logger = logging.getLogger("adchronotype.users")


def _pub(u: User) -> PublicUser:
    return PublicUser(
        id=u.id,
        firstName=u.first_name,
        lastName=u.last_name,
        username=u.username,
        email=u.email,
        caregiverSearchEnabled=u.caregiver_search_enabled,
    )


@router.get("/me", response_model=PublicUser)
def get_me(me: User = Depends(get_current_user)):
    return _pub(me)


@router.patch("/me", response_model=PublicUser)
def update_me(
    body: UpdateProfileRequest,
    db: Session = Depends(get_db),
    me: User = Depends(get_current_user),
):
    if body.firstName is not None:
        me.first_name = body.firstName
    if body.lastName is not None:
        me.last_name = body.lastName

    db.commit()
    db.refresh(me)
    logger.info("profile_updated user_id=%s", me.id)
    return _pub(me)


@router.patch("/me/privacy", response_model=PublicUser)
def update_privacy(
    body: UpdatePrivacyRequest,
    db: Session = Depends(get_db),
    me: User = Depends(get_current_user),
):
    me.caregiver_search_enabled = body.caregiverSearchEnabled
    db.commit()
    db.refresh(me)
    logger.info(
        "caregiver_search_preference_updated user_id=%s enabled=%s",
        me.id,
        me.caregiver_search_enabled,
    )
    return _pub(me)


@router.post("/me/change-password", status_code=204)
def change_password(
    body: ChangePwRequest,
    db: Session = Depends(get_db),
    me: User = Depends(get_current_user),
):
    if not _pwd.verify(body.current_password, me.password_hash):
        raise HTTPException(status_code=400, detail="current password is wrong")

    me.password_hash = _pwd.hash(body.new_password)
    db.commit()
    logger.info("password_changed user_id=%s", me.id)


@router.delete("/me", status_code=204)
def delete_me(
    db: Session = Depends(get_db),
    me: User = Depends(get_current_user),
):
    user_id = me.id

    try:
        related_links = db.query(CaregiverLink.id).filter(
            or_(
                CaregiverLink.patient_id == user_id,
                CaregiverLink.caregiver_id == user_id,
            )
        ).all()
        related_link_ids = [row.id for row in related_links]

        if related_link_ids:
            db.query(CaregiverMessage).filter(
                CaregiverMessage.link_id.in_(related_link_ids)
            ).delete(synchronize_session=False)

        db.query(CaregiverMessage).filter(
            or_(
                CaregiverMessage.sender_id == user_id,
                CaregiverMessage.recipient_id == user_id,
            )
        ).delete(synchronize_session=False)

        db.query(CaregiverLink).filter(
            or_(
                CaregiverLink.patient_id == user_id,
                CaregiverLink.caregiver_id == user_id,
            )
        ).delete(synchronize_session=False)

        for model in (
            CognitiveTest,
            PasswordResetToken,
            Prediction,
            RefreshToken,
            SleepLog,
        ):
            db.query(model).filter(model.user_id == user_id).delete(synchronize_session=False)

        db.delete(me)
        db.commit()
        logger.info("account_deleted user_id=%s", user_id)
    except Exception:
        db.rollback()
        logger.exception("account_delete_failed user_id=%s", user_id)
        raise
