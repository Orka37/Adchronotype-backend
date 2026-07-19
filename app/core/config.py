import os
from functools import lru_cache
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    DATABASE_URL: str
    JWT_SECRET_KEY: str
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    REFRESH_TOKEN_EXPIRE_DAYS: int = 30
    PASSWORD_RESET_EXPIRE_MINUTES: int = 30
    RESEND_API_KEY: str = ""
    PASSWORD_RESET_FROM_EMAIL: str = ""
    FRONTEND_APP_URL: str = ""
    APP_ENV: str = "development"
    FRONTEND_ORIGINS: str = ""
    RUN_MIGRATIONS_ON_STARTUP: bool = False

    class Config:
        env_file = ".env"
        case_sensitive = True

    @property
    def is_production(self):
        return self.APP_ENV == "production"

    @property
    def cors_origins(self):
        origins = [origin.strip().rstrip("/") for origin in self.FRONTEND_ORIGINS.split(",") if origin.strip()]
        if self.FRONTEND_APP_URL:
            origins.append(self.FRONTEND_APP_URL.strip().rstrip("/"))
        return sorted(set(origins))

    @property
    def cors_origin_regex(self):
        if not self.is_production and not self.cors_origins:
            return r".*"
        # Local preview ports are safe to allow explicitly and prevent Railway test previews
        # from breaking every time the frontend server starts on a new port.
        return r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$"


# cached so we don't re-read .env on every request
@lru_cache()
def get_settings():
    return Settings()
