import json
import logging
from urllib import error, request

from app.core.config import get_settings

logger = logging.getLogger("adchronotype.email")


def send_password_reset_email(to_email: str, reset_url: str) -> bool:
    settings = get_settings()
    if not settings.RESEND_API_KEY or not settings.PASSWORD_RESET_FROM_EMAIL:
        logger.warning("password_reset_email_skipped reason=missing_resend_config")
        return False

    payload = {
        "from": settings.PASSWORD_RESET_FROM_EMAIL,
        "to": [to_email],
        "subject": "Reset your ADChronotype password",
        "html": (
            "<p>Hello,</p>"
            "<p>We received a request to reset your ADChronotype password.</p>"
            f"<p><a href=\"{reset_url}\">Reset your password</a></p>"
            "<p>This link expires soon. If you did not request this, you can ignore this email.</p>"
        ),
        "text": (
            "We received a request to reset your ADChronotype password.\n\n"
            f"Reset your password: {reset_url}\n\n"
            "If you did not request this, you can ignore this email."
        ),
    }

    req = request.Request(
        "https://api.resend.com/emails",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {settings.RESEND_API_KEY}",
            "Content-Type": "application/json",
            "User-Agent": "ADChronotype/1.0 (password-reset)",
        },
        method="POST",
    )

    try:
        with request.urlopen(req, timeout=10) as res:
            ok = 200 <= res.status < 300
            if ok:
                logger.info("password_reset_email_sent")
            else:
                logger.warning("password_reset_email_failed status=%s", res.status)
            return ok
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        logger.error("password_reset_email_failed status=%s body=%s", exc.code, body)
    except Exception as exc:
        logger.error("password_reset_email_failed error=%s", exc)

    return False
