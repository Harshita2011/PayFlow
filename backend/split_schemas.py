from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, field_serializer, field_validator

from payment_schemas import FundingRequest, RecipientRequest, TransferRequest
from social_schemas import PublicPerson


class SplitPersonInput(RecipientRequest):
    share_amount: Decimal | None = Field(default=None, gt=0, le=Decimal("100000"), decimal_places=2)

    @field_validator("share_amount", mode="before")
    @classmethod
    def exact_share(cls, value):
        return None if value is None else TransferRequest.exact_amount(value)


class SplitCreate(FundingRequest):
    title: str = Field(min_length=1, max_length=80)
    description: str = Field(default="", max_length=240)
    total_amount: Decimal = Field(gt=0, le=Decimal("100000"), decimal_places=2)
    include_creator: bool = Field(default=True, strict=True)
    mode: Literal["EQUAL", "CUSTOM"] = "EQUAL"
    creator_share: Decimal | None = Field(default=None, gt=0, le=Decimal("100000"), decimal_places=2)
    participants: list[SplitPersonInput] = Field(min_length=1, max_length=10)

    @field_validator("title", "description")
    @classmethod
    def trim_text(cls, value):
        return value.strip()

    @field_validator("title")
    @classmethod
    def title_not_blank(cls, value):
        if not value:
            raise ValueError("Enter an expense title")
        return value

    @field_validator("total_amount", "creator_share", mode="before")
    @classmethod
    def exact_amount(cls, value):
        return None if value is None else TransferRequest.exact_amount(value)


class RequestAttempt(BaseModel):
    request_id: str
    status: str
    payment_id: str | None
    created_at: datetime


class SplitPersonResponse(BaseModel):
    id: str
    person: PublicPerson
    share_amount: Decimal
    is_creator_share: bool
    status: Literal["CREATOR_SHARE", "PENDING", "PAID", "DECLINED", "CANCELLED", "EXPIRED"]
    request_id: str | None
    payment_id: str | None
    can_pay: bool
    attempts: list[RequestAttempt]

    @field_serializer("share_amount")
    def amount_string(self, value):
        return format(value, ".2f")


class SplitResponse(BaseModel):
    id: str
    title: str
    description: str
    total_amount: Decimal
    creator_share: Decimal
    contributions_received: Decimal
    outstanding_amount: Decimal
    currency: Literal["INR"] = "INR"
    expense_model: Literal["EXTERNAL_RECORD"] = "EXTERNAL_RECORD"
    status: Literal["OPEN", "SETTLED", "CANCELLED"]
    creator: PublicPerson
    is_creator: bool
    participant_count: int
    participants: list[SplitPersonResponse]
    created_at: datetime
    updated_at: datetime

    @field_serializer("total_amount", "creator_share", "contributions_received", "outstanding_amount")
    def amount_string(self, value):
        return format(value, ".2f")


class SplitPage(BaseModel):
    items: list[SplitResponse]
    next_cursor: str | None
