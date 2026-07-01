from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

from app.core.config import get_settings

cfg = get_settings()

# strip any sslmode param and force disable —
# Railway's public proxy doesn't use SSL
db_url = cfg.DATABASE_URL
if "?" in db_url:
    db_url = db_url.split("?")[0]
db_url = db_url + "?sslmode=disable"

engine = create_engine(
    db_url,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
    pool_timeout=30,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()