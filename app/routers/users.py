import logging

from fastapi import APIRouter, Depends, HTTPException
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.database import get_db
from app.models import User
from app.schemas import ChangePwRequest, PublicUser, UpdateProfileRequest

router = APIRouter(prefix="/users", tags=["Users"])
_pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")
logger = logging.getLogger("adchronotype.users")


def _pub(u: User) -> PublicUser:
    return PublicUser(id=u.id, firstName=u.first_name, lastName=u.last_name,
                      username=u.username, email=u.email)


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
