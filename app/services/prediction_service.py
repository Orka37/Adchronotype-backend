import json
from pathlib import Path
import logging

import joblib
import numpy as np
import pandas as pd
import shap

from app.schemas import PredictRequest

_pkl_path = Path(__file__).resolve().parent.parent.parent / "ml_model.pkl"
logger = logging.getLogger("adchronotype.prediction_service")

_model = joblib.load(_pkl_path)

# max possible raw score from training data — used to normalise to 0-100%
# this value comes directly from the original Streamlit app: max_score = 67.37
_MAX_SCORE = 67.37

# SHAP explainer — built once at startup, reused for every request
_explainer = shap.TreeExplainer(_model)


def _saved_base_score() -> float:
    booster = _model.get_booster()
    config = json.loads(booster.save_config())
    raw = config["learner"]["learner_model_param"]["base_score"]
    if isinstance(raw, str) and raw.startswith("["):
        return float(json.loads(raw)[0])
    return float(raw)


_MODEL_BASE_SCORE = _saved_base_score()

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


def _to_decimal_hour(t: str) -> float:
    h, m = map(int, t.split(":"))
    return h + (m / 60.0)


def _normalise_family_history(value: str) -> str:
    # The Streamlit reference model currently hardcodes family history to "No".
    return "No"


def _build_row(req: PredictRequest) -> pd.DataFrame:
    sleep_numeric = float(_to_decimal_hour(req.sleep_time))
    wake_numeric = float(_to_decimal_hour(req.wake_time))
    sleep_hrs = (wake_numeric - sleep_numeric) % 24

    row = {c: 0.0 for c in _COLS}
    row["Age"]           = float(req.age)
    row["BMI"]           = float(req.bmi)
    row["SleepTime_sin"] = np.sin(2 * np.pi * sleep_numeric / 24)
    row["SleepTime_cos"] = np.cos(2 * np.pi * sleep_numeric / 24)
    row["WakeTime_sin"]  = np.sin(2 * np.pi * wake_numeric / 24)
    row["WakeTime_cos"]  = np.cos(2 * np.pi * wake_numeric / 24)
    row["SleepDuration"] = sleep_hrs

    # One-hot encode categorical fields in the same column set/order as Streamlit.
    for prefix, val in [
        ("Chronotype",    req.chronotype),
        ("Ethnicity",     req.ethnicity),
        ("FamilyHistory", _normalise_family_history(req.family_history)),
    ]:
        key = f"{prefix}_{val}"
        if key in row:
            row[key] = 1.0
        # unknown categorical values stay zero, matching the model's training columns

    return pd.DataFrame([row], columns=_COLS)



def _risk_label(score: float) -> str:
    if score < 30:
        return "Low"
    if score < 60:
        return "Moderate"
    return "Elevated"


def risk_label_for_score(score: float) -> str:
    return _risk_label(score)


def run_prediction(req: PredictRequest) -> dict:
    features = _build_row(req)
    model_prediction = float(_model.predict(features)[0])

    # SHAP factor contributions match the Streamlit reference app.
    shap_values  = _explainer(features).values[0]            # shape (n_features,)
    feature_map  = dict(zip(_COLS, shap_values))
    raw_prediction = _MODEL_BASE_SCORE + float(sum(shap_values))
    score = round(float(min(max(raw_prediction / _MAX_SCORE * 100, 0), 100)), 1)

    def factor_pct(keys: list) -> float:
        """Sum SHAP values for the given feature keys and normalise to %."""
        return round(float(sum(feature_map.get(k, 0.0) for k in keys) / _MAX_SCORE * 100), 1)

    # Baseline mirrors Streamlit: expected value plus hidden/input factors.
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

    baseline_raw  = float(round(_MODEL_BASE_SCORE, 1))
    baseline_raw_with_hidden_factors = baseline_raw + family_shap + duration_shap + inactive_shap
    baseline = round(baseline_raw_with_hidden_factors / _MAX_SCORE * 100, 1)

    factor_contributions = {
        "chronotype": factor_pct([f"Chronotype_{req.chronotype}"]),
        "age":        factor_pct(["Age"]),
        "bmi":        factor_pct(["BMI"]),
        "sleep_time": factor_pct(["SleepTime_sin", "SleepTime_cos"]),
        "wake_time":  factor_pct(["WakeTime_sin",  "WakeTime_cos"]),
        "ethnicity":  factor_pct([f"Ethnicity_{req.ethnicity}"]),
    }

    logger.info(
        "prediction_calculated calculation_mode=streamlit_shap_additive_v2 raw_prediction=%s model_prediction=%s score=%s baseline=%s",
        round(raw_prediction, 4),
        round(model_prediction, 4),
        score,
        baseline,
    )

    return {
        "score":      score,
        "risk_label": _risk_label(score),
        "baseline":   baseline,
        "factor_contributions": factor_contributions,
    }
