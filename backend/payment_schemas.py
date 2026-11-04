import re
from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator


class RecipientRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    upi_id: str = Field(max_length=48)

    @field_validator("upi_id", mode="before")
    @classmethod
    def normalize_upi(cls, value):
        if not isinstance(value, str):
            raise ValueError("Enter a valid @payflow ID")
        value = value.strip().lower()
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,39}@payflow", value):
            raise ValueError("Enter a valid @payflow ID")
        return value


class TransferRequest(RecipientRequest):
    channel: Literal["QR"] | None = None
    source_account_id: int | None = Field(default=None, gt=0, strict=True)
    amount: Decimal = Field(gt=0, le=Decimal("100000.00"), max_digits=18, decimal_places=2)
    note: str = Field(default="", max_length=140)

    @field_validator("amount", mode="before")
    @classmethod
    def exact_amount(cls, value):
        if not isinstance(value, str) or not re.fullmatch(r"[0-9]{1,16}(\.[0-9]{1,2})?", value):
            raise ValueError("Send amount as a decimal string with at most two decimal places")
        return Decimal(value)

    @field_validator("note")
    @classmethod
    def clean_note(cls, value):
        return value.strip()


class FundingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DemoFundingRequest(FundingRequest):
    account_id: int | None = Field(default=None, gt=0, strict=True)


class RequestPayInput(FundingRequest):
    source_account_id: int | None = Field(default=None, gt=0, strict=True)


class SelfTransferRequest(FundingRequest):
    source_account_id: int = Field(gt=0, strict=True)
    destination_account_id: int = Field(gt=0, strict=True)
    amount: Decimal = Field(gt=0, le=Decimal("100000.00"), max_digits=18, decimal_places=2)
    note: str = Field(default="", max_length=140)

    @field_validator("amount", mode="before")
    @classmethod
    def exact_amount(cls, value):
        return TransferRequest.exact_amount(value)

    @field_validator("note")
    @classmethod
    def clean_note(cls, value):
        return value.strip()


class RecipientResponse(BaseModel):
    display_name: str
    bank_name: str
    upi_id: str


class PaymentReceipt(BaseModel):
    transaction_id: str
    type: Literal["TRANSFER", "DEMO_FUNDING", "SELF_TRANSFER", "MOBILE_RECHARGE", "BILL_PAYMENT"]
    channel: Literal["QR", "REQUEST"] | None = None
    direction: Literal["INCOMING", "OUTGOING", "FUNDING", "SELF"]
    status: Literal["SUCCESS", "FAILED"]
    amount: Decimal
    currency: Literal["INR"] = "INR"
    counterparty_name: str
    counterparty_upi_id: str | None
    recipient_upi_id: str | None
    note: str
    failure_reason: str | None
    created_at: datetime
    source_bank: str | None = None
    source_masked_account: str | None = None
    destination_bank: str | None = None
    destination_masked_account: str | None = None

    @field_serializer("amount")
    def serialize_amount(self, value: Decimal) -> str:
        return format(value, ".2f")


class PaymentHistory(BaseModel):
    items: list[PaymentReceipt]
    next_cursor: str | None
