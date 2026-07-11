from contextlib import asynccontextmanager
import logging
import subprocess
import time

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from sqlalchemy import text

from app.core.config import get_settings
from app.database import engine
from app.routers import auth, caregivers, cognitive_tests, predictions, sleep_logs, users

cfg = get_settings()
limiter = Limiter(key_func=get_remote_address)
logger = logging.getLogger("adchronotype.api")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))

    if cfg.RUN_MIGRATIONS_ON_STARTUP:
        logger.info("running_database_migrations")
        subprocess.run(["alembic", "upgrade", "head"], check=True)

    yield


app = FastAPI(
    title="ADChronotype API",
    version="1.0.0",
    lifespan=lifespan,
    docs_url=None if cfg.is_production else "/docs",
    redoc_url=None if cfg.is_production else "/redoc",
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=cfg.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    started = time.perf_counter()
    try:
        response = await call_next(request)
        duration_ms = round((time.perf_counter() - started) * 1000, 1)
        logger.info(
            "request_completed method=%s path=%s status=%s duration_ms=%s",
            request.method,
            request.url.path,
            response.status_code,
            duration_ms,
        )
        return response
    except Exception:
        duration_ms = round((time.perf_counter() - started) * 1000, 1)
        logger.exception(
            "request_failed method=%s path=%s duration_ms=%s",
            request.method,
            request.url.path,
            duration_ms,
        )
        raise


@app.exception_handler(Exception)
async def _unhandled(request: Request, exc: Exception):
    if cfg.is_production:
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"detail": "something went wrong on our end"},
        )
    raise exc


app.include_router(auth.router)
app.include_router(users.router)
app.include_router(predictions.router)
app.include_router(sleep_logs.router)
app.include_router(cognitive_tests.router)
app.include_router(caregivers.router)


@app.get("/", tags=["Health"])
def root():
    return {"name": "ADChronotype API", "version": "1.0.0"}


@app.get("/health", tags=["Health"])
def health():
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    return {"status": "ok", "database": "ok"}
