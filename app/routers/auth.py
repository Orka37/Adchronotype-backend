from datetime import datetime, timedelta, timezone
import logging

from fastapi import APIRouter, Depends, HTTPException, status
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.deps import get_current_user
from app.core.security import create_access_token, create_refresh_token, decode_refresh_token
from app.database import get_db
from app.models import RefreshToken, User
from app.schemas import (
    AuthResponse, LoginRequest, PublicUser,
    RefreshRequest, SignupRequest, TokenPair, UsernameCheckResponse,
)

router = APIRouter(prefix="/auth", tags=["Auth"])
logger = logging.getLogger("adchronotype.auth")

_pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Precomputed valid bcrypt hash used for constant-time comparison when a
# username/email is not found. Computed once at import so it is always a
# well-formed bcrypt string (a hand-written placeholder is not, and makes
# passlib raise "malformed bcrypt hash" instead of returning False).
_DUMMY_HASH = _pwd.hash("account-not-found-timing-safe-placeholder")
cfg  = get_settings()


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
    clash = db.query(User).filter(
        (User.email == body.email) | (User.username == body.username)
    ).first()

    if clash:
        raise HTTPException(status_code=409, detail="email or username taken")

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
