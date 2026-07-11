import uuid

from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, String, Text
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
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    predictions    = relationship("Prediction",   back_populates="user", cascade="all, delete-orphan")
    sleep_logs     = relationship("SleepLog",     back_populates="user", cascade="all, delete-orphan")
    cognitive_tests = relationship("CognitiveTest", back_populates="user", cascade="all, delete-orphan")
    refresh_tokens = relationship("RefreshToken", back_populates="user", cascade="all, delete-orphan")
    caregiver_links = relationship(
        "CaregiverLink",
        foreign_keys="CaregiverLink.patient_id",
        back_populates="patient",
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
    quality_score  = Column(Integer, nullable=False)   # 1–5
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
    status       = Column(String(20), nullable=False, default="pending")  # pending | active | revoked
    created_at   = Column(DateTime(timezone=True), server_default=func.now())
    updated_at   = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    patient    = relationship("User", foreign_keys=[patient_id], back_populates="caregiver_links")
    caregiver  = relationship("User", foreign_keys=[caregiver_id])
