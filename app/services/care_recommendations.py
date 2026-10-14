"""Rules adapted from the supplied care_backend.py. Original files: docs/caregiver-reference. No ML training."""
from __future__ import annotations

import math
from collections import defaultdict
from datetime import datetime, time
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field, model_validator


# =============================================================================
#  DATA SHAPES  (this is exactly what the app must send / the DB must return)
# =============================================================================

class EventType(str, Enum):
    """The kinds of events a caregiver logs with one tap."""
    WAKE = "wake"                 # patient woke up
    SLEEP = "sleep"               # patient fell asleep for the night
    NAP_START = "nap_start"       # daytime nap began
    NAP_END = "nap_end"           # daytime nap ended
    AGITATION = "agitation"       # patient became agitated / distressed
    MEAL = "meal"                 # optional, not required by the logic here
    MEDS_PREPARED = "meds_prepared"  # optional


class LogEntry(BaseModel):
    """
    One logged event. This is the shape the DB rows / app payloads must match.

      patient_id : str      -> which patient this belongs to
      type       : EventType-> one of the strings in EventType above
      timestamp  : datetime -> ISO 8601, e.g. "2026-10-02T14:30:00"
      duration_min: int|None-> only used for naps (minutes), optional otherwise
      note       : str|None -> free text, e.g. "calmed with music", optional
    """
    patient_id: str = Field(min_length=1)
    type: EventType
    timestamp: datetime
    duration_min: Optional[int] = Field(None, ge=1, le=1440)
    note: Optional[str] = None


class CircadianConfig(BaseModel):
    """
    Tunable knobs for the day-night plan. Sensible defaults are set so the
    app can send nothing and still get a reasonable plan. Tune later once
    you have real caregiver feedback - you are NOT locked into these numbers.
    """
    # Target wake/bed the plan nudges TOWARD (local clock, 24h "HH:MM").
    target_wake: str = Field("07:30", pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    target_bed: str = Field("21:30", pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    # Don't jerk the schedule all at once; shift at most this many minutes/day.
    max_daily_shift_min: int = Field(30, ge=1, le=720)
    # Morning bright-light block length, starting at recommended wake.
    morning_light_min: int = Field(45, ge=1, le=1440)
    # Naps: none after this hour (24h), and cap each nap's length.
    nap_cutoff_hour: int = Field(14, ge=0, le=23)           # 2:00 PM
    max_nap_min: int = Field(30, ge=1, le=1440)
    # Wind-down (dim lights, calm activity) begins this many hours before bed.
    winddown_hours_before_bed: float = Field(2.0, gt=0, lt=24)
    # How many days of logs are needed before a plan is trustworthy.
    min_days_required: int = Field(3, ge=1, le=90)


class CalmConfig(BaseModel):
    """Tunable knobs for calm-window detection."""
    bin_minutes: int = Field(60, ge=1, le=1440)          # size of each time-of-day bucket
    min_days_required: int = Field(3, ge=1, le=90)     # need at least this many days of logs
    # A bucket is "calm" if the patient was agitated there on <= this fraction
    # of observed days, and "hard" if agitated on >= the hard fraction.
    calm_threshold: float = Field(0.20, ge=0, le=1)
    hard_threshold: float = Field(0.50, ge=0, le=1)


    @model_validator(mode="after")
    def validate_buckets(self):
        if 1440 % self.bin_minutes:
            raise ValueError("bin_minutes must divide 1440 evenly")
        if self.calm_threshold >= self.hard_threshold:
            raise ValueError("calm_threshold must be below hard_threshold")
        return self


# ---- response shapes ---------------------------------------------------------

class PlanBlock(BaseModel):
    start: str          # "HH:MM"
    end: str            # "HH:MM"
    activity: str       # what the caregiver should do
    reason: str         # why (which problem it addresses)


class CircadianPlan(BaseModel):
    status: str                      # "ok" or "needs_more_data"
    days_of_data: int
    detected_issues: List[str]
    recommended_wake: Optional[str] = None
    recommended_bed: Optional[str] = None
    blocks: List[PlanBlock] = []
    notes: List[str] = []


class CalmWindow(BaseModel):
    start: str          # "HH:MM"
    end: str            # "HH:MM"
    agitation_rate: float  # fraction of observed days with agitation here


class CalmReport(BaseModel):
    status: str                      # "ok" or "needs_more_data"
    days_of_data: int
    calm_windows: List[CalmWindow] = []
    hard_windows: List[CalmWindow] = []
    notes: List[str] = []


# =============================================================================
#  TIME HELPERS
# =============================================================================

def _hhmm_to_minutes(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def _minutes_to_hhmm(mins: int) -> str:
    mins = int(round(mins)) % (24 * 60)
    return f"{mins // 60:02d}:{mins % 60:02d}"


def _circular_mean_minutes(minutes_list: List[int]) -> Optional[int]:
    """
    Average a set of clock times correctly. A plain average breaks across
    midnight (23:50 and 00:10 should average to 00:00, not 12:00). We treat
    each time as an angle on the 24h clock and average the vectors. This also
    makes the plan robust to day-night reversal (afternoon wake, morning
    sleep), which is common in dementia.
    """
    if not minutes_list:
        return None
    day = 24 * 60
    sin_sum = sum(math.sin(2 * math.pi * m / day) for m in minutes_list)
    cos_sum = sum(math.cos(2 * math.pi * m / day) for m in minutes_list)
    if math.hypot(sin_sum, cos_sum) < 1e-8 * len(minutes_list):
        return None
    ang = math.atan2(sin_sum, cos_sum)
    return int(round((ang % (2 * math.pi)) / (2 * math.pi) * day)) % day


def _shift_toward(current_min: int, target_min: int, max_step: int) -> int:
    """Move current time toward target by at most max_step minutes, on the
    shorter way around the 24h clock."""
    day = 24 * 60
    diff = (target_min - current_min) % day
    if diff > day / 2:
        diff -= day  # go the shorter (negative) direction
    step = max(-max_step, min(max_step, diff))
    return (current_min + step) % day


# =============================================================================
#  FEATURE 1 - DAY-NIGHT RESET  (pure logic, fully testable, no DB needed)
# =============================================================================

def build_circadian_plan(logs: List[LogEntry], cfg: CircadianConfig) -> CircadianPlan:
    wake_times, sleep_times, nap_starts, nap_durs = [], [], [], []
    days_seen = set()

    for e in logs:
        days_seen.add(e.timestamp.date())
        tod = e.timestamp.hour * 60 + e.timestamp.minute
        if e.type == EventType.WAKE:
            wake_times.append(tod)
        elif e.type == EventType.SLEEP:
            sleep_times.append(tod)
        elif e.type == EventType.NAP_START:
            nap_starts.append(tod)
            if e.duration_min:
                nap_durs.append(e.duration_min)

    wake_days = {e.timestamp.date() for e in logs if e.type == EventType.WAKE}
    sleep_days = {e.timestamp.date() for e in logs if e.type == EventType.SLEEP}
    days = min(len(wake_days), len(sleep_days))
    if days < cfg.min_days_required:
        return CircadianPlan(
            status="needs_more_data",
            days_of_data=days,
            detected_issues=[],
            notes=[f"Need sleep logs on at least {cfg.min_days_required} days and wake logs on at least {cfg.min_days_required} days; have {len(sleep_days)} sleep days and {len(wake_days)} wake days."],
        )

    mean_wake = _circular_mean_minutes(wake_times)
    mean_sleep = _circular_mean_minutes(sleep_times)
    if mean_wake is None or mean_sleep is None:
        return CircadianPlan(status="needs_more_data", days_of_data=days, detected_issues=[],
                             notes=["Sleep or wake times are too inconsistent to suggest a timing yet."])
    target_wake = _hhmm_to_minutes(cfg.target_wake)
    target_bed = _hhmm_to_minutes(cfg.target_bed)

    # ---- detect problems -----------------------------------------------------
    issues: List[str] = []
    day = 24 * 60

    if mean_wake is not None:
        # how far (minutes) current wake is from target, shorter way round
        dw = (mean_wake - target_wake) % day
        if dw > day / 2:
            dw -= day
        if dw > 90:
            issues.append("waking_late")
        elif dw < -90:
            issues.append("waking_early")

    if mean_sleep is not None:
        ds = (mean_sleep - target_bed) % day
        if ds > day / 2:
            ds -= day
        if ds > 90:
            issues.append("falling_asleep_late")

    late_naps = [t for t in nap_starts if t >= cfg.nap_cutoff_hour * 60]
    if late_naps:
        issues.append("late_daytime_napping")
    if nap_durs and (sum(nap_durs) / max(1, len(days_seen))) > cfg.max_nap_min:
        issues.append("excessive_daytime_napping")

    # Day-night reversal: sleeping deep into daytime / waking in afternoon-evening
    if mean_wake is not None and (12 * 60 <= mean_wake <= 20 * 60):
        issues.append("day_night_reversal")

    # ---- build the plan ------------------------------------------------------
    rec_wake = _shift_toward(mean_wake, target_wake, cfg.max_daily_shift_min) \
        if mean_wake is not None else target_wake
    rec_bed = _shift_toward(mean_sleep, target_bed, cfg.max_daily_shift_min) \
        if mean_sleep is not None else target_bed

    blocks: List[PlanBlock] = []

    # Morning bright light + activity, anchored at recommended wake.
    blocks.append(PlanBlock(
        start=_minutes_to_hhmm(rec_wake),
        end=_minutes_to_hhmm(rec_wake + cfg.morning_light_min),
        activity="Bright light (window or lightbox) + a short walk or activity",
        reason="Morning light anchors the body clock and advances it earlier; "
               "the strongest non-drug lever for restoring night sleep.",
    ))

    # Nap rule (stated as a guard, not a scheduled block).
    blocks.append(PlanBlock(
        start=_minutes_to_hhmm(cfg.nap_cutoff_hour * 60),
        end=_minutes_to_hhmm(cfg.nap_cutoff_hour * 60),
        activity=f"No naps after {cfg.nap_cutoff_hour:02d}:00; "
                 f"keep any earlier nap under {cfg.max_nap_min} min",
        reason="Late or long naps steal sleep pressure from the night and "
               "deepen day-night reversal.",
    ))

    # Wind-down before bed.
    wind_start = (rec_bed - int(cfg.winddown_hours_before_bed * 60)) % day
    blocks.append(PlanBlock(
        start=_minutes_to_hhmm(wind_start),
        end=_minutes_to_hhmm(rec_bed),
        activity="Dim the lights, calm/quiet activity, no screens or caffeine",
        reason="Lower evening light and arousal let melatonin rise so the "
               "patient can fall asleep at night.",
    ))

    notes = [
        "Times shift gradually toward the target; expect several days to move, "
        "not an overnight jump.",
        "This is guidance built from the patient's own logs, refined as more "
        "days are added. It is not medical advice.",
    ]

    if any(e.type == EventType.NAP_START and e.duration_min is None for e in logs):
        notes.append("Some naps have no recorded duration; nap-length findings are incomplete.")
    return CircadianPlan(
        status="ok",
        days_of_data=days,
        detected_issues=issues,
        recommended_wake=_minutes_to_hhmm(rec_wake),
        recommended_bed=_minutes_to_hhmm(rec_bed),
        blocks=blocks,
        notes=notes,
    )


# =============================================================================
#  FEATURE 2 - CALM-WINDOW DETECTION  (pure logic, fully testable, no DB)
# =============================================================================

def detect_calm_windows(logs: List[LogEntry], cfg: CalmConfig) -> CalmReport:
    day = 24 * 60
    n_bins = max(1, day // cfg.bin_minutes)

    all_days = set(e.timestamp.date() for e in logs)
    days = len(all_days)
    if days < cfg.min_days_required:
        return CalmReport(
            status="needs_more_data",
            days_of_data=days,
            notes=[f"Need at least {cfg.min_days_required} days of logs; have {days}."],
        )

    if not any(e.type == EventType.AGITATION for e in logs):
        return CalmReport(status="needs_more_data", days_of_data=days,
                          notes=["No agitation has been logged in this period. This does not establish calm times."])

    # For each time bucket, on how many distinct days did agitation occur there?
    agit_days_per_bin = defaultdict(set)
    for e in logs:
        if e.type != EventType.AGITATION:
            continue
        tod = e.timestamp.hour * 60 + e.timestamp.minute
        b = min(n_bins - 1, tod // cfg.bin_minutes)
        agit_days_per_bin[b].add(e.timestamp.date())

    rate = [len(agit_days_per_bin.get(b, set())) / days for b in range(n_bins)]

    def _merge(pred) -> List[CalmWindow]:
        out, i = [], 0
        while i < n_bins:
            if pred(rate[i]):
                j = i
                while j + 1 < n_bins and pred(rate[j + 1]):
                    j += 1
                window_rates = rate[i:j + 1]
                out.append(CalmWindow(
                    start=_minutes_to_hhmm(i * cfg.bin_minutes),
                    end="24:00" if j + 1 == n_bins else _minutes_to_hhmm((j + 1) * cfg.bin_minutes),
                    agitation_rate=round(sum(window_rates) / len(window_rates), 2),
                ))
                i = j + 1
            else:
                i += 1
        return out

    calm = _merge(lambda r: r <= cfg.calm_threshold)
    hard = _merge(lambda r: r >= cfg.hard_threshold)

    notes = [
        "Calm windows mean fewer recorded incidents, not confirmed calm. Missing logs may change these patterns.",
        "Rates use days with any recorded event, not continuously observed days.",
        "Based only on this patient's own logged agitation; more days make it "
        "sharper.",
        "A calm window is a tendency, not a guarantee. Use it to plan routine "
        "care like bathing, not as a safety assurance.",
    ]
    return CalmReport(
        status="ok",
        days_of_data=days,
        calm_windows=calm,
        hard_windows=hard,
        notes=notes,
    )


