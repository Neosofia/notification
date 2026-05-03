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
