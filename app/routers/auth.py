from datetime import datetime, timedelta, timezone
import hashlib
import logging
import secrets
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, status
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.deps import get_current_user
from app.core.security import create_access_token, create_refresh_token, decode_refresh_token
from app.database import get_db
from app.models import PasswordResetToken, RefreshToken, User
from app.services.email import send_password_reset_email
from app.schemas import (
    AuthResponse, LoginRequest, MessageResponse, PasswordResetConfirm,
    PasswordResetRequest, PublicUser, RefreshRequest, SignupRequest,
    TokenPair, UsernameCheckResponse,
)

router = APIRouter(prefix="/auth", tags=["Auth"])
logger = logging.getLogger("adchronotype.auth")

_pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Precomputed valid bcrypt hash used for constant-time comparison when an
# account is not found. Keeping this as a real bcrypt hash avoids leaking
# whether an identifier exists through response timing.
_DUMMY_HASH = _pwd.hash("account-not-found-timing-safe-placeholder")
cfg  = get_settings()




def _hash_reset_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _reset_response() -> MessageResponse:
    return MessageResponse(message="If an account exists, reset instructions will be sent shortly.")


def _pub(user: User) -> PublicUser:
    return PublicUser(
        id=user.id,
        firstName=user.first_name,
        lastName=user.last_name,
        username=user.username,
        email=user.email,
    )


def _issue(user: User, db: Session) -> TokenPair:
    access  = create_access_token(str(user.id))
    refresh = create_refresh_token(str(user.id))

    db.add(RefreshToken(
        user_id=user.id,
        token=refresh,
        expires_at=datetime.now(tz=timezone.utc) + timedelta(days=cfg.REFRESH_TOKEN_EXPIRE_DAYS),
    ))
    db.commit()
    return TokenPair(access_token=access, refresh_token=refresh)


@router.post("/signup", response_model=AuthResponse, status_code=201)
def signup(body: SignupRequest, db: Session = Depends(get_db)):
    if db.query(User).filter(User.username == body.username).first():
        raise HTTPException(status_code=409, detail="username already taken")

    if db.query(User).filter(User.email == body.email).first():
        raise HTTPException(status_code=409, detail="email already registered")

    user = User(
        first_name=body.firstName,
        last_name=body.lastName,
        username=body.username,
        email=body.email,
        password_hash=_pwd.hash(body.password),
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    logger.info("user_signed_up user_id=%s username=%s", user.id, user.username)

    return AuthResponse(user=_pub(user), tokens=_issue(user, db))


@router.post("/login", response_model=AuthResponse)
def login(body: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(
        (User.email == body.emailOrUsername) | (User.username == body.emailOrUsername)
    ).first()

    # timing-safe: always run bcrypt even on missing user.
    # Guard against malformed/corrupt stored hashes so a bad hash yields a
    # clean 401 instead of a 500 (passlib raises ValueError on bad hashes).
    try:
        pw_ok = _pwd.verify(body.password, user.password_hash if user else _DUMMY_HASH)
    except ValueError:
        pw_ok = False

    if not user or not pw_ok:
        logger.info("login_failed identifier_type=%s", "email" if "@" in body.emailOrUsername else "username")
        raise HTTPException(status_code=401, detail="incorrect credentials")

    if not user.is_active:
        logger.info("login_blocked_disabled user_id=%s", user.id)
        raise HTTPException(status_code=403, detail="account disabled")

    logger.info("user_logged_in user_id=%s", user.id)
    return AuthResponse(user=_pub(user), tokens=_issue(user, db))


@router.post("/forgot-password", response_model=MessageResponse)
def forgot_password(body: PasswordResetRequest, db: Session = Depends(get_db)):
    identifier = body.emailOrUsername.strip()
    user = db.query(User).filter(
        (User.email == identifier) | (User.username == identifier)
    ).first()

    if not user or not user.is_active:
        logger.info("password_reset_requested missing_or_inactive identifier_type=%s", "email" if "@" in identifier else "username")
        return _reset_response()

    token = secrets.token_urlsafe(32)
    reset_token = PasswordResetToken(
        user_id=user.id,
        token_hash=_hash_reset_token(token),
        expires_at=datetime.now(tz=timezone.utc) + timedelta(minutes=cfg.PASSWORD_RESET_EXPIRE_MINUTES),
    )
    db.add(reset_token)
    db.commit()

    logger.info("password_reset_requested user_id=%s reset_token_id=%s", user.id, reset_token.id)

    if cfg.FRONTEND_APP_URL:
        reset_url = f"{cfg.FRONTEND_APP_URL.rstrip('/')}/reset-password?{urlencode({'token': token})}"
        send_password_reset_email(user.email, reset_url)
    elif not cfg.is_production:
        logger.warning("password_reset_token_dev user_id=%s token=%s", user.id, token)
    else:
        logger.error("password_reset_email_not_sent reason=missing_frontend_app_url user_id=%s", user.id)

    return _reset_response()


@router.post("/reset-password", response_model=MessageResponse)
def reset_password(body: PasswordResetConfirm, db: Session = Depends(get_db)):
    token_hash = _hash_reset_token(body.token)
    now = datetime.now(tz=timezone.utc)

    reset_token = db.query(PasswordResetToken).filter(
        PasswordResetToken.token_hash == token_hash,
        PasswordResetToken.used_at.is_(None),
        PasswordResetToken.expires_at > now,
    ).first()

    if not reset_token:
        logger.info("password_reset_failed invalid_or_expired_token")
        raise HTTPException(status_code=400, detail="invalid or expired reset token")

    user = db.query(User).filter(User.id == reset_token.user_id).first()
    if not user or not user.is_active:
        logger.info("password_reset_failed missing_or_inactive_user token_id=%s", reset_token.id)
        raise HTTPException(status_code=400, detail="invalid or expired reset token")

    user.password_hash = _pwd.hash(body.new_password)
    reset_token.used_at = now

    db.query(RefreshToken).filter(
        RefreshToken.user_id == user.id,
        RefreshToken.revoked.is_(False),
    ).update({"revoked": True}, synchronize_session=False)

    db.commit()
    logger.info("password_reset_completed user_id=%s reset_token_id=%s", user.id, reset_token.id)
    return MessageResponse(message="Password has been reset. Please log in with your new password.")


@router.post("/refresh", response_model=TokenPair)
def refresh_tokens(body: RefreshRequest, db: Session = Depends(get_db)):
    uid = decode_refresh_token(body.refresh_token)
    if not uid:
        raise HTTPException(status_code=401, detail="invalid or expired refresh token")

    stored = db.query(RefreshToken).filter(
        RefreshToken.token == body.refresh_token,
        RefreshToken.revoked.is_(False),
    ).first()

    if not stored:
        raise HTTPException(status_code=401, detail="refresh token revoked")

    # rotate: burn old, issue new
    stored.revoked = True
    db.commit()

    user = db.query(User).filter(User.id == stored.user_id).first()
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="user not found")

    logger.info("token_refreshed user_id=%s", user.id)
    return _issue(user, db)


@router.post("/logout", status_code=204)
def logout(
    body: RefreshRequest,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    row = db.query(RefreshToken).filter(RefreshToken.token == body.refresh_token).first()
    if row and not row.revoked:
        row.revoked = True
        db.commit()
        logger.info("user_logged_out user_id=%s", row.user_id)


@router.get("/check-username", response_model=UsernameCheckResponse)
def check_username(username: str, db: Session = Depends(get_db)):
    taken = db.query(User).filter(User.username == username).first()
    return UsernameCheckResponse(available=taken is None)
