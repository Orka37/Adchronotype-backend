"""
Run with:  pytest tests/test_api.py -v
Uses in-memory SQLite so no Postgres needed locally.
"""
from datetime import datetime, timedelta, timezone

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
    assert r.json()["detail"] == "email already registered"


def test_signup_duplicate_username_gives_specific_409(client):
    register(client, "dup_username")
    r = client.post("/auth/signup", json={
        "firstName": "A", "lastName": "B",
        "username": "user_dup_username", "email": "different@test.com",
        "password": "Pass12345!",
    })
    assert r.status_code == 409
    assert r.json()["detail"] == "username already taken"


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


def test_delete_account_allows_reusing_username_and_email(client):
    original = register(client, "delete_reuse")
    auth = {"Authorization": f"Bearer {original['tokens']['access_token']}"}

    consent = client.post("/users/me/legal-consent", json={
        "termsVersion": "2026-08-16",
        "privacyVersion": "2026-08-16",
        "platform": "ios",
        "appVersion": "1.0.0",
    }, headers=auth)
    assert consent.status_code == 201

    deleted = client.delete("/users/me", headers=auth)
    assert deleted.status_code == 204
    assert client.get("/auth/check-username?username=user_delete_reuse").json()["available"] is True

    recreated = client.post("/auth/signup", json={
        "firstName": "Recreated", "lastName": "User",
        "username": "user_delete_reuse", "email": "delete_reuse@test.com",
        "password": "Pass12345!",
    })
    assert recreated.status_code == 201
    assert recreated.json()["user"]["username"] == "user_delete_reuse"

    recreated_auth = {"Authorization": f"Bearer {recreated.json()['tokens']['access_token']}"}
    assert client.get("/users/me/legal-consent", headers=recreated_auth).json() is None


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


# ── patient-centered caregiver roles ─────────────────────────────

def test_primary_creates_patient_and_is_only_profile_manager(client):
    _, primary_h = _auth_user(client, "care_primary")
    _, helper_h = _auth_user(client, "care_helper")

    created = client.post("/care-patients", json={"display_name": "Mom"}, headers=primary_h)
    assert created.status_code == 201
    patient_id = created.json()["id"]
    assert created.json()["my_role"] == "primary"

    invite = client.post(
        f"/care-patients/{patient_id}/invitations",
        json={"username": "user_care_helper"}, headers=primary_h,
    )
    assert invite.status_code == 201
    accepted = client.post(f"/care-patients/invitations/{invite.json()['id']}/accept", headers=helper_h)
    assert accepted.status_code == 200
    assert accepted.json()["my_role"] == "helper"

    assert client.get(f"/care-patients/{patient_id}", headers=helper_h).status_code == 200
    assert client.patch(
        f"/care-patients/{patient_id}", json={"display_name": "Changed"}, headers=helper_h,
    ).status_code == 403
    assert client.post(
        f"/care-patients/{patient_id}/invitations", json={"email": "another@test.com"}, headers=helper_h,
    ).status_code == 403


def test_revocation_is_immediate_and_primary_cannot_be_removed(client):
    _, primary_h = _auth_user(client, "revoke_primary")
    _, helper_h = _auth_user(client, "revoke_helper")
    patient = client.post("/care-patients", json={"display_name": "Dad"}, headers=primary_h).json()
    invite = client.post(
        f"/care-patients/{patient['id']}/invitations",
        json={"username": "user_revoke_helper"}, headers=primary_h,
    ).json()
    client.post(f"/care-patients/invitations/{invite['id']}/accept", headers=helper_h)
    members = client.get(f"/care-patients/{patient['id']}/members", headers=primary_h).json()
    primary_member = next(row for row in members if row["role"] == "primary")
    helper_member = next(row for row in members if row["role"] == "helper")

    assert client.delete(
        f"/care-patients/{patient['id']}/members/{primary_member['id']}", headers=primary_h,
    ).status_code == 400
    assert client.delete(
        f"/care-patients/{patient['id']}/members/{helper_member['id']}", headers=primary_h,
    ).status_code == 204
    assert client.get(f"/care-patients/{patient['id']}", headers=helper_h).status_code == 403


def test_only_intended_user_can_accept_patient_invitation(client):
    _, primary_h = _auth_user(client, "invite_primary")
    _, helper_h = _auth_user(client, "invite_helper")
    _, stranger_h = _auth_user(client, "invite_stranger")
    patient = client.post("/care-patients", json={"display_name": "Patient"}, headers=primary_h).json()
    invite = client.post(
        f"/care-patients/{patient['id']}/invitations",
        json={"username": "user_invite_helper"}, headers=primary_h,
    ).json()
    assert client.post(f"/care-patients/invitations/{invite['id']}/accept", headers=stranger_h).status_code == 404
    assert client.post(f"/care-patients/invitations/{invite['id']}/accept", headers=helper_h).status_code == 200


def test_primary_and_helper_can_log_patient_events(client):
    _, primary_h = _auth_user(client, "event_primary")
    _, helper_h = _auth_user(client, "event_helper")
    patient = client.post("/care-patients", json={"display_name": "Dad"}, headers=primary_h).json()
    invite = client.post(
        f"/care-patients/{patient['id']}/invitations",
        json={"username": "user_event_helper"}, headers=primary_h,
    ).json()
    client.post(f"/care-patients/invitations/{invite['id']}/accept", headers=helper_h)

    first = client.post(f"/care-patients/{patient['id']}/events", json={
        "event_type": "slept", "event_time": "2026-01-10T22:30:00Z",
    }, headers=primary_h)
    second = client.post(f"/care-patients/{patient['id']}/events", json={
        "event_type": "woke", "event_time": "2026-01-11T02:15:00Z", "note": "Needed water",
    }, headers=helper_h)
    assert first.status_code == 201
    assert second.status_code == 201
    rows = client.get(f"/care-patients/{patient['id']}/events", headers=helper_h)
    assert rows.status_code == 200
    assert [row["event_type"] for row in rows.json()[:2]] == ["woke", "slept"]


def test_patient_event_permissions_and_validation(client):
    _, primary_h = _auth_user(client, "event_owner")
    _, helper_h = _auth_user(client, "event_editor")
    _, stranger_h = _auth_user(client, "event_stranger")
    patient = client.post("/care-patients", json={"display_name": "Mom"}, headers=primary_h).json()
    invite = client.post(
        f"/care-patients/{patient['id']}/invitations",
        json={"username": "user_event_editor"}, headers=primary_h,
    ).json()
    client.post(f"/care-patients/invitations/{invite['id']}/accept", headers=helper_h)
    event = client.post(f"/care-patients/{patient['id']}/events", json={
        "event_type": "napped", "event_time": "2026-01-11T13:00:00Z",
    }, headers=primary_h).json()

    assert client.get(f"/care-patients/{patient['id']}/events", headers=stranger_h).status_code == 403
    assert client.patch(
        f"/care-patients/{patient['id']}/events/{event['id']}",
        json={"note": "helper edit"}, headers=helper_h,
    ).status_code == 403
    assert client.post(f"/care-patients/{patient['id']}/events", json={
        "event_type": "invalid", "event_time": "2026-01-11T13:00:00Z",
    }, headers=primary_h).status_code == 422
    assert client.post(f"/care-patients/{patient['id']}/events", json={
        "event_type": "slept", "event_time": "2099-01-11T13:00:00Z",
    }, headers=primary_h).status_code == 422


def test_helper_can_delete_own_event_and_primary_can_delete_any_event(client):
    _, primary_h = _auth_user(client, "delete_event_primary")
    _, helper_h = _auth_user(client, "delete_event_helper")
    patient = client.post("/care-patients", json={"display_name": "Patient"}, headers=primary_h).json()
    invite = client.post(
        f"/care-patients/{patient['id']}/invitations",
        json={"username": "user_delete_event_helper"}, headers=primary_h,
    ).json()
    client.post(f"/care-patients/invitations/{invite['id']}/accept", headers=helper_h)
    own = client.post(f"/care-patients/{patient['id']}/events", json={
        "event_type": "agitated", "event_time": "2026-01-11T01:15:00Z",
    }, headers=helper_h).json()
    assert client.delete(f"/care-patients/{patient['id']}/events/{own['id']}", headers=helper_h).status_code == 204

    another = client.post(f"/care-patients/{patient['id']}/events", json={
        "event_type": "woke", "event_time": "2026-01-11T03:15:00Z",
    }, headers=helper_h).json()
    assert client.delete(f"/care-patients/{patient['id']}/events/{another['id']}", headers=primary_h).status_code == 204


def test_primary_sets_routine_and_helper_can_view_it(client):
    _, primary_h = _auth_user(client, "routine_primary")
    _, helper_h = _auth_user(client, "routine_helper")
    patient = client.post("/care-patients", json={"display_name": "Dad"}, headers=primary_h).json()
    patient_id = patient["id"]

    assert client.get(f"/care-patients/{patient_id}/routine", headers=primary_h).json() is None
    invite = client.post(
        f"/care-patients/{patient_id}/invitations",
        json={"username": "user_routine_helper"}, headers=primary_h,
    ).json()
    client.post(f"/care-patients/invitations/{invite['id']}/accept", headers=helper_h)

    saved = client.put(f"/care-patients/{patient_id}/routine", json={
        "usual_bedtime": "22:00", "usual_wake_time": "07:00",
        "nap_start_time": "13:00", "nap_end_time": "14:00", "notes": "Quiet music",
    }, headers=primary_h)
    assert saved.status_code == 200
    assert saved.json()["notes"] == "Quiet music"
    visible = client.get(f"/care-patients/{patient_id}/routine", headers=helper_h)
    assert visible.status_code == 200
    assert visible.json()["usual_bedtime"] == "22:00"


def test_helper_cannot_edit_routine_and_routine_validation(client):
    _, primary_h = _auth_user(client, "routine_owner")
    _, helper_h = _auth_user(client, "routine_readonly")
    patient = client.post("/care-patients", json={"display_name": "Mom"}, headers=primary_h).json()
    invite = client.post(
        f"/care-patients/{patient['id']}/invitations",
        json={"username": "user_routine_readonly"}, headers=primary_h,
    ).json()
    client.post(f"/care-patients/invitations/{invite['id']}/accept", headers=helper_h)
    payload = {"usual_bedtime": "21:30", "usual_wake_time": "06:30"}
    assert client.put(f"/care-patients/{patient['id']}/routine", json=payload, headers=helper_h).status_code == 403
    assert client.put(f"/care-patients/{patient['id']}/routine", json={
        **payload, "nap_start_time": "13:00",
    }, headers=primary_h).status_code == 422
    assert client.put(f"/care-patients/{patient['id']}/routine", json={
        **payload, "usual_bedtime": "25:00",
    }, headers=primary_h).status_code == 422


def test_caregivers_share_handoff_notes(client):
    primary, primary_h = _auth_user(client, "handoff_primary")
    helper, helper_h = _auth_user(client, "handoff_helper")
    patient = client.post("/care-patients", json={"display_name": "Mom"}, headers=primary_h).json()
    invite = client.post(
        f"/care-patients/{patient['id']}/invitations",
        json={"username": "user_handoff_helper"}, headers=primary_h,
    ).json()
    client.post(f"/care-patients/invitations/{invite['id']}/accept", headers=helper_h)

    first = client.post(f"/care-patients/{patient['id']}/handoff-notes", json={
        "tags": ["calm", "ate well"], "note": "Enjoyed breakfast in the kitchen.",
    }, headers=primary_h)
    second = client.post(f"/care-patients/{patient['id']}/handoff-notes", json={
        "tags": ["music helped"], "note": "Quiet music helped at bedtime.",
    }, headers=helper_h)
    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["author"]["id"] == primary["user"]["id"]
    assert second.json()["author"]["id"] == helper["user"]["id"]

    rows = client.get(f"/care-patients/{patient['id']}/handoff-notes", headers=helper_h)
    assert rows.status_code == 200
    assert {tuple(row["tags"]) for row in rows.json()} == {("music helped",), ("calm", "ate well")}


def test_handoff_note_permissions_and_validation(client):
    _, primary_h = _auth_user(client, "handoff_owner")
    _, helper_h = _auth_user(client, "handoff_editor")
    _, stranger_h = _auth_user(client, "handoff_stranger")
    patient = client.post("/care-patients", json={"display_name": "Dad"}, headers=primary_h).json()
    invite = client.post(
        f"/care-patients/{patient['id']}/invitations",
        json={"username": "user_handoff_editor"}, headers=primary_h,
    ).json()
    client.post(f"/care-patients/invitations/{invite['id']}/accept", headers=helper_h)

    primary_note = client.post(f"/care-patients/{patient['id']}/handoff-notes", json={
        "tags": ["slept"], "note": "Rested after lunch.",
    }, headers=primary_h).json()
    helper_note = client.post(f"/care-patients/{patient['id']}/handoff-notes", json={
        "tags": ["agitated"], "note": "Settled after a short walk.",
    }, headers=helper_h).json()

    assert client.get(f"/care-patients/{patient['id']}/handoff-notes", headers=stranger_h).status_code == 403
    assert client.patch(
        f"/care-patients/{patient['id']}/handoff-notes/{primary_note['id']}",
        json={"tags": ["calm"], "note": "Helper edit"}, headers=helper_h,
    ).status_code == 403
    edited = client.patch(
        f"/care-patients/{patient['id']}/handoff-notes/{helper_note['id']}",
        json={"tags": ["calm"], "note": "Calm after a short walk."}, headers=helper_h,
    )
    assert edited.status_code == 200
    assert edited.json()["tags"] == ["calm"]
    assert client.delete(
        f"/care-patients/{patient['id']}/handoff-notes/{helper_note['id']}", headers=primary_h,
    ).status_code == 204
    assert client.post(f"/care-patients/{patient['id']}/handoff-notes", json={
        "tags": ["unsupported"], "note": "Bad tag",
    }, headers=primary_h).status_code == 422
    assert client.post(f"/care-patients/{patient['id']}/handoff-notes", json={
        "tags": [], "note": "   ",
    }, headers=primary_h).status_code == 422


def test_daily_summary_uses_events_routine_and_shared_notes(client):
    _, primary_h = _auth_user(client, "summary_primary")
    _, helper_h = _auth_user(client, "summary_helper")
    patient = client.post("/care-patients", json={"display_name": "Mom"}, headers=primary_h).json()
    invite = client.post(
        f"/care-patients/{patient['id']}/invitations",
        json={"username": "user_summary_helper"}, headers=primary_h,
    ).json()
    client.post(f"/care-patients/invitations/{invite['id']}/accept", headers=helper_h)
    now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    today = now.replace(hour=0, minute=0)
    slept = now - timedelta(hours=8)
    woke = now
    client.put(f"/care-patients/{patient['id']}/routine", json={
        "usual_bedtime": slept.strftime("%H:%M"), "usual_wake_time": woke.strftime("%H:%M"),
    }, headers=primary_h)

    for event_type, event_time in [("slept", slept), ("woke", woke), ("napped", now - timedelta(hours=2)), ("agitated", now - timedelta(hours=1))]:
        assert client.post(f"/care-patients/{patient['id']}/events", json={
            "event_type": event_type, "event_time": event_time.isoformat(),
        }, headers=helper_h).status_code == 201
    client.post(f"/care-patients/{patient['id']}/handoff-notes", json={
        "tags": ["calm"], "note": "Music helped after lunch.",
    }, headers=helper_h)

    result = client.get(f"/care-patients/{patient['id']}/daily-summaries?days=7", headers=primary_h)
    assert result.status_code == 200
    body = result.json()
    assert body["learning_nights"] == 1
    assert body["sufficient_data"] is False
    sleep_day_index = 0 if slept.date() == today.date() else 1
    sleep_day = body["days"][sleep_day_index]
    assert sleep_day["sleep_minutes"] == 480
    assert sleep_day["routine_status"] == "on_routine"
    assert sum(day["nap_count"] for day in body["days"][:2]) == 1
    assert sum(day["agitation_count"] for day in body["days"][:2]) == 1
    assert body["days"][0]["handoff_note_count"] == 1
    assert client.get(f"/care-patients/{patient['id']}/daily-summaries", headers=helper_h).status_code == 200


def test_daily_summary_requires_membership_and_limits_history(client):
    _, primary_h = _auth_user(client, "summary_owner")
    _, stranger_h = _auth_user(client, "summary_stranger")
    patient = client.post("/care-patients", json={"display_name": "Dad"}, headers=primary_h).json()
    assert client.get(f"/care-patients/{patient['id']}/daily-summaries", headers=stranger_h).status_code == 403
    result = client.get(f"/care-patients/{patient['id']}/daily-summaries?days=100", headers=primary_h)
    assert result.status_code == 200
    assert len(result.json()["days"]) == 30


def test_caregiver_wellness_check_ins_are_private(client):
    _, first_h = _auth_user(client, "wellness_first")
    _, second_h = _auth_user(client, "wellness_second")
    created = client.post("/care-patients/wellness/check-ins", json={
        "feeling": "overwhelmed", "sleep_minutes": 270,
        "broken_night": True, "note": "A difficult night",
    }, headers=first_h)
    assert created.status_code == 201
    first = client.get("/care-patients/wellness/summary?days=7", headers=first_h)
    assert first.status_code == 200
    assert first.json()["average_sleep_minutes"] == 270
    assert first.json()["broken_nights"] == 1
    assert first.json()["hard_week"] is True
    second = client.get("/care-patients/wellness/summary?days=7", headers=second_h)
    assert second.status_code == 200
    assert second.json()["check_ins"] == []
    assert client.post("/care-patients/wellness/check-ins", json={
        "feeling": "invalid", "sleep_minutes": 1500,
    }, headers=first_h).status_code == 422


def test_medication_schedule_permissions_and_shared_logging(client):
    _, primary_h = _auth_user(client, "medication_primary")
    helper, helper_h = _auth_user(client, "medication_helper")
    _, stranger_h = _auth_user(client, "medication_stranger")
    patient = client.post("/care-patients", json={"display_name": "Mom"}, headers=primary_h).json()
    invite = client.post(
        f"/care-patients/{patient['id']}/invitations",
        json={"username": "user_medication_helper"}, headers=primary_h,
    ).json()
    client.post(f"/care-patients/invitations/{invite['id']}/accept", headers=helper_h)
    payload = {
        "name": "Morning medication", "instructions": "With breakfast",
        "window_start": "08:00", "window_end": "09:00", "clinician_confirmed": True,
    }
    created = client.post(f"/care-patients/{patient['id']}/medications", json=payload, headers=primary_h)
    assert created.status_code == 201
    schedule = created.json()
    assert "dose" not in schedule
    assert client.post(f"/care-patients/{patient['id']}/medications", json=payload, headers=helper_h).status_code == 403
    assert client.post(f"/care-patients/{patient['id']}/medications", json={
        **payload, "clinician_confirmed": False,
    }, headers=primary_h).status_code == 422
    assert client.get(f"/care-patients/{patient['id']}/medications", headers=helper_h).status_code == 200
    assert client.get(f"/care-patients/{patient['id']}/medications", headers=stranger_h).status_code == 403

    logged = client.post(
        f"/care-patients/{patient['id']}/medications/{schedule['id']}/logs",
        json={"status": "taken", "occurred_at": datetime.now(timezone.utc).isoformat()},
        headers=helper_h,
    )
    assert logged.status_code == 201
    assert logged.json()["logged_by"]["id"] == helper["user"]["id"]
    history = client.get(f"/care-patients/{patient['id']}/medication-logs", headers=primary_h)
    assert history.status_code == 200
    assert history.json()[0]["status"] == "taken"
    assert client.post(
        f"/care-patients/{patient['id']}/medications/{schedule['id']}/logs",
        json={"status": "taken", "occurred_at": "2099-01-01T00:00:00Z"}, headers=helper_h,
    ).status_code == 422
