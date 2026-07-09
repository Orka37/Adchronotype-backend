from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from app.core.config import get_settings
from app.routers import auth, caregivers, cognitive_tests, predictions, sleep_logs, users

cfg = get_settings()
limiter = Limiter(key_func=get_remote_address)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # runs once on startup — safe because create_all uses IF NOT EXISTS
    from app.database import engine, Base
    import app.models  # noqa — ensures all models are registered
    Base.metadata.create_all(bind=engine)
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
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


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
    return {"status": "ok"}
