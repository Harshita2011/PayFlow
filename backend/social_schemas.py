from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, field_serializer

from payment_schemas import RecipientRequest, TransferRequest


class PublicPerson(BaseModel):
    display_name: str
    upi_id: str


class ContactCreate(RecipientRequest):
    pass


class FavoriteUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    is_favorite: bool


class ContactResponse(PublicPerson):
    id: str
    is_favorite: bool
    created_at: datetime
    updated_at: datetime


class RecentContact(PublicPerson):
    last_interacted_at: datetime


class MoneyRequestCreate(TransferRequest):
    """Same exact decimal, note, UPI and maximum amount rules as transfers."""


class MoneyRequestResponse(BaseModel):
    id: str
    requester: PublicPerson
    payer: PublicPerson
    amount: Decimal
    note: str
    status: Literal["PENDING", "PAID", "DECLINED", "CANCELLED", "EXPIRED"]
    payment_id: str | None
    created_at: datetime
    updated_at: datetime
    expires_at: datetime

    @field_serializer("amount")
    def amount_string(self, value):
        return format(value, ".2f")


class MoneyRequestPage(BaseModel):
    items: list[MoneyRequestResponse]
    next_cursor: str | None
    pending_count: int
