"""Proves the logic and the API actually work, with realistic synthetic data."""
from datetime import datetime, timedelta
import json

from fastapi.testclient import TestClient
import care_backend as cb
from care_backend import (
    LogEntry, EventType, CircadianConfig, CalmConfig,
    build_circadian_plan, detect_calm_windows, app,
)

# ---------------------------------------------------------------------------
# Build 7 days of realistic logs for a patient with day-night reversal:
#   - wakes late (~11:20), sleeps late (~01:30)
#   - naps in the late afternoon (~16:00) for ~90 min
#   - agitation clusters in the late afternoon/evening (16:00-19:00)
#   - mornings (09:00-11:00) are calm
# ---------------------------------------------------------------------------
def make_logs():
    logs = []
    base = datetime(2026, 9, 1)
    for d in range(7):
        day = base + timedelta(days=d)
        # late wake ~11:20 (+/- a few min via d)
        logs.append(LogEntry(patient_id="p1", type=EventType.WAKE,
                             timestamp=day.replace(hour=11, minute=15 + (d % 3) * 5)))
        # late afternoon nap start ~16:00, 90 min
        logs.append(LogEntry(patient_id="p1", type=EventType.NAP_START,
                             timestamp=day.replace(hour=16, minute=0), duration_min=90))
        logs.append(LogEntry(patient_id="p1", type=EventType.NAP_END,
                             timestamp=day.replace(hour=17, minute=30)))
        # agitation in late afternoon/evening on most days
        for hr in (16, 17, 18):
            if (d + hr) % 4 != 0:  # present most days, not every day
                logs.append(LogEntry(patient_id="p1", type=EventType.AGITATION,
                                     timestamp=day.replace(hour=hr, minute=20),
                                     note="restless"))
        # sleep onset after midnight (~01:30 the NEXT calendar day)
        nxt = day + timedelta(days=1)
        logs.append(LogEntry(patient_id="p1", type=EventType.SLEEP,
                             timestamp=nxt.replace(hour=1, minute=30)))
    return logs


def section(t): print("\n" + "=" * 70 + "\n" + t + "\n" + "=" * 70)

logs = make_logs()
print(f"Generated {len(logs)} log entries across 7 days.")

# ---- 1. circadian plan -----------------------------------------------------
section("FEATURE 1: build_circadian_plan")
plan = build_circadian_plan(logs, CircadianConfig())
print(json.dumps(json.loads(plan.model_dump_json()), indent=2))

assert plan.status == "ok", "should have enough data"
assert "waking_late" in plan.detected_issues
assert "falling_asleep_late" in plan.detected_issues
assert "late_daytime_napping" in plan.detected_issues
assert "excessive_daytime_napping" in plan.detected_issues
# recommended wake should move EARLIER than the ~11:15 current, toward 07:30,
# but by no more than the 30-min/day cap -> around 10:45-ish
rw = int(plan.recommended_wake.split(":")[0]) * 60 + int(plan.recommended_wake.split(":")[1])
assert 10 * 60 + 30 <= rw <= 11 * 60, f"recommended wake {plan.recommended_wake} not nudged correctly"
assert len(plan.blocks) == 3
print("\n[OK] late-phase patient: late-wake/sleep/nap issues detected + wake nudged earlier within cap")

# ---- 1b. a TRULY day-night-reversed patient (wakes mid-afternoon) ----------
section("FEATURE 1b: day-night reversal fires for an afternoon-waking patient")
rev = []
b2 = datetime(2026, 9, 1)
for d in range(5):
    day = b2 + timedelta(days=d)
    rev.append(LogEntry(patient_id="p2", type=EventType.WAKE,
                        timestamp=day.replace(hour=15, minute=0)))   # wakes 3 PM
    nxt = day + timedelta(days=1)
    rev.append(LogEntry(patient_id="p2", type=EventType.SLEEP,
                        timestamp=nxt.replace(hour=6, minute=0)))     # sleeps 6 AM
rev_plan = build_circadian_plan(rev, CircadianConfig())
print("issues:", rev_plan.detected_issues, "| rec wake:", rev_plan.recommended_wake)
assert "day_night_reversal" in rev_plan.detected_issues
print("[OK] day_night_reversal correctly detected for afternoon-waking patient")

# ---- 2. calm windows -------------------------------------------------------
section("FEATURE 2: detect_calm_windows")
report = detect_calm_windows(logs, CalmConfig())
print(json.dumps(json.loads(report.model_dump_json()), indent=2))

assert report.status == "ok"
# late afternoon/evening should be flagged hard
hard_hours = [w.start for w in report.hard_windows]
assert any(w.start <= "16:00" < w.end for w in report.hard_windows), \
    f"expected a hard window covering ~16:00, got {[(w.start,w.end) for w in report.hard_windows]}"
# mid-morning should be calm (no agitation logged there)
assert any(w.start <= "09:00" < w.end for w in report.calm_windows), \
    f"expected a calm window covering ~09:00, got {[(w.start,w.end) for w in report.calm_windows]}"
print("\n[OK] calm windows: afternoon flagged hard, morning flagged calm")

# ---- 3. not-enough-data guard ---------------------------------------------
section("GUARD: too few days returns needs_more_data")
few = [LogEntry(patient_id="p1", type=EventType.WAKE,
                timestamp=datetime(2026, 9, 1, 11, 0))]
p2 = build_circadian_plan(few, CircadianConfig())
c2 = detect_calm_windows(few, CalmConfig())
print("circadian:", p2.status, "| calm:", c2.status)
assert p2.status == "needs_more_data" and c2.status == "needs_more_data"
print("[OK] both guard correctly on thin data")

# ---- 4. midnight-crossing sanity (circular mean) --------------------------
section("UNIT: circular mean handles midnight crossing")
cm = cb._circular_mean_minutes([23 * 60 + 50, 10])  # 23:50 and 00:10
print("mean of 23:50 and 00:10 =", cb._minutes_to_hhmm(cm))
assert cm is not None and (cm <= 5 or cm >= 24 * 60 - 5), "should be ~00:00"
print("[OK] circular mean correct across midnight")

# ---- 5. API endpoints via TestClient --------------------------------------
section("API: endpoints respond 200 with logs in body")
client = TestClient(app)
body = {"logs": [json.loads(l.model_dump_json()) for l in logs]}

r1 = client.post("/circadian-plan", json=body)
r2 = client.post("/calm-windows", json=body)
r3 = client.get("/health")
print("POST /circadian-plan ->", r1.status_code, "| status:", r1.json()["status"])
print("POST /calm-windows   ->", r2.status_code, "| status:", r2.json()["status"])
print("GET  /health         ->", r3.status_code, r3.json())
assert r1.status_code == 200 and r1.json()["status"] == "ok"
assert r2.status_code == 200 and r2.json()["status"] == "ok"
assert r3.status_code == 200

# by-id endpoint should return a clean 501 until fetch_patient_logs is filled
r4 = client.post("/circadian-plan/by-id/p1")
print("POST /circadian-plan/by-id/p1 ->", r4.status_code, "(expected 501 until DB wired)")
assert r4.status_code == 501
print("\n[OK] all endpoints behave correctly")

section("ALL TESTS PASSED")
