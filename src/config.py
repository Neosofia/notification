from typing import List

from pydantic import EmailStr, Field, computed_field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _normalize_origins(origins: str) -> List[str]:
    return [origin.strip() for origin in origins.split(",") if origin.strip()]


class Settings(BaseSettings):
    resend_api_key: str
    notification_from: EmailStr
    notification_to: EmailStr
    cors_origins_raw: str = Field(validation_alias="cors_origins")
    env: str = "production"
    rate_limit_storage_uri: str = "memory://"
    max_content_length: int = 16_384
    port: int = 8005
    web_concurrency: int = 2
    gunicorn_threads: int = 2
    gunicorn_timeout: int = 30
    gunicorn_keepalive: int = 2

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="forbid",
        env_ignore_empty=True,
        populate_by_name=True,
    )

    @field_validator("cors_origins_raw")
    @classmethod
    def validate_cors_origins(cls, value: str) -> str:
        origins = _normalize_origins(value)
        if not origins:
            raise ValueError("CORS_ORIGINS must contain at least one origin")
        if "*" in origins:
            raise ValueError("CORS_ORIGINS must not include wildcard '*'")
        return value

    @computed_field  # type: ignore[misc]
    @property
    def cors_origins(self) -> List[str]:
        return _normalize_origins(self.cors_origins_raw)


settings = Settings()  # type: ignore[call-arg]
