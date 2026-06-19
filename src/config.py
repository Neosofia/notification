import json
from typing import List

from pydantic import EmailStr, Field, computed_field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _split_csv(values: str) -> List[str]:
    return [value.strip() for value in values.split(",") if value.strip()]


class Settings(BaseSettings):
    resend_api_key: str
    notification_from: EmailStr
    notification_to: EmailStr
    cors_origins_raw: str = Field(validation_alias="cors_origins")
    log_level: str = Field("info")
    env: str = "production"
    rate_limit_storage_uri: str = "memory://"
    trusted_proxy_hops: int = Field(1, ge=0)
    max_content_length: int = 16_384
    port: int = 8005
    web_concurrency: int = 2
    gunicorn_threads: int = 2
    gunicorn_timeout: int = 30
    gunicorn_keepalive: int = 5
    platform_jwt_issuer: str | None = None
    platform_jwt_audience: str | None = None
    platform_jwt_allowed_subjects_raw: str = Field("", validation_alias="platform_jwt_allowed_subjects")
    platform_jwt_jwks_json: str | None = None
    platform_email_allowed_domains_raw: str = Field("", validation_alias="platform_email_allowed_domains")

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
        origins = _split_csv(value)
        if not origins:
            raise ValueError("CORS_ORIGINS must contain at least one origin")
        if "*" in origins:
            raise ValueError("CORS_ORIGINS must not include wildcard '*'")
        return value

    @field_validator("platform_jwt_jwks_json")
    @classmethod
    def validate_platform_jwks_json(cls, value: str | None) -> str | None:
        if value is None:
            return value
        payload = json.loads(value)
        if not isinstance(payload, dict) or not isinstance(payload.get("keys"), list):
            raise ValueError("PLATFORM_JWT_JWKS_JSON must be a JWKS object with a keys array")
        return value

    @computed_field  # type: ignore[misc]
    @property
    def cors_origins(self) -> List[str]:
        return _split_csv(self.cors_origins_raw)

    @computed_field  # type: ignore[misc]
    @property
    def platform_jwt_allowed_subjects(self) -> frozenset[str]:
        return frozenset(_split_csv(self.platform_jwt_allowed_subjects_raw))

    @computed_field  # type: ignore[misc]
    @property
    def platform_email_allowed_domains(self) -> frozenset[str]:
        return frozenset(domain.lower() for domain in _split_csv(self.platform_email_allowed_domains_raw))


settings = Settings()  # type: ignore[call-arg]
