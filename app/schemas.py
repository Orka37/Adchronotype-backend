from datetime import datetime
from typing import Optional, List
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
    caregiverSearchEnabled: bool = False

    model_config = {"from_attributes": True}


class AuthResponse(BaseModel):
    user:   PublicUser
    tokens: TokenPair


class UsernameCheckResponse(BaseModel):
    available: bool


class PasswordResetRequest(BaseModel):
    emailOrUsername: str = Field(..., min_length=3, max_length=255)


class PasswordResetConfirm(BaseModel):
    token: str = Field(..., min_length=20, max_length=256)
    new_password: str = Field(..., min_length=8, max_length=128)


class MessageResponse(BaseModel):
    message: str


# ── user profile ──────────────────────────────────────────────────

class UpdateProfileRequest(BaseModel):
    firstName: Optional[str] = Field(None, min_length=1, max_length=100)
    lastName:  Optional[str] = Field(None, min_length=1, max_length=100)


class UpdatePrivacyRequest(BaseModel):
    caregiverSearchEnabled: bool


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


class FactorContributions(BaseModel):
    chronotype: float
    age:        float
    bmi:        float
    sleep_time: float
    wake_time:  float
    ethnicity:  float


class PredictResponse(BaseModel):
    prediction:           float
    risk_label:           str
    message:              str
    prediction_id:        UUID
    age:                  int
    bmi:                  float
    ethnicity:            str
    chronotype:           str
    family_history:       str
    sleep_time:           str
    wake_time:            str
    sleep_duration:       float
    baseline:             Optional[float] = None
    factor_contributions: Optional[FactorContributions] = None


# ── sleep logs ────────────────────────────────────────────────────

class SleepLogIn(BaseModel):
    sleep_time:     str     = Field(..., pattern=r"^\d{2}:\d{2}$")
    wake_time:      str     = Field(..., pattern=r"^\d{2}:\d{2}$")
    duration_hours: float   = Field(..., ge=0.0, le=24.0)
    quality_score:  int     = Field(..., ge=0, le=21)
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
    attempt_number:   int = Field(1, ge=1)
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
    attempt_number:   int
    score:            float
    unit:             str
    duration_seconds: Optional[float]
    tested_at:        datetime
    created_at:       datetime

    model_config = {"from_attributes": True}


# ── caregivers ────────────────────────────────────────────────────

class CaregiverInvite(BaseModel):
    caregiver_email: EmailStr


class CaregiverUserOut(BaseModel):
    id: UUID
    firstName: str
    lastName: str
    username: str


class CaregiverSearchResult(CaregiverUserOut):
    request_status: Optional[str] = None


class CaregiverRequestCreate(BaseModel):
    username: str = Field(..., min_length=3, max_length=50)


class CaregiverLinkOut(BaseModel):
    id:            UUID
    patient_id:    UUID
    caregiver_id:  Optional[UUID]
    invited_email: Optional[str]
    status:        str
    created_at:    datetime
    other_user:    Optional[CaregiverUserOut] = None

    model_config = {"from_attributes": True}


class CaregiverStatsOut(BaseModel):
    user: CaregiverUserOut
    latest_prediction: Optional[PredictResponse] = None
    cognitive_tests: List[CogTestOut] = Field(default_factory=list)
    personal_bests: dict = Field(default_factory=dict)


class CaregiverMessageCreate(BaseModel):
    message_key: str = Field(..., min_length=3, max_length=50)


class CaregiverMessageOut(BaseModel):
    id: UUID
    link_id: UUID
    sender_id: UUID
    recipient_id: UUID
    message_key: str
    message_text: str
    read_at: Optional[datetime]
    created_at: datetime

    model_config = {"from_attributes": True}
