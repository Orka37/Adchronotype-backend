"""V2 inference; requires a separately trained seven-feature model."""
from functools import lru_cache
from pathlib import Path
import os
import numpy as np
import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, FiniteFloat
from typing import Annotated, Literal
from uuid import UUID

FEATURES = ["chronotype", "sleep_duration", "sleep_variability", "bmi", "family_history", "dwell_time", "key_latency"]
MODIFIABLE = ["sleep_duration", "sleep_variability", "bmi"]
# Values supplied for V2; must be confirmed against the training cohort.
MEDIANS = {"dwell_time": 112.5, "key_latency": 245.0}
Dwell = Annotated[FiniteFloat, Field(ge=0)]

class IntakePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    patient_id: UUID
    chronotype_score: FiniteFloat
    sleep_duration_hours: Annotated[FiniteFloat, Field(ge=0, le=24)]
    bedtime_consistency_std: Annotated[FiniteFloat, Field(ge=0)]
    bmi: Annotated[FiniteFloat, Field(gt=0)]
    family_history: Literal[0, 1]
    dwell_times_ms: list[Dwell] | None = Field(default=None, max_length=10000)
    # Signed flight intervals allow overlapping key presses.
    flight_times_ms: list[FiniteFloat] | None = Field(default=None, max_length=10000)
    imputation_strategy: Literal["median", "native"] = "median"

class ModelUnavailable(RuntimeError):
    pass

@lru_cache(maxsize=1)
def load_model():
    import xgboost as xgb
    import shap
    path = Path(os.environ.get("SIMILARITY_MODEL_PATH", str(Path(__file__).resolve().parents[2] / "adchronotype_xgboost_v2.json")))
    try:
        model = xgb.XGBRegressor()
        model.load_model(path)
        if model.get_booster().feature_names != FEATURES:
            raise ValueError("V2 model feature names or ordering do not match")
        return model, shap.TreeExplainer(model)
    except Exception as exc:
        raise ModelUnavailable("V2 model is unavailable or incompatible") from exc

def build_features(payload):
    imputed = {}
    def metric(values, name):
        imputed[name] = values is None or len(values) < 3
        if imputed[name]:
            return MEDIANS[name] if payload.imputation_strategy == "median" else np.nan
        # Divide first to avoid overflowing the sum of finite samples.
        return float(np.sum(np.asarray(values, dtype=float) / len(values)))
    row = [payload.chronotype_score, payload.sleep_duration_hours,
           payload.bedtime_consistency_std, payload.bmi, payload.family_history,
           metric(payload.dwell_times_ms, "dwell_time"),
           metric(payload.flight_times_ms, "key_latency")]
    return pd.DataFrame([row], columns=FEATURES), imputed

def run_similarity(payload):
    features, imputed = build_features(payload)
    model, explainer = load_model()
    raw = float(model.predict(features)[0])
    explanation = explainer(features)
    values = np.asarray(explanation.values, dtype=float)
    baseline = float(np.asarray(explanation.base_values).reshape(-1)[0])
    if values.shape != (1, len(FEATURES)) or not np.isfinite(values).all() or not np.isfinite([raw, baseline]).all():
        raise ValueError("Invalid V2 model output")
    impacts = {key: float(value) for key, value in zip(FEATURES, values[0])}
    positive = [key for key in MODIFIABLE if impacts[key] > 0]
    return dict(status="success", cognitive_similarity_score=round(float(np.clip(raw, 0, 100)), 1),
                raw_similarity_score=raw, shap_baseline=baseline,
                top_modifiable_factor=max(positive, key=impacts.get) if positive else None,
                shap_contributions=impacts, telemetry_imputed=any(imputed.values()),
                imputed_features=[key for key, missing in imputed.items() if missing],
                imputation_strategy=payload.imputation_strategy)
