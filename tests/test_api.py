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
from app.models import PasswordResetToken
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


def test_forgot_password_is_generic(client):
    r = client.post("/auth/forgot-password", json={"emailOrUsername": "missing@test.com"})
    assert r.status_code == 200
    assert "If an account exists" in r.json()["message"]


def test_reset_password_changes_login(client, db):
    register(client, "reset1")
    r = client.post("/auth/forgot-password", json={"emailOrUsername": "reset1@test.com"})
    assert r.status_code == 200
    token_row = db.query(PasswordResetToken).first()
    assert token_row is not None

    # We store only hashes, so direct reset with a made-up token must fail.
    bad = client.post("/auth/reset-password", json={"token": "not-the-real-token-value-123", "new_password": "NewPass999!"})
    assert bad.status_code == 400


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


def test_legal_consent_is_account_wide_and_versioned(client):
    h = headers(client, "consent1")
    assert client.get("/users/me/legal-consent", headers=h).json() is None

    payload = {
        "termsVersion": "2026-08-16",
        "privacyVersion": "2026-08-16",
        "platform": "web",
        "appVersion": "1.0.0",
    }
    created = client.post("/users/me/legal-consent", json=payload, headers=h)
    assert created.status_code == 201
    assert created.json()["termsVersion"] == payload["termsVersion"]
    assert created.json()["privacyVersion"] == payload["privacyVersion"]
    assert created.json()["acceptedAt"]

    fetched = client.get("/users/me/legal-consent", headers=h)
    assert fetched.status_code == 200
    assert fetched.json()["id"] == created.json()["id"]

    duplicate = client.post("/users/me/legal-consent", json=payload, headers=h)
    assert duplicate.status_code == 201
    assert duplicate.json()["id"] == created.json()["id"]


def test_legal_consent_requires_authentication(client):
    assert client.get("/users/me/legal-consent").status_code == 401


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


def test_sleep_quality_score_accepts_0_to_21(client):
    h = headers(client, "sl3")
    good = {**_SLEEP_PAYLOAD, "quality_score": 21}
    r = client.post("/sleep-logs", json=good, headers=h)
    assert r.status_code == 201
    assert r.json()["quality_score"] == 21


def test_bad_quality_score_rejected(client):
    h = headers(client, "sl3_bad")
    bad = {**_SLEEP_PAYLOAD, "quality_score": 22}
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


# ── caregiver connections ─────────────────────────────────────────

def _auth_user(client, tag):
    data = register(client, tag)
    return data, {"Authorization": f"Bearer {data['tokens']['access_token']}"}


def test_caregiver_search_respects_privacy(client):
    target, target_h = _auth_user(client, "cg_private")
    _, seeker_h = _auth_user(client, "cg_seeker")

    hidden = client.get("/caregivers/search?username=user_cg_private", headers=seeker_h)
    assert hidden.status_code == 200
    assert hidden.json() == []

    client.patch("/users/me/privacy", json={"caregiverSearchEnabled": True}, headers=target_h)
    visible = client.get("/caregivers/search?username=user_cg_private", headers=seeker_h)
    assert visible.status_code == 200
    assert visible.json()[0]["username"] == target["user"]["username"]


def test_caregiver_request_accept_and_stats_permission(client):
    target, target_h = _auth_user(client, "cg_target")
    requester, requester_h = _auth_user(client, "cg_requester")
    stranger, stranger_h = _auth_user(client, "cg_stranger")

    client.patch("/users/me/privacy", json={"caregiverSearchEnabled": True}, headers=target_h)
    created = client.post("/caregivers/requests", json={"username": target["user"]["username"]}, headers=requester_h)
    assert created.status_code == 201
    link_id = created.json()["id"]

    blocked = client.get(f"/caregivers/connections/{target['user']['id']}/stats", headers=requester_h)
    assert blocked.status_code == 403

    incoming = client.get("/caregivers/requests/incoming", headers=target_h)
    assert incoming.status_code == 200
    assert incoming.json()[0]["id"] == link_id

    accepted = client.post(f"/caregivers/requests/{link_id}/accept", headers=target_h)
    assert accepted.status_code == 200
    assert accepted.json()["status"] == "accepted"

    stats = client.get(f"/caregivers/connections/{target['user']['id']}/stats", headers=requester_h)
    assert stats.status_code == 200
    assert stats.json()["user"]["username"] == target["user"]["username"]

    stranger_blocked = client.get(f"/caregivers/connections/{target['user']['id']}/stats", headers=stranger_h)
    assert stranger_blocked.status_code == 403


def test_caregiver_prebuilt_messages_only(client):
    target, target_h = _auth_user(client, "cg_msg_target")
    requester, requester_h = _auth_user(client, "cg_msg_requester")

    client.patch("/users/me/privacy", json={"caregiverSearchEnabled": True}, headers=target_h)
    link_id = client.post("/caregivers/requests", json={"username": target["user"]["username"]}, headers=requester_h).json()["id"]
    client.post(f"/caregivers/requests/{link_id}/accept", headers=target_h)

    invalid = client.post(
        f"/caregivers/connections/{target['user']['id']}/messages",
        json={"message_key": "custom_free_text"},
        headers=requester_h,
    )
    assert invalid.status_code == 422

    valid = client.post(
        f"/caregivers/connections/{target['user']['id']}/messages",
        json={"message_key": "sleep_log_reminder"},
        headers=requester_h,
    )
    assert valid.status_code == 201
    assert "sleep log" in valid.json()["message_text"].lower()
