import logging
from datetime import datetime, timedelta, timezone
from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.database import get_db
from app.models import (
    CaregiverWellnessCheckIn, CarePatient, CarePatientEvent, CarePatientHandoffNote,
    CarePatientInvitation, CarePatientMedicationLog, CarePatientMedicationSchedule,
    CarePatientMember, CarePatientRoutine, User,
)
from app.schemas import (
    CarePatientCreate,
    CarePatientEventCreate,
    CarePatientEventOut,
    CarePatientEventUpdate,
    CarePatientInvitationOut,
    CarePatientHandoffNoteCreate,
    CarePatientHandoffNoteOut,
    CarePatientHandoffNoteUpdate,
    CarePatientInviteCreate,
    CarePatientMemberOut,
    CarePatientOut,
    CarePatientRoutineOut,
    CarePatientRoutineUpsert,
    CarePatientDailySummaryOut,
    CarePatientSummaryHistoryOut,
    CarePatientUpdate,
    CaregiverUserOut,
    CaregiverWellnessCheckInCreate,
    CaregiverWellnessCheckInOut,
    CaregiverWellnessSummaryOut,
    CarePatientMedicationScheduleCreate,
    CarePatientMedicationScheduleUpdate,
    CarePatientMedicationScheduleOut,
    CarePatientMedicationLogCreate,
    CarePatientMedicationLogOut,
)
from app.services.caregiver_access import require_active_member, require_primary

router = APIRouter(prefix="/care-patients", tags=["Care Patients"])
logger = logging.getLogger("adchronotype.care_patients")


def _user_out(user: User) -> CaregiverUserOut:
    return CaregiverUserOut(id=user.id, firstName=user.first_name, lastName=user.last_name, username=user.username)


def _patient_out(patient: CarePatient, role: str) -> CarePatientOut:
    return CarePatientOut(
        id=patient.id,
        display_name=patient.display_name,
        primary_caregiver_id=patient.primary_caregiver_id,
        my_role=role,
        created_at=patient.created_at,
        updated_at=patient.updated_at,
    )


def _invite_out(invite: CarePatientInvitation) -> CarePatientInvitationOut:
    return CarePatientInvitationOut(
        id=invite.id,
        patient_id=invite.patient_id,
        patient_name=invite.patient.display_name,
        invited_by_user_id=invite.invited_by_user_id,
        invitee_user_id=invite.invitee_user_id,
        invited_email=invite.invited_email,
        role=invite.role,
        status=invite.status,
        created_at=invite.created_at,
        responded_at=invite.responded_at,
    )


def _event_out(event: CarePatientEvent) -> CarePatientEventOut:
    return CarePatientEventOut(
        id=event.id,
        patient_id=event.patient_id,
        logged_by_user_id=event.logged_by_user_id,
        logged_by=_user_out(event.logged_by) if event.logged_by else None,
        event_type=event.event_type,
        event_time=event.event_time,
        note=event.note,
        duration_min=event.duration_min,
        created_at=event.created_at,
        updated_at=event.updated_at,
    )


def _routine_out(routine: CarePatientRoutine) -> CarePatientRoutineOut:
    return CarePatientRoutineOut(
        id=routine.id, patient_id=routine.patient_id,
        usual_bedtime=routine.usual_bedtime, usual_wake_time=routine.usual_wake_time,
        nap_start_time=routine.nap_start_time, nap_end_time=routine.nap_end_time,
        notes=routine.notes, created_at=routine.created_at, updated_at=routine.updated_at,
    )


def _handoff_out(note: CarePatientHandoffNote) -> CarePatientHandoffNoteOut:
    return CarePatientHandoffNoteOut(
        id=note.id, patient_id=note.patient_id, author_user_id=note.author_user_id,
        author=_user_out(note.author) if note.author else None,
        tags=[tag for tag in note.tags.split("|") if tag], note=note.note,
        created_at=note.created_at, updated_at=note.updated_at,
    )


def _wellness_out(row: CaregiverWellnessCheckIn) -> CaregiverWellnessCheckInOut:
    return CaregiverWellnessCheckInOut(
        id=row.id, user_id=row.user_id, feeling=row.feeling,
        sleep_minutes=row.sleep_minutes, broken_night=row.broken_night,
        note=row.note, created_at=row.created_at, updated_at=row.updated_at,
    )


def _medication_out(row: CarePatientMedicationSchedule) -> CarePatientMedicationScheduleOut:
    return CarePatientMedicationScheduleOut(
        id=row.id, patient_id=row.patient_id, created_by_user_id=row.created_by_user_id,
        name=row.name, instructions=row.instructions, window_start=row.window_start,
        window_end=row.window_end, clinician_confirmed=row.clinician_confirmed,
        active=row.active, created_at=row.created_at, updated_at=row.updated_at,
    )


def _medication_log_out(row: CarePatientMedicationLog) -> CarePatientMedicationLogOut:
    return CarePatientMedicationLogOut(
        id=row.id, patient_id=row.patient_id, schedule_id=row.schedule_id,
        logged_by_user_id=row.logged_by_user_id,
        logged_by=_user_out(row.logged_by) if row.logged_by else None,
        status=row.status, occurred_at=row.occurred_at, note=row.note,
        created_at=row.created_at,
    )


def _clock_minutes(value: datetime) -> int:
    return value.hour * 60 + value.minute


def _target_minutes(value: str) -> int:
    hour, minute = value.split(":")
    return int(hour) * 60 + int(minute)


def _clock_difference(actual: int, target: int) -> int:
    return (actual - target + 720) % 1440 - 720


@router.post("", response_model=CarePatientOut, status_code=201)
def create_patient(body: CarePatientCreate, db: Session = Depends(get_db), me: User = Depends(get_current_user)):
    patient = CarePatient(display_name=body.display_name.strip(), primary_caregiver_id=me.id)
    db.add(patient)
    db.flush()
    db.add(CarePatientMember(
        patient_id=patient.id,
        user_id=me.id,
        role="primary",
        status="active",
        granted_by_user_id=me.id,
    ))
    db.commit()
    db.refresh(patient)
    logger.info("care_patient_created patient_id=%s primary_user_id=%s", patient.id, me.id)
    return _patient_out(patient, "primary")


@router.get("", response_model=List[CarePatientOut])
def list_patients(db: Session = Depends(get_db), me: User = Depends(get_current_user)):
    rows = db.query(CarePatient, CarePatientMember).join(
        CarePatientMember, CarePatientMember.patient_id == CarePatient.id,
    ).filter(
        CarePatientMember.user_id == me.id,
        CarePatientMember.status == "active",
    ).order_by(CarePatient.created_at.desc()).all()
    return [_patient_out(patient, member.role) for patient, member in rows]


@router.get("/invitations/incoming", response_model=List[CarePatientInvitationOut])
def incoming_invitations(db: Session = Depends(get_db), me: User = Depends(get_current_user)):
    rows = db.query(CarePatientInvitation).filter(
        CarePatientInvitation.status == "pending",
        or_(
            CarePatientInvitation.invitee_user_id == me.id,
            func.lower(CarePatientInvitation.invited_email) == me.email.lower(),
        ),
    ).order_by(CarePatientInvitation.created_at.desc()).all()
    return [_invite_out(row) for row in rows]


@router.post("/wellness/check-ins", response_model=CaregiverWellnessCheckInOut, status_code=201)
def create_wellness_check_in(
    body: CaregiverWellnessCheckInCreate,
    db: Session = Depends(get_db),
    me: User = Depends(get_current_user),
):
    row = CaregiverWellnessCheckIn(
        user_id=me.id, feeling=body.feeling, sleep_minutes=body.sleep_minutes,
        broken_night=body.broken_night, note=body.note.strip() if body.note else None,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _wellness_out(row)


@router.get("/wellness/summary", response_model=CaregiverWellnessSummaryOut)
def wellness_summary(
    days: int = 7,
    db: Session = Depends(get_db),
    me: User = Depends(get_current_user),
):
    days = max(1, min(days, 30))
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    rows = db.query(CaregiverWellnessCheckIn).filter(
        CaregiverWellnessCheckIn.user_id == me.id,
        CaregiverWellnessCheckIn.created_at >= cutoff,
    ).order_by(CaregiverWellnessCheckIn.created_at.desc()).all()
    sleep_values = [row.sleep_minutes for row in rows if row.sleep_minutes is not None]
    average = round(sum(sleep_values) / len(sleep_values)) if sleep_values else None
    broken_nights = sum(1 for row in rows if row.broken_night)
    hard_week = (
        any(row.feeling == "overwhelmed" for row in rows)
        or broken_nights >= 3
        or (average is not None and average < 300)
    )
    return CaregiverWellnessSummaryOut(
        check_ins=[_wellness_out(row) for row in rows],
        average_sleep_minutes=average,
        broken_nights=broken_nights,
        hard_week=hard_week,
    )


@router.get("/{patient_id}", response_model=CarePatientOut)
def get_patient(patient_id: UUID, db: Session = Depends(get_db), me: User = Depends(get_current_user)):
    patient, member = require_active_member(db, patient_id, me)
    return _patient_out(patient, member.role)


@router.patch("/{patient_id}", response_model=CarePatientOut)
def update_patient(body: CarePatientUpdate, patient_id: UUID, db: Session = Depends(get_db), me: User = Depends(get_current_user)):
    patient, member = require_primary(db, patient_id, me)
    patient.display_name = body.display_name.strip()
    db.commit()
    db.refresh(patient)
    return _patient_out(patient, member.role)


@router.get("/{patient_id}/members", response_model=List[CarePatientMemberOut])
def list_members(patient_id: UUID, db: Session = Depends(get_db), me: User = Depends(get_current_user)):
    require_active_member(db, patient_id, me)
    rows = db.query(CarePatientMember).filter(
        CarePatientMember.patient_id == patient_id,
        CarePatientMember.status == "active",
    ).order_by(CarePatientMember.granted_at.asc()).all()
    return [CarePatientMemberOut(
        id=row.id, patient_id=row.patient_id, user_id=row.user_id, role=row.role,
        status=row.status, granted_by_user_id=row.granted_by_user_id,
        granted_at=row.granted_at, revoked_at=row.revoked_at, user=_user_out(row.user),
    ) for row in rows]


@router.post("/{patient_id}/invitations", response_model=CarePatientInvitationOut, status_code=201)
def invite_helper(body: CarePatientInviteCreate, patient_id: UUID, db: Session = Depends(get_db), me: User = Depends(get_current_user)):
    patient, _ = require_primary(db, patient_id, me)
    username, email = body.username, body.email

    invitee = None
    if username:
        invitee = db.query(User).filter(func.lower(User.username) == username.lower()).first()
        if not invitee:
            raise HTTPException(status_code=404, detail="user not found")
        email = invitee.email.lower()
    else:
        invitee = db.query(User).filter(func.lower(User.email) == str(email).lower()).first()

    if invitee and invitee.id == me.id:
        raise HTTPException(status_code=400, detail="primary caregiver cannot invite themselves")
    if invitee and db.query(CarePatientMember).filter(
        CarePatientMember.patient_id == patient_id,
        CarePatientMember.user_id == invitee.id,
        CarePatientMember.status == "active",
    ).first():
        raise HTTPException(status_code=409, detail="user already has access")

    target_match = (
        CarePatientInvitation.invitee_user_id == invitee.id
        if invitee
        else func.lower(CarePatientInvitation.invited_email) == str(email).lower()
    )
    duplicate = db.query(CarePatientInvitation).filter(
        CarePatientInvitation.patient_id == patient_id,
        CarePatientInvitation.status == "pending",
        target_match,
    ).first()
    if duplicate:
        raise HTTPException(status_code=409, detail="pending invitation already exists")

    invite = CarePatientInvitation(
        patient_id=patient.id,
        invited_by_user_id=me.id,
        invitee_user_id=invitee.id if invitee else None,
        invited_email=str(email).lower(),
        role="helper",
        status="pending",
    )
    db.add(invite)
    db.commit()
    db.refresh(invite)
    logger.info("care_patient_invited patient_id=%s inviter_id=%s invite_id=%s", patient_id, me.id, invite.id)
    return _invite_out(invite)


@router.get("/{patient_id}/invitations", response_model=List[CarePatientInvitationOut])
def list_invitations(patient_id: UUID, db: Session = Depends(get_db), me: User = Depends(get_current_user)):
    require_primary(db, patient_id, me)
    rows = db.query(CarePatientInvitation).filter(CarePatientInvitation.patient_id == patient_id).order_by(
        CarePatientInvitation.created_at.desc()
    ).all()
    return [_invite_out(row) for row in rows]


def _pending_invite_for_user(db: Session, invite_id: UUID, me: User) -> CarePatientInvitation:
    invite = db.query(CarePatientInvitation).filter(
        CarePatientInvitation.id == invite_id,
        CarePatientInvitation.status == "pending",
        or_(CarePatientInvitation.invitee_user_id == me.id, func.lower(CarePatientInvitation.invited_email) == me.email.lower()),
    ).first()
    if not invite:
        raise HTTPException(status_code=404, detail="pending invitation not found")
    return invite


@router.post("/invitations/{invite_id}/accept", response_model=CarePatientOut)
def accept_invitation(invite_id: UUID, db: Session = Depends(get_db), me: User = Depends(get_current_user)):
    invite = _pending_invite_for_user(db, invite_id, me)
    member = db.query(CarePatientMember).filter(
        CarePatientMember.patient_id == invite.patient_id,
        CarePatientMember.user_id == me.id,
    ).first()
    if member:
        member.role = "helper"
        member.status = "active"
        member.granted_by_user_id = invite.invited_by_user_id
        member.granted_at = datetime.now(timezone.utc)
        member.revoked_at = None
    else:
        member = CarePatientMember(
            patient_id=invite.patient_id, user_id=me.id, role="helper", status="active",
            granted_by_user_id=invite.invited_by_user_id,
        )
        db.add(member)
    invite.invitee_user_id = me.id
    invite.status = "accepted"
    invite.responded_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(invite.patient)
    return _patient_out(invite.patient, "helper")


@router.post("/invitations/{invite_id}/decline", response_model=CarePatientInvitationOut)
def decline_invitation(invite_id: UUID, db: Session = Depends(get_db), me: User = Depends(get_current_user)):
    invite = _pending_invite_for_user(db, invite_id, me)
    invite.status = "declined"
    invite.responded_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(invite)
    return _invite_out(invite)


@router.delete("/invitations/{invite_id}", status_code=204)
def cancel_invitation(invite_id: UUID, db: Session = Depends(get_db), me: User = Depends(get_current_user)):
    invite = db.query(CarePatientInvitation).filter(CarePatientInvitation.id == invite_id).first()
    if not invite:
        raise HTTPException(status_code=404, detail="invitation not found")
    require_primary(db, invite.patient_id, me)
    if invite.status != "pending":
        raise HTTPException(status_code=409, detail="only pending invitations can be cancelled")
    invite.status = "cancelled"
    invite.responded_at = datetime.now(timezone.utc)
    db.commit()


@router.delete("/{patient_id}/members/{member_id}", status_code=204)
def revoke_helper(member_id: UUID, patient_id: UUID, db: Session = Depends(get_db), me: User = Depends(get_current_user)):
    require_primary(db, patient_id, me)
    member = db.query(CarePatientMember).filter(
        CarePatientMember.id == member_id,
        CarePatientMember.patient_id == patient_id,
        CarePatientMember.status == "active",
    ).first()
    if not member:
        raise HTTPException(status_code=404, detail="active member not found")
    if member.role == "primary":
        raise HTTPException(status_code=400, detail="primary caregiver cannot be removed")
    member.status = "revoked"
    member.revoked_at = datetime.now(timezone.utc)
    db.commit()
    logger.info("care_patient_access_revoked patient_id=%s member_id=%s by_user_id=%s", patient_id, member_id, me.id)


@router.post("/{patient_id}/events", response_model=CarePatientEventOut, status_code=201)
def create_event(body: CarePatientEventCreate, patient_id: UUID, db: Session = Depends(get_db), me: User = Depends(get_current_user)):
    require_active_member(db, patient_id, me)
    now = datetime.now(timezone.utc)
    event_time = body.event_time if body.event_time.tzinfo else body.event_time.replace(tzinfo=timezone.utc)
    if event_time > now + timedelta(minutes=5):
        raise HTTPException(status_code=422, detail="event time cannot be in the future")
    if body.duration_min is not None and body.event_type != "napped":
        raise HTTPException(status_code=422, detail="duration is only supported for naps")
    event = CarePatientEvent(
        patient_id=patient_id,
        logged_by_user_id=me.id,
        event_type=body.event_type,
        duration_min=body.duration_min,
        event_time=event_time,
        note=body.note.strip() if body.note else None,
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    logger.info("care_patient_event_created patient_id=%s event_id=%s by_user_id=%s", patient_id, event.id, me.id)
    return _event_out(event)


@router.get("/{patient_id}/events", response_model=List[CarePatientEventOut])
def list_events(
    patient_id: UUID,
    since: datetime | None = None,
    until: datetime | None = None,
    limit: int = 100,
    db: Session = Depends(get_db),
    me: User = Depends(get_current_user),
):
    require_active_member(db, patient_id, me)
    query = db.query(CarePatientEvent).filter(CarePatientEvent.patient_id == patient_id)
    if since:
        query = query.filter(CarePatientEvent.event_time >= since)
    if until:
        query = query.filter(CarePatientEvent.event_time <= until)
    rows = query.order_by(CarePatientEvent.event_time.desc()).limit(min(max(limit, 1), 250)).all()
    return [_event_out(row) for row in rows]


@router.patch("/{patient_id}/events/{event_id}", response_model=CarePatientEventOut)
def update_event(body: CarePatientEventUpdate, event_id: UUID, patient_id: UUID, db: Session = Depends(get_db), me: User = Depends(get_current_user)):
    _, member = require_active_member(db, patient_id, me)
    event = db.query(CarePatientEvent).filter(CarePatientEvent.id == event_id, CarePatientEvent.patient_id == patient_id).first()
    if not event:
        raise HTTPException(status_code=404, detail="event not found")
    if member.role != "primary" and event.logged_by_user_id != me.id:
        raise HTTPException(status_code=403, detail="helpers can only edit their own events")
    updates = body.model_dump(exclude_unset=True)
    if any(key in updates and updates[key] is None for key in ("event_type", "event_time")):
        raise HTTPException(status_code=422, detail="event type and time cannot be null")
    if updates.get("duration_min") is not None and updates.get("event_type", event.event_type) != "napped":
        raise HTTPException(status_code=422, detail="duration is only supported for naps")
    if "event_time" in updates:
        event_time = updates["event_time"]
        event_time = event_time if event_time.tzinfo else event_time.replace(tzinfo=timezone.utc)
        if event_time > datetime.now(timezone.utc) + timedelta(minutes=5):
            raise HTTPException(status_code=422, detail="event time cannot be in the future")
        event.event_time = event_time
    if "duration_min" in updates:
        event.duration_min = updates["duration_min"]
    if "event_type" in updates:
        event.event_type = updates["event_type"]
        if event.event_type != "napped":
            event.duration_min = None
    if "note" in updates:
        event.note = updates["note"].strip() if updates["note"] else None
    db.commit()
    db.refresh(event)
    return _event_out(event)


@router.delete("/{patient_id}/events/{event_id}", status_code=204)
def delete_event(event_id: UUID, patient_id: UUID, db: Session = Depends(get_db), me: User = Depends(get_current_user)):
    _, member = require_active_member(db, patient_id, me)
    event = db.query(CarePatientEvent).filter(CarePatientEvent.id == event_id, CarePatientEvent.patient_id == patient_id).first()
    if not event:
        raise HTTPException(status_code=404, detail="event not found")
    if member.role != "primary" and event.logged_by_user_id != me.id:
        raise HTTPException(status_code=403, detail="helpers can only delete their own events")
    db.delete(event)
    db.commit()


@router.get("/{patient_id}/daily-summaries", response_model=CarePatientSummaryHistoryOut)
def daily_summaries(
    patient_id: UUID,
    days: int = 7,
    db: Session = Depends(get_db),
    me: User = Depends(get_current_user),
):
    require_active_member(db, patient_id, me)
    days = min(max(days, 1), 30)
    now = datetime.now(timezone.utc)
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    history_start = today - timedelta(days=max(days, 30))
    events = db.query(CarePatientEvent).filter(
        CarePatientEvent.patient_id == patient_id,
        CarePatientEvent.event_time >= history_start - timedelta(days=1),
    ).order_by(CarePatientEvent.event_time.asc()).all()
    notes = db.query(CarePatientHandoffNote).filter(
        CarePatientHandoffNote.patient_id == patient_id,
        CarePatientHandoffNote.created_at >= today - timedelta(days=days - 1),
    ).all()
    routine = db.query(CarePatientRoutine).filter(CarePatientRoutine.patient_id == patient_id).first()

    def aware(value: datetime) -> datetime:
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)

    event_times = [(event, aware(event.event_time)) for event in events]
    note_times = [(note, aware(note.created_at)) for note in notes]
    paired_sleep_dates = set()
    for event, slept_time in event_times:
        if event.event_type == "slept" and any(
            candidate.event_type == "woke" and slept_time < candidate_time <= slept_time + timedelta(hours=18)
            for candidate, candidate_time in event_times
        ):
            paired_sleep_dates.add(slept_time.date())

    output = []
    for offset in range(days):
        day_start = today - timedelta(days=offset)
        day_end = day_start + timedelta(days=1)
        day_events = [(event, value) for event, value in event_times if day_start <= value < day_end]
        slept_candidates = [(event, value) for event, value in day_events if event.event_type == "slept"]
        slept_at = slept_candidates[-1][1] if slept_candidates else None
        wake_candidates = [value for event, value in event_times if event.event_type == "woke" and slept_at and slept_at < value <= slept_at + timedelta(hours=18)]
        woke_at = wake_candidates[0] if wake_candidates else None
        sleep_minutes = int((woke_at - slept_at).total_seconds() // 60) if slept_at and woke_at else None
        bedtime_difference = _clock_difference(_clock_minutes(slept_at), _target_minutes(routine.usual_bedtime)) if slept_at and routine else None
        wake_difference = _clock_difference(_clock_minutes(woke_at), _target_minutes(routine.usual_wake_time)) if woke_at and routine else None
        if not routine:
            status = "no_routine"
        elif sleep_minutes is None:
            status = "insufficient"
        elif abs(bedtime_difference) <= 60 and abs(wake_difference) <= 60:
            status = "on_routine"
        else:
            status = "outside_routine"
        output.append(CarePatientDailySummaryOut(
            date=day_start.date().isoformat(), slept_at=slept_at, woke_at=woke_at,
            sleep_minutes=sleep_minutes,
            nap_count=sum(1 for event, _ in day_events if event.event_type == "napped"),
            agitation_count=sum(1 for event, _ in day_events if event.event_type == "agitated"),
            event_count=len(day_events),
            handoff_note_count=sum(1 for _, value in note_times if day_start <= value < day_end),
            bedtime_difference_minutes=bedtime_difference,
            wake_difference_minutes=wake_difference,
            routine_status=status,
        ))
    learning_nights = len(paired_sleep_dates)
    return CarePatientSummaryHistoryOut(
        generated_at=now, learning_nights=learning_nights,
        sufficient_data=learning_nights >= 7, days=output,
    )


@router.get("/{patient_id}/routine", response_model=CarePatientRoutineOut | None)
def get_routine(patient_id: UUID, db: Session = Depends(get_db), me: User = Depends(get_current_user)):
    require_active_member(db, patient_id, me)
    routine = db.query(CarePatientRoutine).filter(CarePatientRoutine.patient_id == patient_id).first()
    return _routine_out(routine) if routine else None


@router.put("/{patient_id}/routine", response_model=CarePatientRoutineOut)
def upsert_routine(body: CarePatientRoutineUpsert, patient_id: UUID, db: Session = Depends(get_db), me: User = Depends(get_current_user)):
    require_primary(db, patient_id, me)
    routine = db.query(CarePatientRoutine).filter(CarePatientRoutine.patient_id == patient_id).first()
    values = body.model_dump()
    values["notes"] = values["notes"].strip() if values["notes"] else None
    if routine:
        for key, value in values.items():
            setattr(routine, key, value)
    else:
        routine = CarePatientRoutine(patient_id=patient_id, **values)
        db.add(routine)
    db.commit()
    db.refresh(routine)
    logger.info("care_patient_routine_saved patient_id=%s by_user_id=%s", patient_id, me.id)
    return _routine_out(routine)


@router.post("/{patient_id}/handoff-notes", response_model=CarePatientHandoffNoteOut, status_code=201)
def create_handoff_note(body: CarePatientHandoffNoteCreate, patient_id: UUID, db: Session = Depends(get_db), me: User = Depends(get_current_user)):
    require_active_member(db, patient_id, me)
    note = CarePatientHandoffNote(
        patient_id=patient_id, author_user_id=me.id, tags="|".join(body.tags),
        note=body.note.strip() if body.note else None,
    )
    db.add(note)
    db.commit()
    db.refresh(note)
    return _handoff_out(note)


@router.get("/{patient_id}/handoff-notes", response_model=List[CarePatientHandoffNoteOut])
def list_handoff_notes(
    patient_id: UUID, since: datetime | None = None, until: datetime | None = None,
    limit: int = 100, db: Session = Depends(get_db), me: User = Depends(get_current_user),
):
    require_active_member(db, patient_id, me)
    query = db.query(CarePatientHandoffNote).filter(CarePatientHandoffNote.patient_id == patient_id)
    if since:
        query = query.filter(CarePatientHandoffNote.created_at >= since)
    if until:
        query = query.filter(CarePatientHandoffNote.created_at <= until)
    rows = query.order_by(CarePatientHandoffNote.created_at.desc()).limit(min(max(limit, 1), 250)).all()
    return [_handoff_out(row) for row in rows]


def _editable_handoff(db: Session, patient_id: UUID, note_id: UUID, me: User):
    _, member = require_active_member(db, patient_id, me)
    note = db.query(CarePatientHandoffNote).filter(
        CarePatientHandoffNote.id == note_id, CarePatientHandoffNote.patient_id == patient_id,
    ).first()
    if not note:
        raise HTTPException(status_code=404, detail="handoff note not found")
    if member.role != "primary" and note.author_user_id != me.id:
        raise HTTPException(status_code=403, detail="helpers can only manage their own handoff notes")
    return note


@router.patch("/{patient_id}/handoff-notes/{note_id}", response_model=CarePatientHandoffNoteOut)
def update_handoff_note(body: CarePatientHandoffNoteUpdate, note_id: UUID, patient_id: UUID, db: Session = Depends(get_db), me: User = Depends(get_current_user)):
    note = _editable_handoff(db, patient_id, note_id, me)
    note.tags = "|".join(body.tags)
    note.note = body.note.strip() if body.note else None
    db.commit()
    db.refresh(note)
    return _handoff_out(note)


@router.delete("/{patient_id}/handoff-notes/{note_id}", status_code=204)
def delete_handoff_note(note_id: UUID, patient_id: UUID, db: Session = Depends(get_db), me: User = Depends(get_current_user)):
    note = _editable_handoff(db, patient_id, note_id, me)
    db.delete(note)
    db.commit()


@router.post("/{patient_id}/medications", response_model=CarePatientMedicationScheduleOut, status_code=201)
def create_medication_schedule(
    body: CarePatientMedicationScheduleCreate, patient_id: UUID,
    db: Session = Depends(get_db), me: User = Depends(get_current_user),
):
    require_primary(db, patient_id, me)
    row = CarePatientMedicationSchedule(
        patient_id=patient_id, created_by_user_id=me.id,
        name=body.name.strip(), instructions=body.instructions.strip() if body.instructions else None,
        window_start=body.window_start, window_end=body.window_end,
        clinician_confirmed=True, active=True,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _medication_out(row)


@router.get("/{patient_id}/medications", response_model=List[CarePatientMedicationScheduleOut])
def list_medication_schedules(
    patient_id: UUID, active_only: bool = True,
    db: Session = Depends(get_db), me: User = Depends(get_current_user),
):
    require_active_member(db, patient_id, me)
    query = db.query(CarePatientMedicationSchedule).filter(CarePatientMedicationSchedule.patient_id == patient_id)
    if active_only:
        query = query.filter(CarePatientMedicationSchedule.active.is_(True))
    rows = query.order_by(CarePatientMedicationSchedule.window_start.asc()).all()
    return [_medication_out(row) for row in rows]


@router.patch("/{patient_id}/medications/{schedule_id}", response_model=CarePatientMedicationScheduleOut)
def update_medication_schedule(
    body: CarePatientMedicationScheduleUpdate, schedule_id: UUID, patient_id: UUID,
    db: Session = Depends(get_db), me: User = Depends(get_current_user),
):
    require_primary(db, patient_id, me)
    row = db.query(CarePatientMedicationSchedule).filter(
        CarePatientMedicationSchedule.id == schedule_id,
        CarePatientMedicationSchedule.patient_id == patient_id,
    ).first()
    if not row:
        raise HTTPException(status_code=404, detail="medication schedule not found")
    row.name = body.name.strip()
    row.instructions = body.instructions.strip() if body.instructions else None
    row.window_start, row.window_end = body.window_start, body.window_end
    row.clinician_confirmed, row.active = True, body.active
    db.commit()
    db.refresh(row)
    return _medication_out(row)


@router.delete("/{patient_id}/medications/{schedule_id}", status_code=204)
def delete_medication_schedule(
    schedule_id: UUID, patient_id: UUID,
    db: Session = Depends(get_db), me: User = Depends(get_current_user),
):
    require_primary(db, patient_id, me)
    row = db.query(CarePatientMedicationSchedule).filter(
        CarePatientMedicationSchedule.id == schedule_id,
        CarePatientMedicationSchedule.patient_id == patient_id,
    ).first()
    if not row:
        raise HTTPException(status_code=404, detail="medication schedule not found")
    db.delete(row)
    db.commit()


@router.post("/{patient_id}/medications/{schedule_id}/logs", response_model=CarePatientMedicationLogOut, status_code=201)
def create_medication_log(
    body: CarePatientMedicationLogCreate, schedule_id: UUID, patient_id: UUID,
    db: Session = Depends(get_db), me: User = Depends(get_current_user),
):
    require_active_member(db, patient_id, me)
    schedule = db.query(CarePatientMedicationSchedule).filter(
        CarePatientMedicationSchedule.id == schedule_id,
        CarePatientMedicationSchedule.patient_id == patient_id,
        CarePatientMedicationSchedule.active.is_(True),
    ).first()
    if not schedule:
        raise HTTPException(status_code=404, detail="active medication schedule not found")
    occurred_at = body.occurred_at if body.occurred_at.tzinfo else body.occurred_at.replace(tzinfo=timezone.utc)
    if occurred_at > datetime.now(timezone.utc) + timedelta(minutes=5):
        raise HTTPException(status_code=422, detail="medication log time cannot be in the future")
    row = CarePatientMedicationLog(
        patient_id=patient_id, schedule_id=schedule_id, logged_by_user_id=me.id,
        status=body.status, occurred_at=occurred_at,
        note=body.note.strip() if body.note else None,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _medication_log_out(row)


@router.get("/{patient_id}/medication-logs", response_model=List[CarePatientMedicationLogOut])
def list_medication_logs(
    patient_id: UUID, limit: int = 100,
    db: Session = Depends(get_db), me: User = Depends(get_current_user),
):
    require_active_member(db, patient_id, me)
    rows = db.query(CarePatientMedicationLog).filter(
        CarePatientMedicationLog.patient_id == patient_id,
    ).order_by(CarePatientMedicationLog.occurred_at.desc()).limit(min(max(limit, 1), 250)).all()
    return [_medication_log_out(row) for row in rows]
