# Caregiver recommendations

The two features use the supplied care_backend.py rules and patient-log statistics,
not the CSS prediction model. Originals are preserved in docs/caregiver-reference.

## API

Authenticated POST `/circadian-plan/by-id/{patient_id}` and
`/calm-windows/by-id/{patient_id}` require active membership of that care record.
The server reads stored patient logs (integration option B). The unauthenticated
body-based demo endpoints are not mounted in the production application.

Request example:

```json
{"timezone":"America/Chicago","lookback_days":14,"circadian_config":{"target_wake":"07:30","target_bed":"21:30"},"calm_config":{"bin_minutes":60}}
```

Only timezone is required. All original settings remain optional and configurable.
The app asks the caregiver to confirm the patient's IANA time zone, initially
showing the device zone; it is request-scoped, not a saved patient preference.
History spans the requested trailing 1–90 days, excluding future events, and is
converted from UTC using the selected zone including daylight-saving offsets.
More than 10,000 rows returns 422 instead of silently truncating history. The UI's
250-row event limit does not limit the calculations. End-of-day is shown as 24:00.
Suggestions never overwrite the saved caregiver routine.

## Nap duration

Migration 20261007_0011 adds nullable care_patient_events.duration_min. Old clients
and old records remain valid; unknown durations are never guessed. New clients
may send 1–1440 minutes on napped events. Changing a nap to another type clears
its duration. Mapping: slept → sleep, woke → wake, napped → nap_start,
agitated → agitation. Other events are excluded from the engine.

## Integration guards

- Input validation prevents invalid clock times, nonpositive bin sizes and overlapping thresholds.
- Require the configured number of distinct sleep days AND wake days for a plan.
- Ambiguous circular means return needs_more_data.
- No recorded agitation returns needs_more_data, not all-day calm.
- Calm windows retain the lead's frequency calculation: fewer logged incidents
  are not confirmed calm. Rates use dates with any relevant event, not continuous
  observation. Missing logs can bias results; the UI explains this.
- Missing nap durations are called out in the generated notes.

Activities, thresholds and default timings remain those supplied by the lead.
Repeated requests recalculate from history; no persistent daily progression is
scheduled. The reference does not supply scientific citations or clinical validation.

## Test and release

Install requirements-dev.txt into a virtual environment. Run the original example:

```sh
python docs/caregiver-reference/test_care_backend.py
```

Run focused route/database tests without the ML runtime:

```sh
DATABASE_URL=sqlite:////tmp/adc-care-test.db JWT_SECRET_KEY=test-only python -m pytest tests/test_care_recommendations.py -q
```

Tests create their own isolated SQLite database and exercise real authentication,
patient access, nap persistence, log isolation, local time, defaults and overrides,
missing data, and migration upgrade/downgrade with an existing row.

Release backend first: apply `alembic upgrade head` through the established
migration process before serving the changed backend. Confirm API behavior with
a test care record, then release the frontend. Installed mobile apps need a new
mobile build; a web deployment alone does not update them. No production migration,
Git push, or deployment is performed by this local implementation.
