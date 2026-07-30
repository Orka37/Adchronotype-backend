from datetime import datetime, timedelta, timezone
import secrets
from typing import Optional

from jose import JWTError, jwt

from app.core.config import get_settings

cfg = get_settings()

_ACCESS  = "access"
_REFRESH = "refresh"


def _make_token(uid: str, kind: str, ttl: timedelta) -> str:
    now = datetime.now(tz=timezone.utc)
    claims = {
        "sub":  uid,
        "type": kind,
        "iat":  now,
        "exp":  now + ttl,
        "jti":  secrets.token_urlsafe(16),
    }
    return jwt.encode(claims, cfg.JWT_SECRET_KEY, algorithm=cfg.JWT_ALGORITHM)


def create_access_token(uid: str) -> str:
    return _make_token(uid, _ACCESS, timedelta(minutes=cfg.ACCESS_TOKEN_EXPIRE_MINUTES))


def create_refresh_token(uid: str) -> str:
    return _make_token(uid, _REFRESH, timedelta(days=cfg.REFRESH_TOKEN_EXPIRE_DAYS))


def _decode(token: str, expected: str) -> Optional[str]:
    try:
        data = jwt.decode(token, cfg.JWT_SECRET_KEY, algorithms=[cfg.JWT_ALGORITHM])
    except JWTError:
        return None

    # extra check — refresh tokens must not work as access tokens and vice versa
    if data.get("type") != expected:
        return None

    return data.get("sub")


def decode_access_token(token: str) -> Optional[str]:
    return _decode(token, _ACCESS)


def decode_refresh_token(token: str) -> Optional[str]:
    return _decode(token, _REFRESH)
