"""
Run with:  pytest tests/test_api.py -v
Uses in-memory SQLite so no Postgres needed locally.
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.main as main_module
from app.database import Base, get_db
from app.main import app

_engine = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
_Session = sessionmaker(autocommit=False, autoflush=False, bind=_engine)


@pytest.fixture(scope="session", autouse=True)
def _tables():
    Base.metadata.create_all(bind=_engine)
    yield
    Base.metadata.drop_all(bind=_engine)


@pytest.fixture()
def db():
    s = _Session()
    try:
        yield s
    finally:
        s.rollback()
        s.close()


@pytest.fixture()
def client(db):
    main_module.engine = _engine
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


# ── helpers ───────────────────────────────────────────────────────

def register(client, tag="u"):
    r = client.post("/auth/signup", json={
        "firstName": "Test", "lastName": "User",
        "username": f"user_{tag}", "email": f"{tag}@test.com",
        "password": "Pass12345!",
    })
    assert r.status_code == 201
    return r.json()


def headers(client, tag="u"):
    data = register(client, tag)
    return {"Authorization": f"Bearer {data['tokens']['access_token']}"}


# ── health ────────────────────────────────────────────────────────

def test_health(client):
    assert client.get("/health").json() == {"status": "ok", "database": "ok"}


# ── signup ────────────────────────────────────────────────────────

def test_signup_returns_tokens(client):
    r = register(client, "signup1")
    assert "access_token" in r["tokens"]
    assert "refresh_token" in r["tokens"]
    assert r["user"]["username"] == "user_signup1"


def test_signup_duplicate_email_gives_409(client):
    register(client, "dup")
    r = client.post("/auth/signup", json={
        "firstName": "A", "lastName": "B",
        "username": "user_dup2", "email": "dup@test.com",
        "password": "Pass12345!",
    })
    assert r.status_code == 409


def test_signup_short_password_gives_422(client):
    r = client.post("/auth/signup", json={
        "firstName": "A", "lastName": "B",
        "username": "short_pw", "email": "short@test.com",
        "password": "abc",
    })
    assert r.status_code == 422


# ── login ─────────────────────────────────────────────────────────

def test_login_with_email(client):
    register(client, "login1")
    r = client.post("/auth/login", json={"emailOrUsername": "login1@test.com", "password": "Pass12345!"})
    assert r.status_code == 200
    assert r.json()["tokens"]["token_type"] == "bearer"


def test_login_with_username(client):
    register(client, "login2")
    r = client.post("/auth/login", json={"emailOrUsername": "user_login2", "password": "Pass12345!"})
    assert r.status_code == 200


def test_wrong_password_gives_401(client):
    register(client, "badpw")
    r = client.post("/auth/login", json={"emailOrUsername": "badpw@test.com", "password": "nope"})
    assert r.status_code == 401


# ── token refresh / logout ────────────────────────────────────────

def test_token_refresh_works(client):
    data = register(client, "ref1")
    r = client.post("/auth/refresh", json={"refresh_token": data["tokens"]["refresh_token"]})
    assert r.status_code == 200
    assert "access_token" in r.json()


def test_reusing_revoked_token_fails(client):
    data = register(client, "rev1")
    tok = data["tokens"]["refresh_token"]
    hdrs = {"Authorization": f"Bearer {data['tokens']['access_token']}"}

    client.post("/auth/logout", json={"refresh_token": tok}, headers=hdrs)
    r = client.post("/auth/refresh", json={"refresh_token": tok})
    assert r.status_code == 401


def test_username_available(client):
    assert client.get("/auth/check-username?username=totally_new").json()["available"] is True


def test_username_taken(client):
    register(client, "taken1")
    assert client.get("/auth/check-username?username=user_taken1").json()["available"] is False


# ── user profile ──────────────────────────────────────────────────

def test_get_profile(client):
    h = headers(client, "prof1")
    r = client.get("/users/me", headers=h)
    assert r.status_code == 200
    assert r.json()["username"] == "user_prof1"


def test_no_token_gives_401(client):
    assert client.get("/users/me").status_code == 401


def test_update_name(client):
    h = headers(client, "upd1")
    r = client.patch("/users/me", json={"firstName": "NewName"}, headers=h)
    assert r.status_code == 200
    assert r.json()["firstName"] == "NewName"


def test_change_password(client):
    h = headers(client, "cpw1")
    r = client.post("/users/me/change-password",
                    json={"current_password": "Pass12345!", "new_password": "NewPass999!"},
                    headers=h)
    assert r.status_code == 204


def test_change_password_wrong_current(client):
    h = headers(client, "cpw2")
    r = client.post("/users/me/change-password",
                    json={"current_password": "wrong", "new_password": "NewPass999!"},
                    headers=h)
    assert r.status_code == 400


# ── sleep logs ────────────────────────────────────────────────────

_SLEEP_PAYLOAD = {
    "sleep_time": "22:30", "wake_time": "06:30",
    "duration_hours": 8.0, "quality_score": 4,
    "awakenings": 1, "logged_date": "2026-01-10T22:30:00Z",
}


def test_create_sleep_log(client):
    h = headers(client, "sl1")
    r = client.post("/sleep-logs", json=_SLEEP_PAYLOAD, headers=h)
    assert r.status_code == 201
    assert r.json()["quality_score"] == 4


def test_list_sleep_logs(client):
    h = headers(client, "sl2")
    client.post("/sleep-logs", json=_SLEEP_PAYLOAD, headers=h)
    r = client.get("/sleep-logs", headers=h)
    assert len(r.json()) >= 1


def test_bad_quality_score_rejected(client):
    h = headers(client, "sl3")
    bad = {**_SLEEP_PAYLOAD, "quality_score": 9}
    assert client.post("/sleep-logs", json=bad, headers=h).status_code == 422


def test_delete_sleep_log(client):
    h = headers(client, "sl4")
    log_id = client.post("/sleep-logs", json=_SLEEP_PAYLOAD, headers=h).json()["id"]
    assert client.delete(f"/sleep-logs/{log_id}", headers=h).status_code == 204
    assert client.get(f"/sleep-logs/{log_id}", headers=h).status_code == 404


# ── cognitive tests ───────────────────────────────────────────────

def test_submit_reaction_test(client):
    h = headers(client, "cog1")
    r = client.post("/cognitive-tests", json={
        "test_type": "reaction", "score": 243.0,
        "unit": "ms", "tested_at": "2026-01-10T10:00:00Z",
    }, headers=h)
    assert r.status_code == 201
    assert r.json()["test_type"] == "reaction"


def test_invalid_test_type_rejected(client):
    h = headers(client, "cog2")
    r = client.post("/cognitive-tests", json={
        "test_type": "made_up", "score": 100.0,
        "unit": "ms", "tested_at": "2026-01-10T10:00:00Z",
    }, headers=h)
    assert r.status_code == 422


def test_personal_bests_endpoint(client):
    h = headers(client, "cog3")
    client.post("/cognitive-tests", json={
        "test_type": "memory", "score": 88.0,
        "unit": "%", "tested_at": "2026-01-10T10:00:00Z",
    }, headers=h)
    bests = client.get("/cognitive-tests/personal-bests", headers=h).json()
    assert bests["memory"] == 88.0


def test_filter_by_test_type(client):
    h = headers(client, "cog4")
    for t in ["reaction", "stroop", "reaction"]:
        client.post("/cognitive-tests", json={
            "test_type": t, "score": 250.0,
            "unit": "ms", "tested_at": "2026-01-10T10:00:00Z",
        }, headers=h)
    results = client.get("/cognitive-tests?test_type=reaction", headers=h).json()
    assert all(r["test_type"] == "reaction" for r in results)
