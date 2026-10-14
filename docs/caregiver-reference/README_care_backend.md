# ADChronotype Caregiver Backend

Two caregiver features, as a ready-to-run FastAPI backend:

1. **Day-night reset** (`POST /circadian-plan`): takes the patient's recent
   logs and returns a personalized daily routine (morning light, nap limits,
   wind-down, target wake/bed) to pull a disrupted body clock back toward
   sleeping at night.
2. **Calm-window detection** (`POST /calm-windows`): takes the patient's
   agitation logs and returns which times of day they tend to be calm vs
   agitated, so routine care (e.g. bathing) can be planned in a calm window.

Important: there is **no ML model here and nothing to train.** Feature 1 is a
rules engine; feature 2 is simple per-patient statistics. The only trained
model in ADChronotype is the separate Phase-1 Cognitive Similarity Score model.

## Run it

```
pip install -r requirements.txt
uvicorn care_backend:app --reload
```

Then open `http://127.0.0.1:8000/docs` for interactive testing. It is already
verified to run; `python3 test_care_backend.py` runs the full test suite.

## Two ways to call it (pick one)

**Option A (easiest, no database wiring).** The app already has the patient's
logs, so POST them in the request body. These endpoints work immediately:

- `POST /circadian-plan`
- `POST /calm-windows`

See `sample_request.json` for an exact, valid body. Response shapes are the
`CircadianPlan` and `CalmReport` models in `care_backend.py`.

**Option B (backend pulls from the database).** If you would rather call by
patient id, fill in the single placeholder function `fetch_patient_logs()`
(search the file for `FILL THIS IN`) to read rows from your database and return
them as `LogEntry` objects. Then use:

- `POST /circadian-plan/by-id/{patient_id}`
- `POST /calm-windows/by-id/{patient_id}`

Until that function is implemented these return HTTP 501 by design.

## The one thing to fill in (Option B only)

`fetch_patient_logs(patient_id)` must return a list of `LogEntry`. Each log row
must have:

| field          | type              | notes                                        |
|----------------|-------------------|----------------------------------------------|
| `patient_id`   | str               | which patient                                |
| `type`         | str               | one of: wake, sleep, nap_start, nap_end, agitation, meal, meds_prepared |
| `timestamp`    | ISO 8601 datetime | e.g. `2026-09-01T11:15:00`                   |
| `duration_min` | int or null       | only for naps                                |
| `note`         | str or null       | optional free text                           |

The docstring on `fetch_patient_logs()` shows an example that reads from a
Supabase/Firebase-style `logs` table.

## What the app needs to send (the logging side)

The two features only need these logged events, each with a timestamp:
`wake`, `sleep`, `nap_start` (+ `duration_min`), and `agitation`. Keep logging
to one tap per event in the app; everything else here already handles the rest.

## Config is tunable

Both endpoints accept optional config in the body (`circadian_config`,
`calm_config`) to adjust target wake/bed, nap cutoff, wind-down length, bin
size, thresholds, etc. Sensible defaults are set, so config can be omitted.

## Files

- `care_backend.py` - the backend (all logic + endpoints)
- `test_care_backend.py` - test suite proving the logic and API work
- `sample_request.json` - a valid example request body
- `requirements.txt` - dependencies
