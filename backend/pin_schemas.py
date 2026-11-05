import re
from datetime import datetime
from typing import Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator


def validate_pin(value):
    raw = value.get_secret_value()
    if not re.fullmatch(r"[0-9]{6}", raw):
        raise ValueError("Payment PIN must contain exactly six ASCII digits")
    return value


def strong_pin(value):
    validate_pin(value)
    raw = value.get_secret_value()
    if (len(set(raw)) < 3 or raw in "0123456789012345" or raw in "9876543210987654" or
        raw[:3] * 2 == raw or raw[:2] * 3 == raw or raw in {"112233", "123321", "000001", "100000", "111222"}):
        raise ValueError("Choose a less predictable payment PIN")
    return value


class PinSetup(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pin: SecretStr = Field(min_length=6, max_length=6)
    password: SecretStr = Field(min_length=1, max_length=128)

    @field_validator("pin")
    @classmethod
    def secure_pin(cls, value):
        return strong_pin(value)


class PinChange(BaseModel):
    model_config = ConfigDict(extra="forbid")
    current_pin: SecretStr = Field(min_length=6, max_length=6)
    new_pin: SecretStr = Field(min_length=6, max_length=6)

    @field_validator("current_pin")
    @classmethod
    def old_pin(cls, value):
        return validate_pin(value)

    @field_validator("new_pin")
    @classmethod
    def new_secure_pin(cls, value):
        return strong_pin(value)


class AuthorizationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pin: SecretStr = Field(min_length=6, max_length=6)
    operation: Literal["TRANSFER", "SELF_TRANSFER", "REQUEST", "MOBILE_RECHARGE", "BILL_PAYMENT"]
    payload: dict
    reference_id: UUID | None = None

    @field_validator("pin")
    @classmethod
    def pin_format(cls, value):
        return validate_pin(value)


class AuthorizationResponse(BaseModel):
    authorization_token: str
    expires_at: datetime
    source_account_id: int
    amount: str
    operation: str


class SecurityStatus(BaseModel):
    pin_configured: bool
    locked_until: datetime | None
    remaining_attempts: int
    single_limit: str
    daily_limit: str
    daily_count_limit: int
    daily_amount_used: str
    daily_count_used: int
    reset_timezone: Literal["UTC"] = "UTC"


class AuditItem(BaseModel):
    id: str
    event_type: str
    created_at: datetime
    operation_id: str | None
    outcome: str
    details: dict


class AuditPage(BaseModel):
    items: list[AuditItem]
    next_cursor: str | None
