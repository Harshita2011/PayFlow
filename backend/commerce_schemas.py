from datetime import date, datetime
from decimal import Decimal
from pydantic import BaseModel, ConfigDict, Field, field_validator, field_serializer
from payment_schemas import PaymentReceipt
from config import DEMO_MOBILE_PATTERN, DEMO_MOBILE_PREFIXES


class StrictInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RechargeInput(StrictInput):
    mobile: str = Field(pattern=DEMO_MOBILE_PATTERN)
    plan_id: str = Field(min_length=1, max_length=32)
    source_account_id: int = Field(gt=0, strict=True)


class BillLookup(StrictInput):
    biller_id: str = Field(min_length=1, max_length=24)
    reference: str = Field(pattern=r"^DEMO[0-9]{6}$")


class SaveBillerInput(BillLookup):
    nickname: str = Field(default="", max_length=40)

    @field_validator("nickname")
    @classmethod
    def trim(cls, value):
        return value.strip()


class BillPayInput(StrictInput):
    source_account_id: int = Field(gt=0, strict=True)


class OperatorOut(BaseModel):
    id: str
    name: str


class RechargeOperatorOut(OperatorOut):
    mobile_pattern: str = DEMO_MOBILE_PATTERN
    mobile_prefixes: str = DEMO_MOBILE_PREFIXES


class PlanOut(BaseModel):
    id: str
    operator_id: str
    name: str
    price: Decimal
    validity_days: int
    description: str

    @field_serializer("price")
    def money(self, value):
        return format(value, ".2f")


class BillerOut(OperatorOut):
    category: str
    description: str
    reference_format: str = "DEMO followed by six digits, e.g. DEMO000001"


class RechargeOut(BaseModel):
    id: str
    operator: str
    plan_id: str
    plan_name: str
    masked_mobile: str
    status: str
    created_at: datetime
    receipt: PaymentReceipt


class BillOut(BaseModel):
    id: str
    biller_id: str
    biller: str
    category: str
    masked_reference: str
    billing_period: str
    amount_due: Decimal
    due_date: date
    status: str
    created_at: datetime
    paid_at: datetime | None
    receipt: PaymentReceipt | None

    @field_serializer("amount_due")
    def money(self, value):
        return format(value, ".2f")


class SavedBillerOut(BaseModel):
    id: str
    biller_id: str
    biller: str
    nickname: str
    masked_reference: str


class CommercePage(BaseModel):
    items: list[BillOut | RechargeOut]
    next_cursor: str | None
