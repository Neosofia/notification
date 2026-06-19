from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


class ContactRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    from_email: EmailStr
    subject: str = Field(min_length=1, max_length=200)
    message: str = Field(min_length=1, max_length=10_000)

    @field_validator("subject", "message", mode="before")
    @classmethod
    def strip_and_require(cls, value: object) -> object:
        if isinstance(value, str):
            value = value.strip()
        return value

    @field_validator("subject")
    @classmethod
    def no_control_chars(cls, v: str) -> str:
        if any(ord(c) < 32 and c != "\t" for c in v):
            raise ValueError("subject must not contain control characters")
        return v


class PlatformEmailRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    to_email: EmailStr
    subject: str = Field(min_length=1, max_length=200)
    message: str = Field(min_length=1, max_length=10_000)
    from_email: EmailStr | None = None
    reply_to: EmailStr | None = None
    message_type: str = Field(default="platform", min_length=1, max_length=50, pattern=r"^[A-Za-z0-9_-]+$")

    @field_validator("subject", "message", "message_type", mode="before")
    @classmethod
    def strip_text_fields(cls, value: object) -> object:
        if isinstance(value, str):
            value = value.strip()
        return value

    @field_validator("subject")
    @classmethod
    def no_platform_subject_control_chars(cls, v: str) -> str:
        if any(ord(c) < 32 and c != "\t" for c in v):
            raise ValueError("subject must not contain control characters")
        return v
