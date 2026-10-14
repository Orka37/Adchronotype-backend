from unittest.mock import patch
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.database import Base, get_db
from app.models import User
from app.routers import auth
from app.services import google_identity
from app.core.security import decode_refresh_token

CLAIMS={'sub':'google-user-123','email':'member@gmail.com','email_verified':True,'given_name':'Test','family_name':'Member','aud':'web-client','iss':'https://accounts.google.com'}

@pytest.fixture
def setup():
    engine=create_engine('sqlite://',connect_args={'check_same_thread':False},poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine)() as db:
        app=FastAPI();app.include_router(auth.router);app.dependency_overrides[get_db]=lambda:db
        with TestClient(app) as client, patch.object(auth,'verify_google_identity',return_value=CLAIMS.copy()):
            yield client,db
    engine.dispose()

def login(client,**kw):return client.post('/auth/google',json={'id_token':'signed-token',**kw})

def test_signup_repeat_and_refresh(setup):
    c,db=setup
    first=login(c);assert first.status_code==200
    uid=first.json()['user']['id'];tokens=first.json()['tokens']
    assert decode_refresh_token(tokens['refresh_token'])==uid
    assert login(c).json()['user']['id']==uid
    assert db.query(User).count()==1
    assert c.post('/auth/refresh',json={'refresh_token':tokens['refresh_token']}).status_code==200

def test_existing_password_requires_proof_then_still_works(setup):
    c,db=setup
    body={'firstName':'Test','lastName':'Member','username':'existing','email':'member@gmail.com','password':'StrongPass123!'}
    created=c.post('/auth/signup',json=body);assert created.status_code==201
    assert login(c).status_code==409
    assert login(c,current_password='wrong').status_code==409
    linked=login(c,current_password=body['password']);assert linked.status_code==200
    assert linked.json()['user']['id']==created.json()['user']['id']
    assert login(c).status_code==200
    assert c.post('/auth/login',json={'emailOrUsername':'existing','password':body['password']}).status_code==200
    assert db.query(User).count()==1

def test_disabled_account_blocked(setup):
    c,db=setup;assert login(c).status_code==200
    user=db.query(User).one();user.is_active=False;db.commit()
    assert login(c).status_code==403

def test_google_subject_wins_over_changed_email(setup):
    c,db=setup;uid=login(c).json()['user']['id']
    with patch.object(auth,'verify_google_identity',return_value={**CLAIMS,'email':'new@gmail.com'}):
        assert login(c).json()['user']['id']==uid
    assert db.query(User).count()==1

def test_different_google_identity_cannot_relink(setup):
    c,db=setup;login(c)
    with patch.object(auth,'verify_google_identity',return_value={**CLAIMS,'sub':'different'}):
        assert login(c).status_code==409

def test_invalid_credentials_forwarded(setup):
    c,db=setup
    with patch.object(auth,'verify_google_identity',side_effect=HTTPException(401,'Invalid token')):
        assert login(c).status_code==401
    assert db.query(User).count()==0

@pytest.mark.parametrize('changes',[{'aud':'wrong'},{'iss':'evil'},{'email_verified':False},{'sub':''},{'email':''}])
def test_claim_validation(changes):
    with patch.object(google_identity.id_token,'verify_oauth2_token',return_value={**CLAIMS,**changes}):
        with pytest.raises(HTTPException) as e:google_identity.verify_google_identity('token','web-client')
        assert e.value.status_code==401

def test_signature_and_expiry_errors_rejected():
    with patch.object(google_identity.id_token,'verify_oauth2_token',side_effect=ValueError('expired')) as verify:
        with pytest.raises(HTTPException) as e:google_identity.verify_google_identity('bad','web-client')
        assert e.value.status_code==401
        assert verify.call_args.kwargs['audience']=='web-client'

def test_unconfigured_disabled():
    with pytest.raises(HTTPException) as e:google_identity.verify_google_identity('token','')
    assert e.value.status_code==503

def test_transport_failure():
    from google.auth.exceptions import TransportError
    with patch.object(google_identity.id_token,'verify_oauth2_token',side_effect=TransportError('offline')):
        with pytest.raises(HTTPException) as e:google_identity.verify_google_identity('token','web-client')
        assert e.value.status_code==503

def test_google_migration_preserves_passwords():
    import importlib.util
    from pathlib import Path
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import text
    spec=importlib.util.spec_from_file_location('google_migration',Path(__file__).parents[1]/'migrations/versions/20261012_0012_google_identity.py')
    migration=importlib.util.module_from_spec(spec);spec.loader.exec_module(migration)
    engine=create_engine('sqlite://')
    with engine.begin() as conn:
        conn.execute(text('CREATE TABLE users (id INTEGER PRIMARY KEY, password_hash TEXT)'))
        conn.execute(text("INSERT INTO users VALUES (1, 'original-hash')"))
        with Operations.context(MigrationContext.configure(conn)):
            migration.upgrade()
            assert 'google_subject' in [c['name'] for c in inspect(conn).get_columns('users')]
            assert conn.execute(text('SELECT password_hash FROM users')).scalar()=='original-hash'
            migration.downgrade()
            assert 'google_subject' not in [c['name'] for c in inspect(conn).get_columns('users')]

def test_real_google_signature_verification():
    import json,time
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.primitives import serialization
    from google.auth import crypt,jwt
    key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
    private=key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption())
    public=key.public_key().public_bytes(serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo).decode()
    signer=crypt.RSASigner.from_string(private,key_id='test-key')
    now=int(time.time())
    def token(**changes):return jwt.encode(signer,{**CLAIMS,'iat':now-5,'exp':now+60,**changes}).decode()
    response=type('Response',(),{'status':200,'data':json.dumps({'test-key':public}).encode()})()
    with patch.object(google_identity,'Request',return_value=lambda *a,**kw:response):
        assert google_identity.verify_google_identity(token(),'web-client')['sub']==CLAIMS['sub']
        for invalid in [token(aud='other'),token(exp=now-1),token(iss='evil')]:
            with pytest.raises(HTTPException) as e:google_identity.verify_google_identity(invalid,'web-client')
            assert e.value.status_code==401
        signed=token();parts=signed.split('.');parts[1]=parts[1][:-3]+'abc'
        with pytest.raises(HTTPException) as e:google_identity.verify_google_identity('.'.join(parts),'web-client')
        assert e.value.status_code==401
