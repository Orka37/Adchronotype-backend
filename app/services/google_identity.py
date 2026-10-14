from fastapi import HTTPException
from google.auth.exceptions import GoogleAuthError, TransportError
from google.auth.transport.requests import Request
from google.oauth2 import id_token


def verify_google_identity(token: str, audience: str) -> dict:
    if not audience:
        raise HTTPException(503, "Google sign-in is not available yet. Use email and password.")
    try:
        claims = id_token.verify_oauth2_token(token, Request(), audience=audience)
    except TransportError:
        raise HTTPException(503, "Google sign-in is temporarily unavailable. Please try again.")
    except (ValueError, GoogleAuthError):
        raise HTTPException(401, "Invalid or expired Google sign-in. Please try again.")
    if (claims.get("iss") not in ("accounts.google.com", "https://accounts.google.com")
            or claims.get("aud") != audience
            or not isinstance(claims.get("sub"), str) or not 0 < len(claims["sub"]) <= 255
            or claims.get("email_verified") is not True
            or not isinstance(claims.get("email"), str)
            or not 3 <= len(claims["email"]) <= 255 or "@" not in claims["email"]):
        raise HTTPException(401, "Google could not verify this account.")
    return claims
