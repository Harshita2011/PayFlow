from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_serializer

from models import DemoBank


class AccountCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    bank_name: DemoBank


class AccountResponse(BaseModel):
    id: int
    bank_name: DemoBank
    masked_account_number: str
    upi_id: str
    balance: Decimal = Field(ge=0, max_digits=18, decimal_places=2)
    created_at: datetime

    @field_serializer("balance")
    def serialize_balance(self, value: Decimal) -> str:
        return format(value, ".2f")
