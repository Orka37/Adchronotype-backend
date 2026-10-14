from datetime import datetime
from typing import Optional, List
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator


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


class LegalConsentRequest(BaseModel):
    termsVersion: str = Field(..., min_length=1, max_length=32)
    privacyVersion: str = Field(..., min_length=1, max_length=32)
    platform: Optional[str] = Field(None, max_length=32)
    appVersion: Optional[str] = Field(None, max_length=32)


class LegalConsentOut(LegalConsentRequest):
    id: UUID
    acceptedAt: datetime


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


# ── patient-centered caregiver access ────────────────────────────

class CarePatientCreate(BaseModel):
    display_name: str = Field(..., min_length=1, max_length=100)


class CarePatientUpdate(BaseModel):
    display_name: str = Field(..., min_length=1, max_length=100)


class CarePatientOut(BaseModel):
    id: UUID
    display_name: str
    primary_caregiver_id: UUID
    my_role: str
    created_at: datetime
    updated_at: datetime


class CarePatientMemberOut(BaseModel):
    id: UUID
    patient_id: UUID
    user_id: UUID
    role: str
    status: str
    granted_by_user_id: UUID
    granted_at: datetime
    revoked_at: Optional[datetime]
    user: CaregiverUserOut


class CarePatientInviteCreate(BaseModel):
    username: Optional[str] = Field(None, min_length=3, max_length=50)
    email: Optional[EmailStr] = None

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value):
        return str(value).lower() if value else value

    @model_validator(mode="after")
    def validate_target(self):
        username = self.username.strip() if self.username else None
        if bool(username) == bool(self.email):
            raise ValueError("provide exactly one of username or email")
        self.username = username
        return self


class CarePatientInvitationOut(BaseModel):
    id: UUID
    patient_id: UUID
    patient_name: str
    invited_by_user_id: UUID
    invitee_user_id: Optional[UUID]
    invited_email: Optional[str]
    role: str
    status: str
    created_at: datetime
    responded_at: Optional[datetime]


class CarePatientEventCreate(BaseModel):
    event_type: str = Field(..., pattern=r"^(slept|woke|napped|agitated|other)$")
    event_time: datetime
    duration_min: Optional[int] = Field(None, ge=1, le=1440)
    note: Optional[str] = Field(None, max_length=255)


class CarePatientEventUpdate(BaseModel):
    event_type: Optional[str] = Field(None, pattern=r"^(slept|woke|napped|agitated|other)$")
    event_time: Optional[datetime] = None
    duration_min: Optional[int] = Field(None, ge=1, le=1440)
    note: Optional[str] = Field(None, max_length=255)


class CarePatientEventOut(BaseModel):
    id: UUID
    patient_id: UUID
    logged_by_user_id: Optional[UUID]
    logged_by: Optional[CaregiverUserOut]
    event_type: str
    event_time: datetime
    duration_min: Optional[int] = Field(None, ge=1, le=1440)
    note: Optional[str]
    created_at: datetime
    updated_at: datetime


class CarePatientRoutineUpsert(BaseModel):
    usual_bedtime: str = Field(..., pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    usual_wake_time: str = Field(..., pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    nap_start_time: Optional[str] = Field(None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    nap_end_time: Optional[str] = Field(None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    notes: Optional[str] = Field(None, max_length=500)

    @model_validator(mode="after")
    def validate_nap_window(self):
        if bool(self.nap_start_time) != bool(self.nap_end_time):
            raise ValueError("provide both nap start and nap end, or leave both empty")
        return self


class CarePatientRoutineOut(CarePatientRoutineUpsert):
    id: UUID
    patient_id: UUID
    created_at: datetime
    updated_at: datetime


_HANDOFF_TAGS = {"calm", "agitated", "ate well", "slept", "music helped", "refused meal"}


class CarePatientHandoffNoteCreate(BaseModel):
    tags: List[str] = Field(default_factory=list, max_length=6)
    note: Optional[str] = Field(None, max_length=500)

    @model_validator(mode="after")
    def validate_content(self):
        self.tags = list(dict.fromkeys(tag.strip().lower() for tag in self.tags if tag.strip()))
        unknown = set(self.tags) - _HANDOFF_TAGS
        if unknown:
            raise ValueError(f"unsupported handoff tags: {sorted(unknown)}")
        if not self.tags and not (self.note and self.note.strip()):
            raise ValueError("choose a tag or add a note")
        return self


class CarePatientHandoffNoteUpdate(CarePatientHandoffNoteCreate):
    pass


class CarePatientHandoffNoteOut(BaseModel):
    id: UUID
    patient_id: UUID
    author_user_id: Optional[UUID]
    author: Optional[CaregiverUserOut]
    tags: List[str]
    note: Optional[str]
    created_at: datetime
    updated_at: datetime


class CarePatientDailySummaryOut(BaseModel):
    date: str
    slept_at: Optional[datetime]
    woke_at: Optional[datetime]
    sleep_minutes: Optional[int]
    nap_count: int
    agitation_count: int
    event_count: int
    handoff_note_count: int
    bedtime_difference_minutes: Optional[int]
    wake_difference_minutes: Optional[int]
    routine_status: str


class CarePatientSummaryHistoryOut(BaseModel):
    generated_at: datetime
    learning_nights: int
    sufficient_data: bool
    days: List[CarePatientDailySummaryOut]


class CaregiverWellnessCheckInCreate(BaseModel):
    feeling: str = Field(..., pattern=r"^(okay|tired|overwhelmed)$")
    sleep_minutes: Optional[int] = Field(None, ge=0, le=1440)
    broken_night: bool = False
    note: Optional[str] = Field(None, max_length=500)


class CaregiverWellnessCheckInOut(CaregiverWellnessCheckInCreate):
    id: UUID
    user_id: UUID
    created_at: datetime
    updated_at: datetime


class CaregiverWellnessSummaryOut(BaseModel):
    check_ins: List[CaregiverWellnessCheckInOut]
    average_sleep_minutes: Optional[int]
    broken_nights: int
    hard_week: bool


class CarePatientMedicationScheduleCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    instructions: Optional[str] = Field(None, max_length=255)
    window_start: str = Field(..., pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    window_end: str = Field(..., pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    clinician_confirmed: bool

    @model_validator(mode="after")
    def require_clinician_confirmation(self):
        if not self.clinician_confirmed:
            raise ValueError("confirm this schedule was set by a clinician")
        return self


class CarePatientMedicationScheduleUpdate(CarePatientMedicationScheduleCreate):
    active: bool = True


class CarePatientMedicationScheduleOut(CarePatientMedicationScheduleUpdate):
    id: UUID
    patient_id: UUID
    created_by_user_id: Optional[UUID]
    created_at: datetime
    updated_at: datetime


class CarePatientMedicationLogCreate(BaseModel):
    status: str = Field(..., pattern=r"^(taken|skipped)$")
    occurred_at: datetime
    note: Optional[str] = Field(None, max_length=255)


class CarePatientMedicationLogOut(CarePatientMedicationLogCreate):
    id: UUID
    patient_id: UUID
    schedule_id: UUID
    logged_by_user_id: Optional[UUID]
    logged_by: Optional[CaregiverUserOut]
    created_at: datetime
