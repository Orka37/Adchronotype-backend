import math
import pickle
from pathlib import Path

import pandas as pd

from app.schemas import PredictRequest

_pkl_path = Path(__file__).resolve().parent.parent.parent / "ml_model.pkl"

with open(_pkl_path, "rb") as fh:
    _model = pickle.load(fh)

# column order must match training data exactly
_COLS = [
    "Age", "BMI",
    "SleepTime_sin", "SleepTime_cos",
    "WakeTime_sin",  "WakeTime_cos",
    "SleepDuration",
    "Chronotype_Definite Evening",
    "Chronotype_Definite Morning",
    "Chronotype_Intermediate",
    "Chronotype_Moderate Evening",
    "Chronotype_Moderate Morning",
    "Ethnicity_African American",
    "Ethnicity_Caucasian",
    "Ethnicity_East Asian",
    "Ethnicity_Hispanic",
    "Ethnicity_Other",
    "Ethnicity_South Asian",
    "FamilyHistory_No",
    "FamilyHistory_Yes",
]


def _to_angle(t: str) -> float:
    # convert HH:MM into radians so midnight and 11:59 PM are close together
    h, m = map(int, t.split(":"))
    return 2 * math.pi * (h * 60 + m) / 1440


def _build_row(req: PredictRequest) -> pd.DataFrame:
    sa = _to_angle(req.sleep_time)
    wa = _to_angle(req.wake_time)

    row = {c: 0.0 for c in _COLS}
    row["Age"]           = float(req.age)
    row["BMI"]           = req.bmi
    row["SleepTime_sin"] = math.sin(sa)
    row["SleepTime_cos"] = math.cos(sa)
    row["WakeTime_sin"]  = math.sin(wa)
    row["WakeTime_cos"]  = math.cos(wa)
    row["SleepDuration"] = req.sleep_duration

    # one-hot encode the categorical fields
    for prefix, val in [
        ("Chronotype", req.chronotype),
        ("Ethnicity",  req.ethnicity),
        ("FamilyHistory", req.family_history),
    ]:
        key = f"{prefix}_{val}"
        if key in row:
            row[key] = 1.0
        # if key not found we just leave it as 0 — unknown value treated as "other"

    return pd.DataFrame([row], columns=_COLS)


def _risk_label(score: float) -> str:
    if score < 0.30:
        return "Low"
    if score < 0.60:
        return "Moderate"
    return "Elevated"


def run_prediction(req: PredictRequest) -> tuple[float, str]:
    features = _build_row(req)
    raw = float(_model.predict(features)[0])
    score = round(max(0.0, min(1.0, raw)), 4)  # clamp to [0, 1]
    return score, _risk_label(score)
