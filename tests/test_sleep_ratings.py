from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4
import importlib.util
from pathlib import Path
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from alembic.migration import MigrationContext
from alembic.operations import Operations
from app.database import Base, get_db
from app.core.deps import get_current_user
from app.models import SleepLog
from app.routers import sleep_logs

@pytest.fixture
def setup():
    engine=create_engine('sqlite://',connect_args={'check_same_thread':False},poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine)() as db:
        me=SimpleNamespace(id=uuid4())
        app=FastAPI(); app.include_router(sleep_logs.router)
        app.dependency_overrides[get_db]=lambda:db
        app.dependency_overrides[get_current_user]=lambda:me
        with TestClient(app) as client: yield client,db,me
    engine.dispose()

def body(score):
    return dict(sleep_time='22:00',wake_time='06:30',duration_hours=8.5,quality_score=score,logged_date='2026-10-15T12:00:00Z')

@pytest.mark.parametrize('score',[1,10])
def test_rating_boundaries(setup,score):
    c,db,me=setup
    r=c.post('/sleep-logs/ratings',json=body(score))
    assert r.status_code==201
    assert r.json()['quality_scale']=='rating_1_10'
    assert db.query(SleepLog).one().quality_score==score

@pytest.mark.parametrize('score',[0,11,21,-1])
def test_reject_invalid_ratings(setup,score):
    c,db,me=setup
    assert c.post('/sleep-logs/ratings',json=body(score)).status_code==422
    assert db.query(SleepLog).count()==0

def test_old_clients_and_owner_isolation(setup):
    c,db,me=setup
    old=c.post('/sleep-logs',json=body(21)).json()
    new=c.post('/sleep-logs/ratings',json=body(8)).json()
    assert old['quality_scale']=='legacy_0_21'
    assert c.post('/sleep-logs',json={**body(8),'quality_scale':'rating_1_10'}).status_code==422
    assert [x['id'] for x in c.get('/sleep-logs').json()]==[old['id']]
    assert len(c.get('/sleep-logs?include_ratings=true').json())==2
    me.id=uuid4()
    assert c.get('/sleep-logs?include_ratings=true').json()==[]
    assert c.get('/sleep-logs/'+new['id']).status_code==404

def test_migration_preserves_original_scores():
    path=Path(__file__).parents[1]/'migrations/versions/20261015_0013_sleep_quality_scale.py'
    spec=importlib.util.spec_from_file_location('scale_migration',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    engine=create_engine('sqlite://')
    with engine.begin() as connection:
        connection.execute(text('CREATE TABLE sleep_logs (id INTEGER PRIMARY KEY, quality_score INTEGER NOT NULL)'))
        connection.execute(text('INSERT INTO sleep_logs VALUES (1,0),(2,21)'))
        with Operations.context(MigrationContext.configure(connection)):
            module.upgrade()
            assert connection.execute(text('SELECT quality_score,quality_scale FROM sleep_logs ORDER BY id')).all()==[(0,'legacy_0_21'),(21,'legacy_0_21')]
            connection.execute(text("INSERT INTO sleep_logs VALUES (3,8,'rating_1_10')"))
            with pytest.raises(RuntimeError):module.downgrade()
