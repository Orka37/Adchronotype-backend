import uuid

from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database import Base


class User(Base):
    __tablename__ = "users"

    id         = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    first_name = Column(String(100), nullable=False)
    last_name  = Column(String(100), nullable=False)
    username   = Column(String(50),  unique=True, nullable=False, index=True)
    email      = Column(String(255), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    is_active  = Column(Boolean, default=True, nullable=False)
    caregiver_search_enabled = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    predictions    = relationship("Prediction",   back_populates="user", cascade="all, delete-orphan")
    sleep_logs     = relationship("SleepLog",     back_populates="user", cascade="all, delete-orphan")
    cognitive_tests = relationship("CognitiveTest", back_populates="user", cascade="all, delete-orphan")
    refresh_tokens = relationship("RefreshToken", back_populates="user", cascade="all, delete-orphan")
    password_reset_tokens = relationship("PasswordResetToken", back_populates="user", cascade="all, delete-orphan")
    legal_consents = relationship("LegalConsent", back_populates="user", cascade="all, delete-orphan")
    caregiver_links = relationship(
        "CaregiverLink",
        foreign_keys="CaregiverLink.patient_id",
        back_populates="patient",
        cascade="all, delete-orphan",
    )
    sent_caregiver_messages = relationship(
        "CaregiverMessage",
        foreign_keys="CaregiverMessage.sender_id",
        cascade="all, delete-orphan",
    )


class RefreshToken(Base):
    # DB-backed so tokens can be revoked on logout / password change
    __tablename__ = "refresh_tokens"

    id         = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id    = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    token      = Column(Text, unique=True, nullable=False)
    revoked    = Column(Boolean, default=False, nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User", back_populates="refresh_tokens")


class PasswordResetToken(Base):
    __tablename__ = "password_reset_tokens"

    id         = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id    = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    token_hash = Column(String(64), unique=True, nullable=False, index=True)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    used_at    = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User", back_populates="password_reset_tokens")


class LegalConsent(Base):
    __tablename__ = "legal_consents"
    __table_args__ = (
        UniqueConstraint("user_id", "terms_version", "privacy_version", name="uq_legal_consent_versions"),
    )

    id              = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id         = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    terms_version   = Column(String(32), nullable=False)
    privacy_version = Column(String(32), nullable=False)
    platform        = Column(String(32), nullable=True)
    app_version     = Column(String(32), nullable=True)
    accepted_at     = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    user = relationship("User", back_populates="legal_consents")


class Prediction(Base):
    __tablename__ = "predictions"

    id         = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id    = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)

    # keeping inputs around is useful for retraining the model later
    age            = Column(Integer, nullable=False)
    bmi            = Column(Float,   nullable=False)
    sleep_duration = Column(Float,   nullable=False)
    sleep_time     = Column(String(10), nullable=False)
    wake_time      = Column(String(10), nullable=False)
    chronotype     = Column(String(50), nullable=False)
    ethnicity      = Column(String(50), nullable=False)
    family_history = Column(String(10), nullable=False)

    prediction_value = Column(Float, nullable=False)
    created_at       = Column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User", back_populates="predictions")


class SleepLog(Base):
    __tablename__ = "sleep_logs"

    id             = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id        = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    sleep_time     = Column(String(10), nullable=False)
    wake_time      = Column(String(10), nullable=False)
    duration_hours = Column(Float,   nullable=False)
    quality_score  = Column(Integer, nullable=False)   # 0-21
    awakenings     = Column(Integer, nullable=False, default=0)
    notes          = Column(Text, nullable=True)
    logged_date    = Column(DateTime(timezone=True), nullable=False)
    created_at     = Column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User", back_populates="sleep_logs")


class CognitiveTest(Base):
    __tablename__ = "cognitive_tests"

    id               = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id          = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    test_type        = Column(String(50), nullable=False)   # reaction | digit_span | memory | stroop
    attempt_number   = Column(Integer, nullable=False, default=1)
    score            = Column(Float, nullable=False)
    unit             = Column(String(20), nullable=False)
    duration_seconds = Column(Float, nullable=True)
    tested_at        = Column(DateTime(timezone=True), nullable=False)
    created_at       = Column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User", back_populates="cognitive_tests")


class CaregiverLink(Base):
    __tablename__ = "caregiver_links"

    id           = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    patient_id   = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    caregiver_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    # invited_email lets us handle the case where the caregiver hasn't signed up yet
    invited_email = Column(String(255), nullable=True)
    status       = Column(String(20), nullable=False, default="pending")  # pending | accepted | rejected | revoked
    created_at   = Column(DateTime(timezone=True), server_default=func.now())
    updated_at   = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    patient    = relationship("User", foreign_keys=[patient_id], back_populates="caregiver_links")
    caregiver  = relationship("User", foreign_keys=[caregiver_id])


class CaregiverMessage(Base):
    __tablename__ = "caregiver_messages"

    id            = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    link_id       = Column(UUID(as_uuid=True), ForeignKey("caregiver_links.id"), nullable=False, index=True)
    sender_id     = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    recipient_id  = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    message_key   = Column(String(50), nullable=False)
    message_text  = Column(String(255), nullable=False)
    read_at       = Column(DateTime(timezone=True), nullable=True)
    created_at    = Column(DateTime(timezone=True), server_default=func.now())

    link      = relationship("CaregiverLink")
    sender    = relationship("User", foreign_keys=[sender_id], back_populates="sent_caregiver_messages")
    recipient = relationship("User", foreign_keys=[recipient_id])


class CarePatient(Base):
    """A care recipient record owned by exactly one primary caregiver."""
    __tablename__ = "care_patients"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    display_name = Column(String(100), nullable=False)
    primary_caregiver_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    primary_caregiver = relationship("User", foreign_keys=[primary_caregiver_id])
    memberships = relationship("CarePatientMember", back_populates="patient", cascade="all, delete-orphan")
    invitations = relationship("CarePatientInvitation", back_populates="patient", cascade="all, delete-orphan")
    events = relationship("CarePatientEvent", back_populates="patient", cascade="all, delete-orphan")
    routine = relationship("CarePatientRoutine", back_populates="patient", cascade="all, delete-orphan", uselist=False)
    handoff_notes = relationship("CarePatientHandoffNote", back_populates="patient", cascade="all, delete-orphan")
    medication_schedules = relationship("CarePatientMedicationSchedule", back_populates="patient", cascade="all, delete-orphan")
    medication_logs = relationship("CarePatientMedicationLog", back_populates="patient", cascade="all, delete-orphan")


class CarePatientMember(Base):
    __tablename__ = "care_patient_members"
    __table_args__ = (UniqueConstraint("patient_id", "user_id", name="uq_care_patient_member"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    patient_id = Column(UUID(as_uuid=True), ForeignKey("care_patients.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    role = Column(String(20), nullable=False)  # primary | helper
    status = Column(String(20), nullable=False, default="active")  # active | revoked
    granted_by_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    granted_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    revoked_at = Column(DateTime(timezone=True), nullable=True)

    patient = relationship("CarePatient", back_populates="memberships")
    user = relationship("User", foreign_keys=[user_id])
    granted_by = relationship("User", foreign_keys=[granted_by_user_id])


class CarePatientInvitation(Base):
    __tablename__ = "care_patient_invitations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    patient_id = Column(UUID(as_uuid=True), ForeignKey("care_patients.id", ondelete="CASCADE"), nullable=False, index=True)
    invited_by_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    invitee_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True, index=True)
    invited_email = Column(String(255), nullable=True, index=True)
    role = Column(String(20), nullable=False, default="helper")
    status = Column(String(20), nullable=False, default="pending")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    responded_at = Column(DateTime(timezone=True), nullable=True)

    patient = relationship("CarePatient", back_populates="invitations")
    invited_by = relationship("User", foreign_keys=[invited_by_user_id])
    invitee = relationship("User", foreign_keys=[invitee_user_id])


class CarePatientEvent(Base):
    """A timestamped observation logged by an authorized caregiver."""
    __tablename__ = "care_patient_events"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    patient_id = Column(UUID(as_uuid=True), ForeignKey("care_patients.id", ondelete="CASCADE"), nullable=False, index=True)
    logged_by_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    event_type = Column(String(20), nullable=False)
    event_time = Column(DateTime(timezone=True), nullable=False, index=True)
    note = Column(String(255), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    patient = relationship("CarePatient", back_populates="events")
    logged_by = relationship("User", foreign_keys=[logged_by_user_id])


class CarePatientRoutine(Base):
    """Care schedule configured by the primary caregiver."""
    __tablename__ = "care_patient_routines"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    patient_id = Column(UUID(as_uuid=True), ForeignKey("care_patients.id", ondelete="CASCADE"), nullable=False, unique=True, index=True)
    usual_bedtime = Column(String(5), nullable=False)
    usual_wake_time = Column(String(5), nullable=False)
    nap_start_time = Column(String(5), nullable=True)
    nap_end_time = Column(String(5), nullable=True)
    notes = Column(String(500), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    patient = relationship("CarePatient", back_populates="routine")


class CarePatientHandoffNote(Base):
    """Short shared shift note visible to every active caregiver."""
    __tablename__ = "care_patient_handoff_notes"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    patient_id = Column(UUID(as_uuid=True), ForeignKey("care_patients.id", ondelete="CASCADE"), nullable=False, index=True)
    author_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    tags = Column(String(255), nullable=False, default="")
    note = Column(String(500), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    patient = relationship("CarePatient", back_populates="handoff_notes")
    author = relationship("User", foreign_keys=[author_user_id])


class CaregiverWellnessCheckIn(Base):
    """Private self-care check-in owned by one caregiver, never part of a patient record."""
    __tablename__ = "caregiver_wellness_check_ins"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    feeling = Column(String(20), nullable=False)  # okay | tired | overwhelmed
    sleep_minutes = Column(Integer, nullable=True)
    broken_night = Column(Boolean, nullable=False, default=False)
    note = Column(String(500), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    user = relationship("User", foreign_keys=[user_id])


class CarePatientMedicationSchedule(Base):
    """Clinician-established medication timing recorded by a primary caregiver; no dose field by design."""
    __tablename__ = "care_patient_medication_schedules"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    patient_id = Column(UUID(as_uuid=True), ForeignKey("care_patients.id", ondelete="CASCADE"), nullable=False, index=True)
    created_by_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    name = Column(String(100), nullable=False)
    instructions = Column(String(255), nullable=True)
    window_start = Column(String(5), nullable=False)
    window_end = Column(String(5), nullable=False)
    clinician_confirmed = Column(Boolean, nullable=False, default=True)
    active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    patient = relationship("CarePatient", back_populates="medication_schedules")
    created_by = relationship("User", foreign_keys=[created_by_user_id])
    logs = relationship("CarePatientMedicationLog", back_populates="schedule", cascade="all, delete-orphan")


class CarePatientMedicationLog(Base):
    """Shared record that a scheduled medication was marked taken or skipped."""
    __tablename__ = "care_patient_medication_logs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    patient_id = Column(UUID(as_uuid=True), ForeignKey("care_patients.id", ondelete="CASCADE"), nullable=False, index=True)
    schedule_id = Column(UUID(as_uuid=True), ForeignKey("care_patient_medication_schedules.id", ondelete="CASCADE"), nullable=False, index=True)
    logged_by_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    status = Column(String(20), nullable=False)  # taken | skipped
    occurred_at = Column(DateTime(timezone=True), nullable=False, index=True)
    note = Column(String(255), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    patient = relationship("CarePatient", back_populates="medication_logs")
    schedule = relationship("CarePatientMedicationSchedule", back_populates="logs")
    logged_by = relationship("User", foreign_keys=[logged_by_user_id])
