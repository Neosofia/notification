from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


class ContactRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    from_email: EmailStr
    subject: str = Field(min_length=1)
    message: str = Field(min_length=1)

    @field_validator("subject", "message", mode="before")
    @classmethod
    def strip_and_require(cls, value: object) -> object:
        if isinstance(value, str):
            value = value.strip()
        return value
