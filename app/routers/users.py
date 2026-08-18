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
    LegalConsent,
    PasswordResetToken,
    Prediction,
    RefreshToken,
    SleepLog,
    User,
)
from app.schemas import (
    ChangePwRequest,
    LegalConsentOut,
    LegalConsentRequest,
    PublicUser,
    UpdatePrivacyRequest,
    UpdateProfileRequest,
)

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


def _legal_consent(row: LegalConsent) -> LegalConsentOut:
    return LegalConsentOut(
        id=row.id,
        termsVersion=row.terms_version,
        privacyVersion=row.privacy_version,
        platform=row.platform,
        appVersion=row.app_version,
        acceptedAt=row.accepted_at,
    )


@router.get("/me", response_model=PublicUser)
def get_me(me: User = Depends(get_current_user)):
    return _pub(me)


@router.get("/me/legal-consent", response_model=LegalConsentOut | None)
def get_legal_consent(
    db: Session = Depends(get_db),
    me: User = Depends(get_current_user),
):
    row = (
        db.query(LegalConsent)
        .filter(LegalConsent.user_id == me.id)
        .order_by(LegalConsent.accepted_at.desc())
        .first()
    )
    return _legal_consent(row) if row else None


@router.post("/me/legal-consent", response_model=LegalConsentOut, status_code=201)
def record_legal_consent(
    body: LegalConsentRequest,
    db: Session = Depends(get_db),
    me: User = Depends(get_current_user),
):
    row = db.query(LegalConsent).filter(
        LegalConsent.user_id == me.id,
        LegalConsent.terms_version == body.termsVersion,
        LegalConsent.privacy_version == body.privacyVersion,
    ).first()
    if row:
        return _legal_consent(row)

    row = LegalConsent(
        user_id=me.id,
        terms_version=body.termsVersion,
        privacy_version=body.privacyVersion,
        platform=body.platform,
        app_version=body.appVersion,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    logger.info(
        "legal_consent_recorded user_id=%s terms_version=%s privacy_version=%s",
        me.id,
        body.termsVersion,
        body.privacyVersion,
    )
    return _legal_consent(row)


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
            LegalConsent,
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
