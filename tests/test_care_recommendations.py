"""Focused tests use real auth, caregiver routes and a disposable SQLite database."""
from datetime import datetime, timedelta, timezone
from uuid import UUID
import importlib.util
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from alembic.migration import MigrationContext
from alembic.operations import Operations

from app.core.security import create_access_token
from app.database import Base, get_db
from app.models import CarePatientEvent, CarePatientMember, User
from app.routers import care_patients, care_recommendations as routes
from app.services.care_recommendations import LogEntry, CircadianConfig, CalmConfig, build_circadian_plan, detect_calm_windows


@pytest.fixture
def setup():
    engine = create_engine('sqlite://', connect_args={'check_same_thread':False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine)() as db:
        app = FastAPI()
        app.include_router(care_patients.router); app.include_router(routes.router)
        app.dependency_overrides[get_db] = lambda: db
        users = []
        for tag in ['owner','outsider','helper']:
            user = User(first_name=tag,last_name='Test',username=tag,email=f'{tag}@example.com',password_hash='unused')
            db.add(user); db.flush(); users.append(user)
        db.commit()
        auth = [{'Authorization':'Bearer '+create_access_token(str(u.id))} for u in users]
        with TestClient(app) as client:
            response = client.post('/care-patients',headers=auth[0],json={'display_name':'Fictional patient'})
            assert response.status_code == 201
            patient = response.json()['id']
            db.add(CarePatientMember(patient_id=UUID(patient),user_id=users[2].id,role='helper',status='active',granted_by_user_id=users[0].id)); db.commit()
            yield client,db,patient,auth,users
    engine.dispose()


@pytest.mark.parametrize('path',['circadian-plan','calm-windows'])
def test_permissions(setup,path):
    client,db,p,auth,users=setup
    url=f'/{path}/by-id/{p}';body={'timezone':'America/Chicago'}
    assert client.post(url,json=body).status_code==401
    assert client.post(url,json=body,headers=auth[1]).status_code==403
    assert client.post(url,json=body,headers=auth[2]).status_code==200
    member=db.query(CarePatientMember).filter_by(user_id=users[2].id).one();member.status='revoked';db.commit()
    assert client.post(url,json=body,headers=auth[2]).status_code==403


def test_history_local_time_isolation_and_saved_routine(setup):
    client,db,p,auth,users=setup
    base=datetime.now(timezone.utc).replace(hour=0,minute=0,second=0,microsecond=0)-timedelta(days=8)
    for day in range(7):
        for kind,hour,duration in [('slept',6,None),('woke',16,None),('napped',21,90),('agitated',22,None)]:
            body={'event_type':kind,'event_time':(base+timedelta(days=day,hours=hour)).isoformat(),'duration_min':duration}
            assert client.post(f'/care-patients/{p}/events',headers=auth[0],json=body).status_code==201
    routine={'usual_bedtime':'22:00','usual_wake_time':'07:00'}
    assert client.put(f'/care-patients/{p}/routine',headers=auth[0],json=routine).status_code==200
    def plan(zone='America/Chicago',days=14,patient=p):
        response=client.post(f'/circadian-plan/by-id/{patient}',headers=auth[0],json={'timezone':zone,'lookback_days':days})
        assert response.status_code==200
        return response.json()
    local=plan();utc=plan('UTC')
    assert local['status']=='ok' and local['days_of_data']==7 and len(local['blocks'])==3
    assert local['recommended_wake']!=utc['recommended_wake']
    calm=client.post(f'/calm-windows/by-id/{p}',headers=auth[0],json={'timezone':'America/Chicago'}).json()
    assert calm['status']=='ok' and calm['hard_windows']
    saved=client.get(f'/care-patients/{p}/routine',headers=auth[0]).json()
    assert saved['usual_bedtime']=='22:00' and saved['usual_wake_time']=='07:00'
    other=client.post('/care-patients',headers=auth[0],json={'display_name':'Other patient'}).json()['id']
    assert plan(patient=other)['status']=='needs_more_data'
    assert plan(days=1)['status']=='needs_more_data'


@pytest.mark.parametrize('body',[{}, {'timezone':'bad-zone'}, {'timezone':'UTC','lookback_days':0},
    {'timezone':'UTC','calm_config':{'bin_minutes':0}}, {'timezone':'UTC','calm_config':{'bin_minutes':100}},
    {'timezone':'UTC','calm_config':{'calm_threshold':0.8,'hard_threshold':0.2}},
    {'timezone':'UTC','circadian_config':{'target_wake':'25:90'}},
    {'timezone':'UTC','circadian_config':{'max_daily_shift_min':-1}}])
def test_invalid_config(setup,body):
    client,_,p,auth,_=setup
    assert client.post(f'/circadian-plan/by-id/{p}',headers=auth[0],json=body).status_code==422


def test_nap_storage_and_legacy_clients(setup):
    client,_,p,auth,_=setup;url=f'/care-patients/{p}/events'
    body={'event_type':'napped','event_time':(datetime.now(timezone.utc)-timedelta(hours=2)).isoformat()}
    old=client.post(url,headers=auth[0],json=body)
    assert old.status_code==201 and old.json()['duration_min'] is None
    nap=client.post(url,headers=auth[0],json={**body,'duration_min':30})
    assert nap.status_code==201 and nap.json()['duration_min']==30
    edit=f"{url}/{nap.json()['id']}"
    assert client.patch(edit,headers=auth[0],json={'duration_min':45}).json()['duration_min']==45
    assert client.patch(edit,headers=auth[0],json={'duration_min':0}).status_code==422
    assert client.patch(edit,headers=auth[0],json={'event_time':None}).status_code==422
    changed=client.patch(edit,headers=auth[0],json={'event_type':'woke'})
    assert changed.json()['duration_min'] is None
    assert client.post(url,headers=auth[0],json={**body,'event_type':'woke','duration_min':30}).status_code==422


def test_insufficient_observations():
    logs=[LogEntry(patient_id='p',type='wake',timestamp=datetime(2026,9,d,8)) for d in [1,2,3]]
    assert build_circadian_plan(logs,CircadianConfig()).status=='needs_more_data'
    calm=detect_calm_windows(logs,CalmConfig())
    assert calm.status=='needs_more_data' and not calm.calm_windows


def test_original_rules_and_overrides():
    logs=[LogEntry(patient_id='p',type=kind,timestamp=datetime(2026,9,d,hour),duration_min=90 if kind=='nap_start' else None)
          for d in range(1,8) for kind,hour in [('sleep',1),('wake',11),('nap_start',16),('agitation',17)]]
    plan=build_circadian_plan(logs,CircadianConfig())
    assert plan.recommended_wake=='10:30' and 'late_daytime_napping' in plan.detected_issues
    custom=build_circadian_plan(logs,CircadianConfig(max_daily_shift_min=15,nap_cutoff_hour=13))
    assert custom.recommended_wake=='10:45' and custom.blocks[1].start=='13:00'
    calm=detect_calm_windows(logs,CalmConfig())
    assert calm.hard_windows[0].start=='17:00' and calm.calm_windows[-1].end=='24:00'


def test_history_exceeds_frontend_limit_and_excludes_future(setup):
    _,db,p,_,users=setup
    base=datetime.now(timezone.utc)-timedelta(days=5)
    for i in range(270):
        db.add(CarePatientEvent(patient_id=UUID(p),logged_by_user_id=users[0].id,event_type='agitated',event_time=base+timedelta(minutes=i)))
    db.add(CarePatientEvent(patient_id=UUID(p),logged_by_user_id=users[0].id,event_type='woke',event_time=datetime.now(timezone.utc)+timedelta(days=1)))
    db.commit()
    assert len(routes.fetch_patient_logs(db,UUID(p),routes.RecommendationRequest(timezone='UTC')))==270


def test_dst_conversion(setup):
    _,db,p,_,users=setup
    now=datetime.now(timezone.utc)-timedelta(hours=1)
    db.add(CarePatientEvent(patient_id=UUID(p),logged_by_user_id=users[0].id,event_type='woke',event_time=now));db.commit()
    local=routes.fetch_patient_logs(db,UUID(p),routes.RecommendationRequest(timezone='America/Chicago'))[0]
    assert local.timestamp.astimezone(timezone.utc)==now
    from zoneinfo import ZoneInfo
    assert datetime(2026,1,15,12,tzinfo=timezone.utc).astimezone(ZoneInfo('America/Chicago')).hour==6
    assert datetime(2026,7,15,12,tzinfo=timezone.utc).astimezone(ZoneInfo('America/Chicago')).hour==7


def test_migration_preserves_existing_rows():
    path=Path(__file__).resolve().parents[1]/'migrations/versions/20261007_0011_care_nap_duration.py'
    spec=importlib.util.spec_from_file_location('nap_migration',path);migration=importlib.util.module_from_spec(spec);spec.loader.exec_module(migration)
    engine=create_engine('sqlite://')
    with engine.begin() as conn:
        conn.execute(text('CREATE TABLE care_patient_events (id INTEGER PRIMARY KEY, event_type TEXT)'))
        conn.execute(text("INSERT INTO care_patient_events VALUES (1, 'napped')"))
        with Operations.context(MigrationContext.configure(conn)):
            migration.upgrade()
            assert conn.execute(text('SELECT duration_min FROM care_patient_events')).scalar() is None
            migration.downgrade()
        assert 'duration_min' not in {c['name'] for c in inspect(conn).get_columns('care_patient_events')}
        assert conn.execute(text('SELECT event_type FROM care_patient_events')).scalar()=='napped'
    engine.dispose()
