from uuid import uuid4
from types import SimpleNamespace
import numpy as np
import pytest
from pydantic import ValidationError
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.services import similarity_service as service
from app.routers import similarity
from app.core.deps import get_current_user

UID = uuid4()


def payload(**kwargs):
    return service.IntakePayload(
        **(
            dict(
                patient_id=UID,
                chronotype_score=50,
                sleep_duration_hours=8,
                bedtime_consistency_std=1,
                bmi=22,
                family_history=1,
            )
            | kwargs
        )
    )


@pytest.mark.parametrize("values", [None, [], [1], [1, 2]])
def test_missing_samples(values):
    frame, flags = service.build_features(
        payload(dwell_times_ms=values, flight_times_ms=[3, 6, 9])
    )
    assert frame.columns.tolist() == service.FEATURES
    assert frame.iloc[0].dwell_time == 112.5
    assert frame.iloc[0].key_latency == 6
    assert flags == dict(dwell_time=True, key_latency=False)


def test_native_and_complete():
    frame, flags = service.build_features(payload(imputation_strategy="native"))
    assert frame.iloc[0][["dwell_time", "key_latency"]].isna().all()
    frame, flags = service.build_features(
        payload(dwell_times_ms=[1, 2, 3], flight_times_ms=[-1, 2, 5])
    )
    assert not any(flags.values())
    assert frame.iloc[0].dwell_time == 2
    assert frame.iloc[0].key_latency == 2


@pytest.mark.parametrize(
    "changes",
    [
        dict(bmi=float("nan")),
        dict(family_history=2),
        dict(sleep_duration_hours=25),
        dict(dwell_times_ms=[-1, 2, 3]),
        dict(flight_times_ms=[float("inf")]),
    ],
)
def test_invalid(changes):
    with pytest.raises(ValidationError):
        payload(**changes)


def test_outputs(monkeypatch):
    model = SimpleNamespace(predict=lambda f: [120.0])
    explainer = lambda f: SimpleNamespace(
        values=np.array([[100.0, 2.0, 3.0, 1.0, 200.0, 300.0, 400.0]]),
        base_values=np.array([-886.0]),
    )
    monkeypatch.setattr(service, "load_model", lambda: (model, explainer))
    result = service.run_similarity(payload())
    assert result["cognitive_similarity_score"] == 100
    assert result["raw_similarity_score"] == 120
    assert result["top_modifiable_factor"] == "sleep_variability"
    assert result["telemetry_imputed"]
    assert result["raw_similarity_score"] == result["shap_baseline"] + sum(
        result["shap_contributions"].values()
    )
    assert all(type(v) is float for v in result["shap_contributions"].values())


def test_missing_model(monkeypatch, tmp_path):
    service.load_model.cache_clear()
    monkeypatch.setattr(
        service,
        "get_settings",
        lambda: SimpleNamespace(SIMILARITY_MODEL_PATH=str(tmp_path / "absent.json")),
    )
    with pytest.raises(service.ModelUnavailable):
        service.load_model()


def test_route_authorization_errors(monkeypatch):
    app = FastAPI()
    app.include_router(similarity.router)
    client = TestClient(app)
    body = payload().model_dump(mode="json")
    assert client.post("/api/v1/predict_similarity", json=body).status_code == 401
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=uuid4())
    assert client.post("/api/v1/predict_similarity", json=body).status_code == 403
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=UID)

    def unavailable(_):
        raise service.ModelUnavailable("private path")

    monkeypatch.setattr(similarity, "run_similarity", unavailable)
    response = client.post("/api/v1/predict_similarity", json=body)
    assert response.status_code == 503
    assert "private path" not in response.text

    def bad(_):
        raise ValueError("private internal error")

    monkeypatch.setattr(similarity, "run_similarity", bad)
    assert client.post("/api/v1/predict_similarity", json=body).json() == {
        "detail": "Unable to calculate similarity"
    }


def test_model_path_from_dotenv(tmp_path):
    from app.core.config import Settings

    env_file = tmp_path / ".env"
    env_file.write_text("SIMILARITY_MODEL_PATH=/tmp/custom-v2.json\n")
    settings = Settings(_env_file=env_file)
    assert settings.SIMILARITY_MODEL_PATH == "/tmp/custom-v2.json"


def test_route_returns_serializable_result(monkeypatch):
    app = FastAPI()
    app.include_router(similarity.router)
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=UID)
    model = SimpleNamespace(predict=lambda f: [25.0])
    explanation = SimpleNamespace(values=np.zeros((1, 7)), base_values=np.array([25.0]))
    monkeypatch.setattr(service, "load_model", lambda: (model, lambda f: explanation))
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/predict_similarity", json=payload().model_dump(mode="json")
        )
    assert response.status_code == 200
    assert response.json()["top_modifiable_factor"] is None
    assert response.json()["cognitive_similarity_score"] == 25.0
