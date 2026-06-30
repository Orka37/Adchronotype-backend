import os
from functools import lru_cache
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    DATABASE_URL: str
    JWT_SECRET_KEY: str
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    REFRESH_TOKEN_EXPIRE_DAYS: int = 30
    APP_ENV: str = "development"

    class Config:
        env_file = ".env"
        case_sensitive = True

    @property
    def is_production(self):
        return self.APP_ENV == "production"


# cached so we don't re-read .env on every request
@lru_cache()
def get_settings():
    return Settings()
