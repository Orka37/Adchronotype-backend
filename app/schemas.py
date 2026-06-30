from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field, field_validator


# ── auth ──────────────────────────────────────────────────────────

class SignupRequest(BaseModel):
    firstName: str = Field(..., min_length=1, max_length=100)
    lastName:  str = Field(..., min_length=1, max_length=100)
    username:  str = Field(..., min_length=3, max_length=50, pattern=r"^[a-zA-Z0-9_]+$")
    email:     EmailStr
    password:  str = Field(..., min_length=8, max_length=128)


class LoginRequest(BaseModel):
    emailOrUsername: str = Field(..., min_length=3)
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


class TokenPair(BaseModel):
    access_token:  str
    refresh_token: str
    token_type:    str = "bearer"


class PublicUser(BaseModel):
    id:        UUID
    firstName: str
    lastName:  str
    username:  str
    email:     str

    model_config = {"from_attributes": True}


class AuthResponse(BaseModel):
    user:   PublicUser
    tokens: TokenPair


class UsernameCheckResponse(BaseModel):
    available: bool


# ── user profile ──────────────────────────────────────────────────

class UpdateProfileRequest(BaseModel):
    firstName: Optional[str] = Field(None, min_length=1, max_length=100)
    lastName:  Optional[str] = Field(None, min_length=1, max_length=100)


class ChangePwRequest(BaseModel):
    current_password: str
    new_password: str = Field(..., min_length=8, max_length=128)


# ── predictions ───────────────────────────────────────────────────

class PredictRequest(BaseModel):
    age:            int   = Field(..., ge=18, le=120)
    bmi:            float = Field(..., ge=10.0, le=70.0)
    ethnicity:      str
    chronotype:     str
    family_history: str
    sleep_time:     str   = Field(..., pattern=r"^\d{2}:\d{2}$")
    wake_time:      str   = Field(..., pattern=r"^\d{2}:\d{2}$")
    sleep_duration: float = Field(..., ge=0.0, le=24.0)


class PredictResponse(BaseModel):
    prediction:    float
    risk_label:    str
    message:       str
    prediction_id: UUID


# ── sleep logs ────────────────────────────────────────────────────

class SleepLogIn(BaseModel):
    sleep_time:     str     = Field(..., pattern=r"^\d{2}:\d{2}$")
    wake_time:      str     = Field(..., pattern=r"^\d{2}:\d{2}$")
    duration_hours: float   = Field(..., ge=0.0, le=24.0)
    quality_score:  int     = Field(..., ge=1, le=5)
    awakenings:     int     = Field(0, ge=0, le=20)
    notes:          Optional[str] = Field(None, max_length=500)
    logged_date:    datetime


class SleepLogOut(BaseModel):
    id:             UUID
    sleep_time:     str
    wake_time:      str
    duration_hours: float
    quality_score:  int
    awakenings:     int
    notes:          Optional[str]
    logged_date:    datetime
    created_at:     datetime

    model_config = {"from_attributes": True}


# ── cognitive tests ───────────────────────────────────────────────

_VALID_TESTS = {"reaction", "digit_span", "memory", "stroop"}


class CogTestIn(BaseModel):
    test_type:        str
    score:            float = Field(..., ge=0.0)
    unit:             str
    duration_seconds: Optional[float] = Field(None, ge=0.0)
    tested_at:        datetime

    @field_validator("test_type")
    @classmethod
    def check_type(cls, v):
        if v not in _VALID_TESTS:
            raise ValueError(f"must be one of {sorted(_VALID_TESTS)}")
        return v


class CogTestOut(BaseModel):
    id:               UUID
    test_type:        str
    score:            float
    unit:             str
    duration_seconds: Optional[float]
    tested_at:        datetime
    created_at:       datetime

    model_config = {"from_attributes": True}


# ── caregivers ────────────────────────────────────────────────────

class CaregiverInvite(BaseModel):
    caregiver_email: EmailStr


class CaregiverLinkOut(BaseModel):
    id:            UUID
    patient_id:    UUID
    caregiver_id:  Optional[UUID]
    invited_email: Optional[str]
    status:        str
    created_at:    datetime

    model_config = {"from_attributes": True}
