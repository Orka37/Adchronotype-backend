import math
import pickle
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
import shap

from app.schemas import PredictRequest

_pkl_path = Path(__file__).resolve().parent.parent.parent / "ml_model.pkl"

with open(_pkl_path, "rb") as fh:
    _model = pickle.load(fh)

# max possible raw score from training data — used to normalise to 0-100%
# this value comes directly from the original Streamlit app: max_score = 67.37
_MAX_SCORE = 67.37

# SHAP explainer — built once at startup, reused for every request
_explainer = shap.TreeExplainer(_model)

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

_ALL_CHRONO = [
    "Chronotype_Definite Evening",
    "Chronotype_Definite Morning",
    "Chronotype_Intermediate",
    "Chronotype_Moderate Evening",
    "Chronotype_Moderate Morning",
]

_ALL_ETHNICITY = [
    "Ethnicity_African American",
    "Ethnicity_Caucasian",
    "Ethnicity_East Asian",
    "Ethnicity_Hispanic",
    "Ethnicity_Other",
    "Ethnicity_South Asian",
]


def _to_angle(t: str) -> float:
    """Convert HH:MM to radians so midnight and 23:59 are close together."""
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

    # one-hot encode categorical fields — reads from real user input
    for prefix, val in [
        ("Chronotype",    req.chronotype),
        ("Ethnicity",     req.ethnicity),
        ("FamilyHistory", req.family_history),
    ]:
        key = f"{prefix}_{val}"
        if key in row:
            row[key] = 1.0
        # unknown value silently stays 0 — treated as "other"

    return pd.DataFrame([row], columns=_COLS)


def _normalise(raw: float) -> float:
    """Convert raw model output (0–67.37) to a 0–100% score."""
    return round(float(np.clip(raw / _MAX_SCORE * 100, 0.0, 100.0)), 1)


def _risk_label(score: float) -> str:
    if score < 30:
        return "Low"
    if score < 60:
        return "Moderate"
    return "Elevated"


def run_prediction(req: PredictRequest) -> dict:
    features = _build_row(req)

    # ── 1. Main score ──────────────────────────────────────────────
    raw   = float(_model.predict(features)[0])
    score = _normalise(raw)

    # ── 2. SHAP factor contributions ───────────────────────────────
    shap_values  = _explainer(features).values[0]            # shape (n_features,)
    feature_map  = dict(zip(_COLS, shap_values))

    def factor_pct(keys: list) -> float:
        """Sum SHAP values for the given feature keys and normalise to %."""
        return round(float(sum(feature_map.get(k, 0.0) for k in keys) / _MAX_SCORE * 100), 1)

    # ── 3. Baseline ────────────────────────────────────────────────
    # expected_value = model's average prediction across all training data
    # add in SHAP for "inactive" features (ones the user didn't trigger)
    # and for family history + sleep duration, which we treat as baseline components
    inactive_shap = sum(
        feature_map.get(k, 0.0) for k in _ALL_CHRONO
        if k != f"Chronotype_{req.chronotype}"
    )
    inactive_shap += sum(
        feature_map.get(k, 0.0) for k in _ALL_ETHNICITY
        if k != f"Ethnicity_{req.ethnicity}"
    )
    family_shap   = feature_map.get("FamilyHistory_No", 0.0) + feature_map.get("FamilyHistory_Yes", 0.0)
    duration_shap = feature_map.get("SleepDuration", 0.0)

    baseline_raw  = float(_explainer.expected_value)
    baseline      = round((baseline_raw + family_shap + duration_shap + inactive_shap) / _MAX_SCORE * 100, 1)

    return {
        "score":      score,
        "risk_label": _risk_label(score),
        "baseline":   baseline,
        "factor_contributions": {
            "chronotype": factor_pct([f"Chronotype_{req.chronotype}"]),
            "age":        factor_pct(["Age"]),
            "bmi":        factor_pct(["BMI"]),
            "sleep_time": factor_pct(["SleepTime_sin", "SleepTime_cos"]),
            "wake_time":  factor_pct(["WakeTime_sin",  "WakeTime_cos"]),
            "ethnicity":  factor_pct([f"Ethnicity_{req.ethnicity}"]),
        },
    }
