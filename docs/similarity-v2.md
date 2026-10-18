# Similarity V2 integration

POST /api/v1/predict_similarity requires existing bearer authentication. patient_id must be the signed-in user UUID; caregiver patient IDs are not supported by this endpoint. This is inference only and does not persist a prediction or replace /predictions and its history contract. The existing app continues using /predictions until an intake/UI migration is implemented.

Supply adchronotype_xgboost_v2.json at repository root or set SIMILARITY_MODEL_PATH. The model must contain the seven named features in the exact order in similarity_service.FEATURES. Missing/incompatible artifacts return 503 without preventing the existing API from starting. The model is cached after successful loading; restart after replacing it.

The supplied median values 112.5 and 245.0 are provisional training metadata, not independently verified. Confirm them, feature units (especially sleep variability), preprocessing, score units and feature ordering with the model owner before rollout. No artifact or evidence for the supplied 319 subjects / RMSE 9.9 claims was found; these claims are not validated by this integration.

Absent, empty or fewer than three telemetry samples count as missing independently for dwell and flight. Default median strategy uses the supplied constants; native strategy passes NaN to XGBoost. Finite numeric validation rejects NaN/infinity in intake. Dwell times must be nonnegative; flight intervals may be signed. Telemetry arrays are capped at 10000 entries each.

SHAP contributions and shap_baseline explain raw_similarity_score, not the clipped/rounded display score. top_modifiable_factor selects the largest positive contribution among sleep duration, sleep variability and BMI, or null if none is positive. It is not a causal recommendation. Chronotype, family history and keystroke measurements are excluded from that selection.

This backend addition needs the real V2 artifact and an authenticated end-to-end test before use. Unit tests with fake estimator outputs check plumbing only, not model accuracy.
